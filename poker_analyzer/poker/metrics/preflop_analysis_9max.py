from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from poker.equity import preflop_equity
from poker.filters import normalize_stakes
from poker.metrics.base import Metric, register
from poker.metrics.preflop_hand_details import (
    build_hand_details as _build_hand_details,
    combo_or_unknown as _combo_or_unknown,
    combo_table as _combo_table,
    first_raising_actor_after as _first_raising_actor_after,
    player_cards as _player_cards,
)
from poker.models import Action, Hand, HandDataset
from poker.positions.nine_max import POSITION_ORDER, NINE_MAX_PROFILE, position_map

HERO = "Hero"
ACTIONS_IMPLEMENTED = frozenset({"open_raise", "3bet", "4bet", "5bet", "3bet_matrix", "4bet_matrix"})


def positions_in_front(hero_pos: str) -> list[str]:
    return NINE_MAX_PROFILE.positions_in_front(hero_pos)


def positions_except(hero_pos: str) -> list[str]:
    return NINE_MAX_PROFILE.positions_except(hero_pos)


def _bb_size(hand: Hand) -> float | None:
    for act in hand.actions:
        if act.action == "posts big blind" and act.amount > 0:
            return act.amount
    key = normalize_stakes(hand.stakes)
    if not key:
        return None
    try:
        return float(key.split("/")[1])
    except (IndexError, ValueError):
        return None


def _hero_showdown_share(hand: Hand) -> float:
    """1 = Hero won the pot, 0.5 = chopped, 0 = lost."""
    if hand.hero_collected <= 0:
        return 0.0
    total = hand.extra.get("total_collected") or 0.0
    if total <= 0:
        total = max(hand.total_pot - hand.fees, hand.hero_collected)
    if hand.hero_collected + 1e-9 >= total:
        return 1.0
    return 0.5


def _raise_to_amount(act: Action) -> float:
    if act.to_amount > 0:
        return act.to_amount
    return act.amount


def _is_open_size(act: Action, bb: float) -> bool:
    return _raise_to_amount(act) + 1e-9 >= 2.0 * bb


def _has_limp(hand: Hand) -> bool:
    """True if anyone called before the first preflop raise (SB complete included)."""
    seen_raise = False
    for act in hand.actions:
        if act.street != "preflop":
            continue
        if act.action in ("raise", "bet"):
            seen_raise = True
        elif act.action == "call" and not seen_raise:
            return True
    return False


def _has_filtered_calls(hand: Hand) -> bool:
    """
    True if the hand has call-open, cold-call 3bet, or cold-call 4bet.

    Opener calling a 3bet / 3bettor calling a 4bet / 4bettor calling a 5bet
    are not cold calls and do not match.
    """
    bb = _bb_size(hand)
    if bb is None:
        return False
    raises = iter_preflop_opensize_raises(hand, bb)
    opener = raises[0][1].player if len(raises) >= 1 else None
    threebettor = raises[1][1].player if len(raises) >= 2 else None
    raise_at = {idx: n for n, (idx, _act) in enumerate(raises, start=1)}
    level = 0
    for idx, act in enumerate(hand.actions):
        if act.street != "preflop":
            continue
        if idx in raise_at:
            level = raise_at[idx]
            continue
        if act.action != "call":
            continue
        if level == 1:
            return True
        if level == 2 and opener and act.player != opener:
            return True
        if level == 3 and threebettor and act.player != threebettor and act.player != opener:
            return True
    return False


def hand_allowed(hand: Hand, allow_limp: bool, allow_call: bool) -> bool:
    if not allow_limp and _has_limp(hand):
        return False
    if not allow_call and _has_filtered_calls(hand):
        return False
    return True


def _iter_filtered_hands(dataset: HandDataset, allow_limp: bool, allow_call: bool) -> Iterable[Hand]:
    for hand in dataset.sorted_hands():
        if hand_allowed(hand, allow_limp, allow_call):
            yield hand


def _option_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def iter_preflop_opensize_raises(hand: Hand, bb: float) -> list[tuple[int, Action]]:
    """Raises/bets on preflop whose size is at least 2bb, in order."""
    found: list[tuple[int, Action]] = []
    for idx, act in enumerate(hand.actions):
        if act.street != "preflop":
            continue
        if act.action not in ("raise", "bet"):
            continue
        if not _is_open_size(act, bb):
            continue
        found.append((idx, act))
    return found


