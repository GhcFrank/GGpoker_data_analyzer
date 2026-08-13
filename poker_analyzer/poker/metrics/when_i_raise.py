from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from poker.metrics.base import Metric, register
from poker.models import Action, Hand, HandDataset

STREETS = ("preflop", "flop", "turn", "river")
SIZE_TARGETS: dict[str, float] = {"33": 33.0, "66": 66.0, "110": 110.0}
SIZE_TOLERANCE_PP = 10.0  # absolute percentage points
PLAYER_COUNT_ALL = {"2", "3+"}
POSITION_ALL = {"IP", "OOP", "OTHER"}
SIZE_ALL = set(SIZE_TARGETS)


@dataclass
class RaiseSpot:
    street: str
    player_count: int
    position: str  # IP | OOP | OTHER
    size_pct: float
    all_fold: bool
    has_call: bool
    has_reraise: bool


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


def _spot_matches(spot: RaiseSpot, options: dict[str, Any]) -> bool:
    street_opt = str(options.get("street") or "ALL").strip().lower()
    if street_opt and street_opt != "all":
        if spot.street != street_opt:
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

        for hand in dataset.sorted_hands():
            hand_spots = [s for s in extract_hero_raise_spots(hand) if _spot_matches(s, opts)]
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

        return {
            "metric_id": self.id,
            "name": self.name,
            "spot_count": n,
            "hand_count": hands_with_spot,
            "all_fold": {"count": all_fold_n, "pct": pct(all_fold_n)},
            "call": {"count": call_n, "pct": pct(call_n)},
            "reraise": {"count": reraise_n, "pct": pct(reraise_n)},
            "options": {
                "street": str(opts.get("street") or "ALL"),
                "player_counts": _as_str_list(opts.get("player_counts")) or sorted(PLAYER_COUNT_ALL),
                "sizes": _as_str_list(opts.get("sizes")) or sorted(SIZE_ALL, key=lambda x: float(x)),
                "positions": _as_str_list(opts.get("positions")) or sorted(POSITION_ALL),
            },
        }
