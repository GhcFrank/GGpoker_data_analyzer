from __future__ import annotations

from typing import Any, Callable

from poker.metrics.preflop_analysis import (
    ACTIONS_IMPLEMENTED as ACTIONS_6,
    POSITION_ORDER as POSITION_ORDER_6,
    extract_3bet as extract_3bet_6,
    extract_4bet as extract_4bet_6,
    extract_5bet as extract_5bet_6,
    extract_open_raise as extract_open_raise_6,
    hand_allowed,
    positions_except as positions_except_6,
    positions_in_front as positions_in_front_6,
)
from poker.metrics.preflop_analysis_9max import (
    ACTIONS_IMPLEMENTED as ACTIONS_9,
    POSITION_ORDER as POSITION_ORDER_9,
    extract_3bet as extract_3bet_9,
    extract_4bet as extract_4bet_9,
    extract_5bet as extract_5bet_9,
    extract_open_raise as extract_open_raise_9,
    positions_except as positions_except_9,
    positions_in_front as positions_in_front_9,
)
from poker.metrics.preflop_events import spot_matches_event
from poker.metrics.when_i_raise import hand_matches_raise_options
from poker.models import Hand

SOURCES = ("preflop_analysis", "preflop_analysis_9max", "when_i_raise")

_PREFLOP_SOURCES = {
    "preflop_analysis": {
        "order": POSITION_ORDER_6,
        "actions": ACTIONS_6,
        "positions_in_front": positions_in_front_6,
        "positions_except": positions_except_6,
        "extract_open_raise": extract_open_raise_6,
        "extract_3bet": extract_3bet_6,
        "extract_4bet": extract_4bet_6,
        "extract_5bet": extract_5bet_6,
    },
    "preflop_analysis_9max": {
        "order": POSITION_ORDER_9,
        "actions": ACTIONS_9,
        "positions_in_front": positions_in_front_9,
        "positions_except": positions_except_9,
        "extract_open_raise": extract_open_raise_9,
        "extract_3bet": extract_3bet_9,
        "extract_4bet": extract_4bet_9,
        "extract_5bet": extract_5bet_9,
    },
}


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


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


def _preflop_matches(hand: Hand, options: dict[str, Any], ctx: dict[str, Any]) -> bool:
    order = ctx["order"]
    hero_pos = _as_str(options.get("hero_position"), "BTN").upper()
    action = _as_str(options.get("action"), "open_raise").lower()
    if hero_pos not in order or action not in ctx["actions"]:
        return False
    if not hand_allowed(
        hand,
        _option_bool(options.get("allow_limp"), True),
        _option_bool(options.get("allow_call"), True),
    ):
        return False
    spot = None
    if action == "open_raise":
        spot = ctx["extract_open_raise"](hand, hero_pos)
    elif action == "3bet":
        allowed = ctx["positions_in_front"](hero_pos)
        opener = _as_str(options.get("opener_position")).upper() or (allowed[0] if allowed else "")
        if opener:
            spot = ctx["extract_3bet"](hand, hero_pos, opener)
    elif action == "4bet":
        allowed = ctx["positions_except"](hero_pos)
        three = _as_str(options.get("threebettor_position")).upper()
        if not three:
            three = "BB" if "BB" in allowed else (allowed[-1] if allowed else "")
        if three:
            spot = ctx["extract_4bet"](hand, hero_pos, three)
    elif action == "5bet":
        allowed = ctx["positions_except"](hero_pos)
        four = _as_str(options.get("fourbettor_position")).upper()
        if not four:
            four = "BB" if "BB" in allowed else (allowed[-1] if allowed else "")
        if four:
            spot = ctx["extract_5bet"](hand, hero_pos, four)
    if spot is None:
        return False
    return spot_matches_event(action, spot, _as_str(options.get("selected_event")))


def matcher_for(source: str, options: dict[str, Any] | None) -> Callable[[Hand], bool]:
    opts = options or {}
    if source in _PREFLOP_SOURCES:
        ctx = _PREFLOP_SOURCES[source]
        return lambda hand: _preflop_matches(hand, opts, ctx)
    if source == "when_i_raise":
        return lambda hand: hand_matches_raise_options(hand, opts)
    raise ValueError(f"未知回放来源: {source}")