def _response_after(hand: Hand, start_index: int) -> tuple[bool, bool, bool]:
    """After start_index on the same street: (all_fold, has_call, has_raise)."""
    street = hand.actions[start_index].street
    has_call = False
    has_raise = False
    saw_opponent = False
    for act in hand.actions[start_index + 1 :]:
        if act.street != street:
            break
        if act.is_hero:
            break
        if act.action in ("show", "muck"):
            continue
        if act.action in ("fold", "check", "call", "bet", "raise"):
            saw_opponent = True
        if act.action == "call":
            has_call = True
        elif act.action in ("raise", "bet"):
            has_raise = True
    all_fold = saw_opponent and not has_call and not has_raise
    return all_fold, has_call, has_raise


@dataclass
class OpenRaiseSpot:
    all_fold: bool
    faced_3bet: bool
    threebettor: str | None
    threebettor_position: str | None
    threebet_combo: str | None


@dataclass
class ThreeBetSpot:
    opener_fold: bool
    opener_call: bool
    opener_4bet: bool
    all_fold: bool
    cold_4bet: bool
    opener_acted: bool
    opener: str
    opener_position: str
    opener_combo: str | None
    cold_4bettor: str | None
    cold_4bettor_position: str | None
    cold_4bet_combo: str | None


@dataclass
class ThreeBetMatrixSpot:
    three_pos: str
    opener_pos: str
    opener_fold: bool
    opener_call: bool
    opener_4bet: bool
    opener_acted: bool
    call_combo: str | None
    fourbet_combo: str | None


def extract_open_raise(hand: Hand, hero_pos: str) -> OpenRaiseSpot | None:
    bb = _bb_size(hand)
    if bb is None:
        return None
    pos = position_map(hand)
    if pos.get(HERO) != hero_pos:
        return None
    raises = iter_preflop_opensize_raises(hand, bb)
    if not raises:
        return None
    idx, act = raises[0]
    if not act.is_hero:
        return None
    all_fold, _has_call, has_raise = _response_after(hand, idx)
    threebet_act = _first_raising_actor_after(hand, idx) if has_raise else None
    return OpenRaiseSpot(
        all_fold=all_fold,
        faced_3bet=has_raise,
        threebettor=threebet_act.player if threebet_act else None,
        threebettor_position=pos.get(threebet_act.player) if threebet_act else None,
        threebet_combo=_combo_or_unknown(hand, threebet_act.player) if threebet_act else None,
    )


def extract_3bet(hand: Hand, hero_pos: str, opener_pos: str) -> ThreeBetSpot | None:
    if opener_pos not in positions_in_front(hero_pos):
        return None
    bb = _bb_size(hand)
    if bb is None:
        return None
    pos = position_map(hand)
    if pos.get(HERO) != hero_pos:
        return None
    raises = iter_preflop_opensize_raises(hand, bb)
    if len(raises) < 2:
        return None
    _open_idx, open_act = raises[0]
    three_idx, three_act = raises[1]
    if not three_act.is_hero:
        return None
    if pos.get(open_act.player) != opener_pos:
        return None

    opener = open_act.player
    hero_order = POSITION_ORDER.index(hero_pos)
    opener_fold = opener_call = opener_4bet = False
    opener_acted = False
    all_fold, _has_call, _has_raise = _response_after(hand, three_idx)
    cold_4bet = False
    cold_4bettor = None
    cold_4bettor_position = None
    cold_4bet_combo = None
    raise_before_opener = False

    street = three_act.street
    for act in hand.actions[three_idx + 1 :]:
        if act.street != street:
            break
        if act.is_hero:
            break
        if act.action in ("show", "muck"):
            continue
        if act.player == opener and act.action in ("fold", "call", "raise", "bet", "check"):
            if not raise_before_opener:
                opener_acted = True
                if act.action == "fold":
                    opener_fold = True
                elif act.action == "call":
                    opener_call = True
                elif act.action in ("raise", "bet"):
                    opener_4bet = True
        if act.action in ("raise", "bet") and act.player != opener:
            vill_pos = pos.get(act.player)
            if vill_pos in POSITION_ORDER and POSITION_ORDER.index(vill_pos) > hero_order:
                if not cold_4bet:
                    cold_4bet = True
                    cold_4bettor = act.player
                    cold_4bettor_position = vill_pos
                    cold_4bet_combo = _combo_or_unknown(hand, act.player)
            raise_before_opener = True

    return ThreeBetSpot(
        opener_fold=opener_fold,
        opener_call=opener_call,
        opener_4bet=opener_4bet,
        all_fold=all_fold,
        cold_4bet=cold_4bet,
        opener_acted=opener_acted,
        opener=opener,
        opener_position=opener_pos,
        opener_combo=(
            _combo_or_unknown(hand, opener)
            if opener_fold or opener_call or opener_4bet
            else None
        ),
        cold_4bettor=cold_4bettor,
        cold_4bettor_position=cold_4bettor_position,
        cold_4bet_combo=cold_4bet_combo,
    )


