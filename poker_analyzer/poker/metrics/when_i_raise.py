from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from poker.board_texture import FLOP_FILTER_KEYS, flop_texture_matches
from poker.metrics.base import Metric, register
from poker.models import Action, Hand, HandDataset

STREETS = ("preflop", "flop", "turn", "river")
POSTFLOP_STREETS = frozenset({"flop", "turn", "river"})
TURN_DETAIL_STREETS = frozenset({"turn", "river"})
TURN_DETAIL_FLOP_LINES = frozenset({"flop_checkcheck", "flop_call", "flop_raise"})
SIZE_TARGETS: dict[str, float] = {"33": 33.0, "66": 66.0, "110": 110.0}
SIZE_TOLERANCE_PP = 10.0  # absolute percentage points
PLAYER_COUNT_ALL = {"2", "3+"}
POSITION_ALL = {"IP", "OOP", "OTHER"}
SIZE_ALL = set(SIZE_TARGETS)
FLOP_FILTER_ALL = set(FLOP_FILTER_KEYS)
STREET_ALL = set(STREETS)


@dataclass
class RaiseSpot:
    street: str
    player_count: int
    position: str  # IP | OOP | OTHER
    size_pct: float
    all_fold: bool
    has_call: bool
    has_reraise: bool
    flop_cards: tuple[str, ...] = ()


def _seat_order_clockwise(seats: Iterable[int], start_seat: int) -> list[int]:
    ordered = sorted(seats)
    if not ordered:
        return []
    # First seat strictly after start, then wrap.
    after = [s for s in ordered if s > start_seat]
    before = [s for s in ordered if s <= start_seat]
    return after + before


def _name_to_seat(hand: Hand) -> dict[str, int]:
    return {name: seat for seat, name in hand.seat_names.items()}


def _action_order_for_street(hand: Hand, street: str, active: set[str]) -> list[str]:
    """Return active players in acting order for the street."""
    if hand.button_seat is None or not hand.seat_names:
        # Fallback: order by first appearance in street actions.
        seen: list[str] = []
        for act in hand.actions:
            if act.street != street:
                continue
            if act.player in active and act.player not in seen:
                seen.append(act.player)
        return seen

    seats_by_name = _name_to_seat(hand)
    active_seats = [seats_by_name[n] for n in active if n in seats_by_name]
    if not active_seats:
        return []

    button = hand.button_seat
    if street == "preflop":
        # Preflop: UTG (left of BB) acts first; BB acts last.
        # SB = first seat after button, BB = second after button.
        clockwise_from_btn = _seat_order_clockwise(hand.seat_names.keys(), button)
        if len(clockwise_from_btn) >= 2:
            bb_seat = clockwise_from_btn[1]
        elif clockwise_from_btn:
            bb_seat = clockwise_from_btn[0]
        else:
            bb_seat = button
        order_seats = _seat_order_clockwise(active_seats, bb_seat)
    else:
        # Postflop: SB (left of button) acts first; button acts last.
        order_seats = _seat_order_clockwise(active_seats, button)

    seat_to_name = {seat: name for seat, name in hand.seat_names.items()}
    return [seat_to_name[s] for s in order_seats if s in seat_to_name]


def _active_before_index(hand: Hand, index: int) -> set[str]:
    """Players still with cards just before actions[index]."""
    active = set(hand.seat_names.values())
    target_street = hand.actions[index].street
    for i, act in enumerate(hand.actions):
        if i >= index:
            break
        if act.action == "fold":
            active.discard(act.player)
    # Restrict to players who reached this street: anyone who folded earlier
    # is already removed. Players who never acted but still have cards remain.
    # Also drop anyone who folded on a previous street (already handled).
    _ = target_street
    return active


def _classify_position(order: list[str], hero: str = "Hero") -> str:
    if hero not in order:
        return "OTHER"
    if len(order) == 1:
        return "IP"
    if order[0] == hero:
        return "OOP"
    if order[-1] == hero:
        return "IP"
    return "OTHER"


def _response_flags(hand: Hand, raise_index: int) -> tuple[bool, bool, bool]:
    """
    After Hero bet/raise at raise_index, classify opponent responses on that street.

    Returns (all_fold, has_call, has_reraise).
    """
    street = hand.actions[raise_index].street
    has_call = False
    has_reraise = False
    saw_opponent = False

    for act in hand.actions[raise_index + 1 :]:
        if act.street != street:
            break
        if act.is_hero:
            # Hero acted again — responses to this aggression are done.
            break
        if act.action in ("show", "muck"):
            continue
        if act.action in ("fold", "check", "call", "bet", "raise"):
            saw_opponent = True
        if act.action == "call":
            has_call = True
        elif act.action == "raise":
            has_reraise = True
        elif act.action == "bet":
            # Facing a check-raise style oddity shouldn't happen after a bet/raise;
            # treat as reraise/aggression.
            has_reraise = True

    all_fold = saw_opponent and not has_call and not has_reraise
    # If nobody left to act (e.g. everyone already all-in) — not all_fold.
    if not saw_opponent:
        all_fold = False
    return all_fold, has_call, has_reraise


