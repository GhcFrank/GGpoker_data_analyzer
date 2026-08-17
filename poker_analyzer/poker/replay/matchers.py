from __future__ import annotations

from typing import Any, Callable

from poker.metrics.preflop_analysis import (
    ACTIONS_IMPLEMENTED,
    POSITION_ORDER,
    extract_3bet,
    extract_4bet,
    extract_5bet,
    extract_open_raise,
    hand_allowed,
    positions_except,
    positions_in_front,
)
from poker.metrics.when_i_raise import hand_matches_raise_options
from poker.models import Hand

SOURCES = ("preflop_analysis", "when_i_raise")


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


def _preflop_matches(hand: Hand, options: dict[str, Any]) -> bool:
    hero_pos = _as_str(options.get("hero_position"), "BTN").upper()
    action = _as_str(options.get("action"), "open_raise").lower()
    if hero_pos not in POSITION_ORDER or action not in ACTIONS_IMPLEMENTED:
        return False
    if not hand_allowed(
        hand,
        _option_bool(options.get("allow_limp"), True),
        _option_bool(options.get("allow_call"), True),
    ):
        return False
    if action == "open_raise":
        return extract_open_raise(hand, hero_pos) is not None
    if action == "3bet":
        allowed = positions_in_front(hero_pos)
        opener = _as_str(options.get("opener_position")).upper() or (allowed[0] if allowed else "")
        return bool(opener) and extract_3bet(hand, hero_pos, opener) is not None
    if action == "4bet":
        allowed = positions_except(hero_pos)
        three = _as_str(options.get("threebettor_position")).upper()
        if not three:
            three = "BB" if "BB" in allowed else (allowed[-1] if allowed else "")
        return bool(three) and extract_4bet(hand, hero_pos, three) is not None
    allowed = positions_except(hero_pos)
    four = _as_str(options.get("fourbettor_position")).upper()
    if not four:
        four = "BB" if "BB" in allowed else (allowed[-1] if allowed else "")
    return bool(four) and extract_5bet(hand, hero_pos, four) is not None


def matcher_for(source: str, options: dict[str, Any] | None) -> Callable[[Hand], bool]:
    opts = options or {}
    if source == "preflop_analysis":
        return lambda hand: _preflop_matches(hand, opts)
    if source == "when_i_raise":
        return lambda hand: hand_matches_raise_options(hand, opts)
    raise ValueError(f"未知回放来源: {source}")