def extract_3bet_matrix_spot(hand: Hand) -> ThreeBetMatrixSpot | None:
    """Any open → 3bet spot; tracks opener fold/call/4bet and known combos."""
    bb = _bb_size(hand)
    if bb is None:
        return None
    pos = position_map(hand)
    raises = iter_preflop_opensize_raises(hand, bb)
    if len(raises) < 2:
        return None
    _open_idx, open_act = raises[0]
    three_idx, three_act = raises[1]
    opener_pos = pos.get(open_act.player)
    three_pos = pos.get(three_act.player)
    if opener_pos not in POSITION_ORDER or three_pos not in POSITION_ORDER:
        return None
    if opener_pos == three_pos:
        return None
    if POSITION_ORDER.index(three_pos) <= POSITION_ORDER.index(opener_pos):
        return None

    opener = open_act.player
    opener_fold = opener_call = opener_4bet = False
    opener_acted = False
    raise_before_opener = False
    street = three_act.street
    for act in hand.actions[three_idx + 1 :]:
        if act.street != street:
            break
        if act.action in ("show", "muck"):
            continue
        if act.player == opener and act.action in ("fold", "call", "raise", "bet", "check"):
            if not raise_before_opener:
                opener_acted = True
                if act.action == "fold":
                    opener_fold = True
                elif act.action == "call":
                    opener_call = True
                elif act.action in ("raise", "bet"):
                    opener_4bet = True
            break
        if act.action in ("raise", "bet") and act.player != opener:
            raise_before_opener = True

    call_combo = _combo_or_unknown(hand, opener) if opener_call else None
    fourbet_combo = _combo_or_unknown(hand, opener) if opener_4bet else None
    return ThreeBetMatrixSpot(
        three_pos=three_pos,
        opener_pos=opener_pos,
        opener_fold=opener_fold,
        opener_call=opener_call,
        opener_4bet=opener_4bet,
        opener_acted=opener_acted,
        call_combo=call_combo,
        fourbet_combo=fourbet_combo,
    )


@dataclass
class FourBetMatrixSpot:
    four_pos: str
    three_pos: str
    three_fold: bool
    three_call: bool
    three_5bet: bool
    three_faced: bool
    call_combo: str | None
    fivebet_combo: str | None


def extract_4bet_matrix_spot(hand: Hand) -> FourBetMatrixSpot | None:
    """Any open → 3bet → 4bet spot; tracks 3bettor fold/call/5bet and known combos."""
    bb = _bb_size(hand)
    if bb is None:
        return None
    pos = position_map(hand)
    raises = iter_preflop_opensize_raises(hand, bb)
    if len(raises) < 3:
        return None
    _three_idx, three_act = raises[1]
    four_idx, four_act = raises[2]
    three_pos = pos.get(three_act.player)
    four_pos = pos.get(four_act.player)
    if three_pos not in POSITION_ORDER or four_pos not in POSITION_ORDER:
        return None
    if three_pos == four_pos:
        return None

    threebettor = three_act.player
    three_fold = three_call = three_5bet = False
    three_faced = False
    raise_before = False
    street = four_act.street
    for act in hand.actions[four_idx + 1 :]:
        if act.street != street:
            break
        if act.action in ("show", "muck"):
            continue
        if act.player == threebettor and act.action in ("fold", "call", "raise", "bet", "check"):
            if not raise_before:
                three_faced = True
                if act.action == "fold":
                    three_fold = True
                elif act.action == "call":
                    three_call = True
                elif act.action in ("raise", "bet"):
                    three_5bet = True
            break
        if act.action in ("raise", "bet") and act.player != threebettor:
            raise_before = True

    call_combo = _combo_or_unknown(hand, threebettor) if three_call else None
    fivebet_combo = _combo_or_unknown(hand, threebettor) if three_5bet else None
    return FourBetMatrixSpot(
        four_pos=four_pos,
        three_pos=three_pos,
        three_fold=three_fold,
        three_call=three_call,
        three_5bet=three_5bet,
        three_faced=three_faced,
        call_combo=call_combo,
        fivebet_combo=fivebet_combo,
    )