def extract_hero_raise_spots(hand: Hand) -> list[RaiseSpot]:
    """Each Hero bet or raise that faces at least one opponent still in."""
    spots: list[RaiseSpot] = []
    for idx, act in enumerate(hand.actions):
        if not act.is_hero:
            continue
        if act.action not in ("bet", "raise"):
            continue
        if act.pot_before <= 0:
            continue

        active = _active_before_index(hand, idx)
        if "Hero" not in active:
            continue
        # Must have someone left to respond.
        opponents = active - {"Hero"}
        if not opponents:
            continue

        order = _action_order_for_street(hand, act.street, active)
        position = _classify_position(order)
        size_pct = round(100.0 * act.amount / act.pot_before, 4)
        all_fold, has_call, has_reraise = _response_flags(hand, idx)

        spots.append(
            RaiseSpot(
                street=act.street,
                player_count=len(active),
                position=position,
                size_pct=size_pct,
                all_fold=all_fold,
                has_call=has_call,
                has_reraise=has_reraise,
                flop_cards=hand.flop_cards if act.street in POSTFLOP_STREETS else (),
            )
        )
    return spots


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [str(v) for v in value]


def _axis_selected(selected: list[str], universe: set[str]) -> set[str]:
    return {s for s in selected if s in universe}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _selected_streets(options: dict[str, Any]) -> set[str] | None:
    """
    Return allowed streets, or None meaning no street restriction.

    Accepts:
      streets: ["flop", "turn"]
      street: "flop" | "ALL"   (legacy single value)
    """
    if "streets" in options:
        raw = _as_str_list(options.get("streets"))
        chosen = {s.strip().lower() for s in raw if s.strip()}
        if not chosen or "all" in chosen:
            return None
        return {s for s in chosen if s in STREET_ALL}

    street_opt = str(options.get("street") or "ALL").strip().lower()
    if not street_opt or street_opt == "all":
        return None
    if street_opt in STREET_ALL:
        return {street_opt}
    return set()


def _hand_reached_turn(hand: Hand) -> bool:
    return any(act.street == "turn" for act in hand.actions)


def _flop_betting_actions(hand: Hand) -> list[Action]:
    return [
        act
        for act in hand.actions
        if act.street == "flop" and act.action in ("fold", "check", "call", "bet", "raise")
    ]


def classify_flop_to_turn(hand: Hand) -> str | None:
    """
    Classify how the hand entered the turn based on flop action.

    Returns one of flop_checkcheck | flop_call | flop_raise, or None if the
    hand did not reach the turn.
    """
    if not _hand_reached_turn(hand):
        return None

    flop_acts = _flop_betting_actions(hand)
    if not any(act.action in ("bet", "raise") for act in flop_acts):
        return "flop_checkcheck"

    last_agg_index: int | None = None
    for idx, act in enumerate(hand.actions):
        if act.street == "flop" and act.action in ("bet", "raise"):
            last_agg_index = idx

    if last_agg_index is None:
        return None

    last_agg = hand.actions[last_agg_index]
    if last_agg.is_hero:
        return "flop_raise"

    hero_last_call_index: int | None = None
    for idx, act in enumerate(hand.actions):
        if act.street == "flop" and act.is_hero and act.action == "call":
            hero_last_call_index = idx

    if hero_last_call_index is None:
        return None

    for act in hand.actions[hero_last_call_index + 1 :]:
        if act.street != "flop":
            break
        if act.action in ("bet", "raise", "call"):
            return None

    return "flop_call"


def _parse_turn_detail_lines(value: Any) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        key = value.strip()
        return {key} if key in TURN_DETAIL_FLOP_LINES else set()
    out: set[str] = set()
    for item in value:
        key = str(item).strip()
        if key in TURN_DETAIL_FLOP_LINES:
            out.add(key)
    return out


def _parse_flop_texture_constraints(value: Any) -> dict[str, bool]:
    """
    Parse enabled flop texture filters.

    Accepts:
      {"high_card": true, "paired": false}
      [{"key": "high_card", "want": true}, ...]
    Only known keys are kept. Empty → no texture filter.
    """
    if not value:
        return {}
    out: dict[str, bool] = {}
    if isinstance(value, dict):
        for key, want in value.items():
            k = str(key)
            if k in FLOP_FILTER_ALL:
                out[k] = bool(want)
        return out
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            k = str(item.get("key") or item.get("id") or "")
            if k not in FLOP_FILTER_ALL:
                continue
            if "want" in item:
                out[k] = bool(item["want"])
            elif "value" in item:
                out[k] = bool(item["value"])
            else:
                out[k] = True
    return out


def _size_matches(size_pct: float, selected: list[str]) -> bool:
    chosen = _axis_selected(selected, SIZE_ALL)
    if not chosen:
        return False
    if chosen == SIZE_ALL:
        return True
    for key in chosen:
        target = SIZE_TARGETS[key]
        if abs(size_pct - target) <= SIZE_TOLERANCE_PP:
            return True
    return False