@dataclass
class FourBetSpot:
    all_fold: bool
    faced_5bet: bool
    threebettor_call: bool
    threebettor_faced: bool
    call_combo: str | None
    threebettor: str
    threebettor_position: str
    fivebettor: str | None
    fivebettor_position: str | None
    fivebet_combo: str | None


@dataclass
class FiveBetSpot:
    fourbettor_fold: bool
    fourbettor_call: bool
    fourbettor_faced: bool
    call_combo: str | None
    fold_combo: str | None
    fourbettor: str
    fourbettor_position: str
    theoretical_equity: float | None
    actual_share: float | None


def _facing_response(
    hand: Hand,
    start_index: int,
    player: str,
) -> tuple[bool, bool, bool, bool]:
    """
    Player's first fold/call/raise after start_index, if no one raised first.

    Returns (faced, folded, called, raised).
    """
    street = hand.actions[start_index].street
    raise_before = False
    for act in hand.actions[start_index + 1 :]:
        if act.street != street:
            break
        if act.is_hero:
            break
        if act.action in ("show", "muck"):
            continue
        if act.player == player and act.action in ("fold", "call", "raise", "bet", "check"):
            if raise_before:
                return False, False, False, False
            if act.action == "fold":
                return True, True, False, False
            if act.action == "call":
                return True, False, True, False
            if act.action in ("raise", "bet"):
                return True, False, False, True
            return True, False, False, False
        if act.action in ("raise", "bet") and act.player != player:
            raise_before = True
    return False, False, False, False


def extract_4bet(hand: Hand, hero_pos: str, three_pos: str) -> FourBetSpot | None:
    if three_pos not in positions_except(hero_pos):
        return None
    bb = _bb_size(hand)
    if bb is None:
        return None
    pos = position_map(hand)
    if pos.get(HERO) != hero_pos:
        return None
    raises = iter_preflop_opensize_raises(hand, bb)
    if len(raises) < 3:
        return None
    _open_idx, _open_act = raises[0]
    _three_idx, three_act = raises[1]
    four_idx, four_act = raises[2]
    if not four_act.is_hero:
        return None
    if pos.get(three_act.player) != three_pos:
        return None

    all_fold, _has_call, has_raise = _response_after(hand, four_idx)
    faced, _folded, called, raised = _facing_response(hand, four_idx, three_act.player)
    call_combo = _combo_or_unknown(hand, three_act.player) if called else None
    fivebet_act = _first_raising_actor_after(hand, four_idx) if has_raise or raised else None
    return FourBetSpot(
        all_fold=all_fold,
        faced_5bet=has_raise or raised,
        threebettor_call=called,
        threebettor_faced=faced,
        call_combo=call_combo,
        threebettor=three_act.player,
        threebettor_position=three_pos,
        fivebettor=fivebet_act.player if fivebet_act else None,
        fivebettor_position=pos.get(fivebet_act.player) if fivebet_act else None,
        fivebet_combo=_combo_or_unknown(hand, fivebet_act.player) if fivebet_act else None,
    )


def extract_5bet(hand: Hand, hero_pos: str, four_pos: str) -> FiveBetSpot | None:
    if four_pos not in positions_except(hero_pos):
        return None
    bb = _bb_size(hand)
    if bb is None:
        return None
    pos = position_map(hand)
    if pos.get(HERO) != hero_pos:
        return None
    raises = iter_preflop_opensize_raises(hand, bb)
    if len(raises) < 4:
        return None
    _four_prev_idx, four_act = raises[2]
    five_idx, five_act = raises[3]
    if not five_act.is_hero:
        return None
    if pos.get(four_act.player) != four_pos:
        return None

    faced, folded, called, _raised = _facing_response(hand, five_idx, four_act.player)
    call_combo = None
    fold_combo = None
    theoretical = None
    actual = None
    if called:
        call_combo = _combo_or_unknown(hand, four_act.player)
        hero_cards = _player_cards(hand, HERO)
        vill_cards = _player_cards(hand, four_act.player)
        if hero_cards and vill_cards:
            theoretical = preflop_equity(hero_cards, vill_cards)
        actual = _hero_showdown_share(hand)
    elif folded:
        fold_combo = _combo_or_unknown(hand, four_act.player)
    return FiveBetSpot(
        fourbettor_fold=folded,
        fourbettor_call=called,
        fourbettor_faced=faced,
        call_combo=call_combo,
        fold_combo=fold_combo,
        fourbettor=four_act.player,
        fourbettor_position=four_pos,
        theoretical_equity=theoretical,
        actual_share=actual,
    )


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _pct(count: int, n: int) -> float | None:
    if n <= 0:
        return None
    return round(100.0 * count / n, 2)


def _stat(count: int, n: int) -> dict[str, Any]:
    return {"count": count, "pct": _pct(count, n)}