def _spot_matches(
    spot: RaiseSpot,
    options: dict[str, Any],
    *,
    flop_line: str | None = None,
) -> bool:
    flop_detail = _truthy(options.get("flop_detail"))
    turn_detail = _truthy(options.get("turn_detail"))
    allowed_streets = _selected_streets(options)

    if turn_detail:
        if spot.street not in TURN_DETAIL_STREETS:
            return False
        if allowed_streets is not None:
            turn_allowed = allowed_streets & TURN_DETAIL_STREETS
            if not turn_allowed or spot.street not in turn_allowed:
                return False
        selected_lines = _parse_turn_detail_lines(options.get("turn_flop_lines"))
        if selected_lines:
            if flop_line is None or flop_line not in selected_lines:
                return False
    elif flop_detail:
        # Flop detail only applies to postflop raise spots.
        if spot.street not in POSTFLOP_STREETS:
            return False
        if allowed_streets is not None:
            postflop_allowed = allowed_streets & POSTFLOP_STREETS
            if not postflop_allowed or spot.street not in postflop_allowed:
                return False
    elif allowed_streets is not None:
        if spot.street not in allowed_streets:
            return False

    player_counts = _as_str_list(options.get("player_counts"))
    # Missing key (API default) → no filter; explicit empty list → no spots.
    if "player_counts" in options:
        chosen = _axis_selected(player_counts, PLAYER_COUNT_ALL)
        if not chosen:
            return False
        if chosen != PLAYER_COUNT_ALL:
            if spot.player_count == 2:
                tag = "2"
            elif spot.player_count >= 3:
                tag = "3+"
            else:
                return False
            if tag not in chosen:
                return False

    if "sizes" in options:
        if not _size_matches(spot.size_pct, _as_str_list(options.get("sizes"))):
            return False

    if "positions" in options:
        chosen_pos = _axis_selected(_as_str_list(options.get("positions")), POSITION_ALL)
        if not chosen_pos:
            return False
        if chosen_pos != POSITION_ALL and spot.position not in chosen_pos:
            return False

    if flop_detail or turn_detail:
        constraints = _parse_flop_texture_constraints(options.get("flop_textures"))
        if constraints:
            if len(spot.flop_cards) != 3:
                return False
            if not flop_texture_matches(spot.flop_cards, constraints):
                return False

    return True


@register
class WhenIRaiseMetric(Metric):
    """Frequency of fold / call / reraise when Hero bets or raises."""

    id = "when_i_raise"
    name = "When I Raise"
    description = "当 Hero 下注/加注时，对手全弃 / 跟注 / 再加注的频率"
    chart_type = "stats"

    def compute(self, dataset: HandDataset, options: dict[str, Any] | None = None) -> dict[str, Any]:
        opts = options or {}
        spots: list[RaiseSpot] = []
        hands_with_spot = 0

        turn_detail = _truthy(opts.get("turn_detail"))

        for hand in dataset.sorted_hands():
            flop_line = classify_flop_to_turn(hand) if turn_detail else None
            hand_spots = [
                s
                for s in extract_hero_raise_spots(hand)
                if _spot_matches(s, opts, flop_line=flop_line)
            ]
            if hand_spots:
                hands_with_spot += 1
            spots.extend(hand_spots)

        n = len(spots)
        all_fold_n = sum(1 for s in spots if s.all_fold)
        call_n = sum(1 for s in spots if s.has_call)
        reraise_n = sum(1 for s in spots if s.has_reraise)

        def pct(count: int) -> float | None:
            if n <= 0:
                return None
            return round(100.0 * count / n, 2)

        streets = _selected_streets(opts)
        flop_detail = _truthy(opts.get("flop_detail"))
        turn_detail = _truthy(opts.get("turn_detail"))
        return {
            "metric_id": self.id,
            "name": self.name,
            "spot_count": n,
            "hand_count": hands_with_spot,
            "all_fold": {"count": all_fold_n, "pct": pct(all_fold_n)},
            "call": {"count": call_n, "pct": pct(call_n)},
            "reraise": {"count": reraise_n, "pct": pct(reraise_n)},
            "options": {
                "streets": sorted(streets) if streets is not None else ["ALL"],
                "flop_detail": flop_detail,
                "turn_detail": turn_detail,
                "turn_flop_lines": sorted(_parse_turn_detail_lines(opts.get("turn_flop_lines")))
                if turn_detail
                else [],
                "player_counts": _as_str_list(opts.get("player_counts")) or sorted(PLAYER_COUNT_ALL),
                "sizes": _as_str_list(opts.get("sizes")) or sorted(SIZE_ALL, key=lambda x: float(x)),
                "positions": _as_str_list(opts.get("positions")) or sorted(POSITION_ALL),
                "flop_textures": _parse_flop_texture_constraints(opts.get("flop_textures"))
                if flop_detail or turn_detail
                else {},
            },
        }