@register
class PreflopAnalysis9MaxMetric(Metric):
    """9-max preflop open-raise / 3bet frequencies from Hero's chosen seat."""

    id = "preflop_analysis_9max"
    name = "翻前分析 (9-max)"
    description = "9-max 按位置统计 Hero open raise / 3bet / 4bet / 5bet 后的对手反应"
    chart_type = "stats"

    def compute(self, dataset: HandDataset, options: dict[str, Any] | None = None) -> dict[str, Any]:
        opts = options or {}
        hero_pos = _as_str(opts.get("hero_position"), "BTN").upper()
        action = _as_str(opts.get("action"), "open_raise").lower()
        opener_pos = _as_str(opts.get("opener_position")).upper()
        three_pos = _as_str(opts.get("threebettor_position")).upper()
        four_pos = _as_str(opts.get("fourbettor_position")).upper()

        if action not in ACTIONS_IMPLEMENTED:
            raise ValueError(f"未知动作: {action}")

        allow_limp = _option_bool(opts.get("allow_limp"), True)
        allow_call = _option_bool(opts.get("allow_call"), True)

        if action == "3bet_matrix":
            return self._compute_3bet_matrix(dataset, allow_limp, allow_call)
        if action == "4bet_matrix":
            return self._compute_4bet_matrix(dataset, allow_limp, allow_call)

        if hero_pos not in POSITION_ORDER:
            raise ValueError(f"未知位置: {hero_pos}")

        if action == "open_raise":
            return self._compute_open(dataset, hero_pos, allow_limp, allow_call)
        if action == "3bet":
            return self._compute_3bet(dataset, hero_pos, opener_pos, allow_limp, allow_call)
        if action == "4bet":
            return self._compute_4bet(dataset, hero_pos, three_pos, allow_limp, allow_call)
        return self._compute_5bet(dataset, hero_pos, four_pos, allow_limp, allow_call)

    def _compute_3bet_matrix(
        self,
        dataset: HandDataset,
        allow_limp: bool,
        allow_call: bool,
    ) -> dict[str, Any]:
        positions = list(POSITION_ORDER)
        buckets: dict[tuple[str, str], dict[str, Any]] = {}
        for three_pos in positions:
            for opener_pos in positions:
                if POSITION_ORDER.index(three_pos) <= POSITION_ORDER.index(opener_pos):
                    continue
                buckets[(three_pos, opener_pos)] = {
                    "fold": 0,
                    "call": 0,
                    "fourbet": 0,
                    "faced": 0,
                    "call_labels": [],
                    "fourbet_labels": [],
                }

        spot_count = 0
        for hand in _iter_filtered_hands(dataset, allow_limp, allow_call):
            spot = extract_3bet_matrix_spot(hand)
            if spot is None:
                continue
            key = (spot.three_pos, spot.opener_pos)
            bucket = buckets.get(key)
            if bucket is None:
                continue
            spot_count += 1
            if not spot.opener_acted:
                continue
            bucket["faced"] += 1
            if spot.opener_fold:
                bucket["fold"] += 1
            elif spot.opener_call:
                bucket["call"] += 1
                if spot.call_combo:
                    bucket["call_labels"].append(spot.call_combo)
            elif spot.opener_4bet:
                bucket["fourbet"] += 1
                if spot.fourbet_combo:
                    bucket["fourbet_labels"].append(spot.fourbet_combo)

        cells: list[dict[str, Any]] = []
        for three_pos in positions:
            for opener_pos in positions:
                key = (three_pos, opener_pos)
                bucket = buckets.get(key)
                if bucket is None:
                    cells.append(
                        {
                            "threebettor": three_pos,
                            "opener": opener_pos,
                            "valid": False,
                        }
                    )
                    continue
                faced = bucket["faced"]
                cells.append(
                    {
                        "threebettor": three_pos,
                        "opener": opener_pos,
                        "valid": True,
                        "faced": faced,
                        "fold": _stat(bucket["fold"], faced),
                        "call": _stat(bucket["call"], faced),
                        "fourbet": _stat(bucket["fourbet"], faced),
                        "call_hands": _combo_table(bucket["call_labels"]),
                        "fourbet_hands": _combo_table(bucket["fourbet_labels"]),
                        "call_hand_count": len(bucket["call_labels"]),
                        "fourbet_hand_count": len(bucket["fourbet_labels"]),
                    }
                )

        return {
            "metric_id": self.id,
            "name": self.name,
            "action": "3bet_matrix",
            "positions": positions,
            "spot_count": spot_count,
            "cells": cells,
            "options": {
                "action": "3bet_matrix",
                "allow_limp": allow_limp,
                "allow_call": allow_call,
            },
        }

    def _compute_4bet_matrix(
        self,
        dataset: HandDataset,
        allow_limp: bool,
        allow_call: bool,
    ) -> dict[str, Any]:
        positions = list(POSITION_ORDER)
        buckets: dict[tuple[str, str], dict[str, Any]] = {}
        for four_pos in positions:
            for three_pos in positions:
                if four_pos == three_pos:
                    continue
                buckets[(four_pos, three_pos)] = {
                    "fold": 0,
                    "call": 0,
                    "fivebet": 0,
                    "faced": 0,
                    "call_labels": [],
                    "fivebet_labels": [],
                }

        spot_count = 0
        for hand in _iter_filtered_hands(dataset, allow_limp, allow_call):
            spot = extract_4bet_matrix_spot(hand)
            if spot is None:
                continue
            key = (spot.four_pos, spot.three_pos)
            bucket = buckets.get(key)
            if bucket is None:
                continue
            spot_count += 1
            if not spot.three_faced:
                continue
            bucket["faced"] += 1
            if spot.three_fold:
                bucket["fold"] += 1
            elif spot.three_call:
                bucket["call"] += 1
                if spot.call_combo:
                    bucket["call_labels"].append(spot.call_combo)
            elif spot.three_5bet:
                bucket["fivebet"] += 1
                if spot.fivebet_combo:
                    bucket["fivebet_labels"].append(spot.fivebet_combo)

        cells: list[dict[str, Any]] = []
        for four_pos in positions:
            for three_pos in positions:
                key = (four_pos, three_pos)
                bucket = buckets.get(key)
                if bucket is None:
                    cells.append(
                        {
                            "fourbettor": four_pos,
                            "threebettor": three_pos,
                            "valid": False,
                        }
                    )
                    continue
                faced = bucket["faced"]
                cells.append(
                    {
                        "fourbettor": four_pos,
                        "threebettor": three_pos,
                        "valid": True,
                        "faced": faced,
                        "fold": _stat(bucket["fold"], faced),
                        "call": _stat(bucket["call"], faced),
                        "fivebet": _stat(bucket["fivebet"], faced),
                        "call_hands": _combo_table(bucket["call_labels"]),
                        "fivebet_hands": _combo_table(bucket["fivebet_labels"]),
                        "call_hand_count": len(bucket["call_labels"]),
                        "fivebet_hand_count": len(bucket["fivebet_labels"]),
                    }
                )

        return {
            "metric_id": self.id,
            "name": self.name,
            "action": "4bet_matrix",
            "positions": positions,
            "spot_count": spot_count,
            "cells": cells,
            "options": {
                "action": "4bet_matrix",
                "allow_limp": allow_limp,
                "allow_call": allow_call,
            },
        }

    def _compute_open(
        self,
        dataset: HandDataset,
        hero_pos: str,
        allow_limp: bool,
        allow_call: bool,
    ) -> dict[str, Any]:
        spots: list[OpenRaiseSpot] = []
        for hand in _iter_filtered_hands(dataset, allow_limp, allow_call):
            spot = extract_open_raise(hand, hero_pos)
            if spot is not None:
                spots.append(spot)
        n = len(spots)
        all_fold_n = sum(1 for s in spots if s.all_fold)
        threebet_n = sum(1 for s in spots if s.faced_3bet)
        threebet_hands = [s.threebet_combo for s in spots if s.faced_3bet and s.threebet_combo]
        return {
            "metric_id": self.id,
            "name": self.name,
            "action": "open_raise",
            "hero_position": hero_pos,
            "spot_count": n,
            "all_fold": _stat(all_fold_n, n),
            "faced_3bet": _stat(threebet_n, n),
            "hand_details": _build_hand_details({"faced_3bet": threebet_hands}),
            "options": {
                "hero_position": hero_pos,
                "action": "open_raise",
                "positions_in_front": positions_in_front(hero_pos),
                "allow_limp": allow_limp,
                "allow_call": allow_call,
            },
        }

    def _compute_3bet(
        self,
        dataset: HandDataset,
        hero_pos: str,
        opener_pos: str,
        allow_limp: bool,
        allow_call: bool,
    ) -> dict[str, Any]:
        allowed = positions_in_front(hero_pos)
        if not opener_pos:
            opener_pos = allowed[0] if allowed else ""
        if opener_pos and opener_pos not in allowed:
            raise ValueError(f"Open raise 位置 {opener_pos} 不在 {hero_pos} 前面")

        spots: list[ThreeBetSpot] = []
        if opener_pos:
            for hand in _iter_filtered_hands(dataset, allow_limp, allow_call):
                spot = extract_3bet(hand, hero_pos, opener_pos)
                if spot is not None:
                    spots.append(spot)

        n = len(spots)
        opener_n = sum(1 for s in spots if s.opener_acted)
        hand_details = _build_hand_details(
            {
                "opener_fold": [s.opener_combo for s in spots if s.opener_fold and s.opener_combo],
                "opener_call": [s.opener_combo for s in spots if s.opener_call and s.opener_combo],
                "opener_4bet": [s.opener_combo for s in spots if s.opener_4bet and s.opener_combo],
                "cold_4bet": [
                    s.cold_4bet_combo for s in spots if s.cold_4bet and s.cold_4bet_combo
                ],
            }
        )
        return {
            "metric_id": self.id,
            "name": self.name,
            "action": "3bet",
            "hero_position": hero_pos,
            "opener_position": opener_pos or None,
            "spot_count": n,
            "opener_responded": opener_n,
            "opener_fold": _stat(sum(1 for s in spots if s.opener_fold), opener_n),
            "opener_call": _stat(sum(1 for s in spots if s.opener_call), opener_n),
            "opener_4bet": _stat(sum(1 for s in spots if s.opener_4bet), opener_n),
            "all_fold": _stat(sum(1 for s in spots if s.all_fold), n),
            "cold_4bet": _stat(sum(1 for s in spots if s.cold_4bet), n),
            "hand_details": hand_details,
            "options": {
                "hero_position": hero_pos,
                "action": "3bet",
                "opener_position": opener_pos or None,
                "positions_in_front": allowed,
                "allow_limp": allow_limp,
                "allow_call": allow_call,
            },
        }

    def _compute_4bet(
        self,
        dataset: HandDataset,
        hero_pos: str,
        three_pos: str,
        allow_limp: bool,
        allow_call: bool,
    ) -> dict[str, Any]:
        allowed = positions_except(hero_pos)
        if not three_pos:
            three_pos = "BB" if "BB" in allowed else (allowed[-1] if allowed else "")
        if three_pos and three_pos not in allowed:
            raise ValueError(f"3bet 位置 {three_pos} 不能与 Hero {hero_pos} 相同")

        spots: list[FourBetSpot] = []
        if three_pos:
            for hand in _iter_filtered_hands(dataset, allow_limp, allow_call):
                spot = extract_4bet(hand, hero_pos, three_pos)
                if spot is not None:
                    spots.append(spot)

        n = len(spots)
        faced_n = sum(1 for s in spots if s.threebettor_faced)
        call_hands = [s.call_combo for s in spots if s.threebettor_call and s.call_combo]
        fivebet_hands = [s.fivebet_combo for s in spots if s.faced_5bet and s.fivebet_combo]
        return {
            "metric_id": self.id,
            "name": self.name,
            "action": "4bet",
            "hero_position": hero_pos,
            "threebettor_position": three_pos or None,
            "spot_count": n,
            "threebettor_faced": faced_n,
            "all_fold": _stat(sum(1 for s in spots if s.all_fold), n),
            "faced_5bet": _stat(sum(1 for s in spots if s.faced_5bet), n),
            "threebettor_call": _stat(sum(1 for s in spots if s.threebettor_call), faced_n),
            "call_hands": _combo_table(call_hands),
            "call_hand_count": len(call_hands),
            "hand_details": _build_hand_details(
                {
                    "faced_5bet": fivebet_hands,
                    "threebettor_call": call_hands,
                }
            ),
            "options": {
                "hero_position": hero_pos,
                "action": "4bet",
                "threebettor_position": three_pos or None,
                "villain_positions": allowed,
                "allow_limp": allow_limp,
                "allow_call": allow_call,
            },
        }

    def _compute_5bet(
        self,
        dataset: HandDataset,
        hero_pos: str,
        four_pos: str,
        allow_limp: bool,
        allow_call: bool,
    ) -> dict[str, Any]:
        allowed = positions_except(hero_pos)
        if not four_pos:
            four_pos = "BB" if "BB" in allowed else (allowed[-1] if allowed else "")
        if four_pos and four_pos not in allowed:
            raise ValueError(f"4bet 位置 {four_pos} 不能与 Hero {hero_pos} 相同")

        spots: list[FiveBetSpot] = []
        if four_pos:
            for hand in _iter_filtered_hands(dataset, allow_limp, allow_call):
                spot = extract_5bet(hand, hero_pos, four_pos)
                if spot is not None:
                    spots.append(spot)

        n = len(spots)
        faced_n = sum(1 for s in spots if s.fourbettor_faced)
        call_hands = [s.call_combo for s in spots if s.fourbettor_call and s.call_combo]
        fold_hands = [s.fold_combo for s in spots if s.fourbettor_fold and s.fold_combo]
        theor = [s.theoretical_equity for s in spots if s.theoretical_equity is not None]
        actual = [s.actual_share for s in spots if s.actual_share is not None]
        return {
            "metric_id": self.id,
            "name": self.name,
            "action": "5bet",
            "hero_position": hero_pos,
            "fourbettor_position": four_pos or None,
            "spot_count": n,
            "fourbettor_faced": faced_n,
            "fourbettor_fold": _stat(sum(1 for s in spots if s.fourbettor_fold), faced_n),
            "fourbettor_call": _stat(sum(1 for s in spots if s.fourbettor_call), faced_n),
            "theoretical_equity": {
                "pct": round(100.0 * (sum(theor) / len(theor)), 2) if theor else None,
                "count": len(theor),
            },
            "actual_winrate": {
                "pct": round(100.0 * (sum(actual) / len(actual)), 2) if actual else None,
                "count": len(actual),
            },
            "call_hands": _combo_table(call_hands),
            "call_hand_count": len(call_hands),
            "hand_details": _build_hand_details(
                {
                    "fourbettor_fold": fold_hands,
                    "fourbettor_call": call_hands,
                }
            ),
            "options": {
                "hero_position": hero_pos,
                "action": "5bet",
                "fourbettor_position": four_pos or None,
                "villain_positions": allowed,
                "allow_limp": allow_limp,
                "allow_call": allow_call,
            },
        }
