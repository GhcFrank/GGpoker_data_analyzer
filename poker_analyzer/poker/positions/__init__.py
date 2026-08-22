from __future__ import annotations

from poker.positions._base import PositionProfile
from poker.positions.nine_max import NINE_MAX_PROFILE, POSITION_ORDER as POSITION_ORDER_9MAX
from poker.positions.six_max import SIX_MAX_PROFILE, POSITION_ORDER as POSITION_ORDER_6MAX

_PROFILES = {
    "6max": SIX_MAX_PROFILE,
    "9max": NINE_MAX_PROFILE,
}


def get_profile(table_format: str) -> PositionProfile:
    key = str(table_format).strip().lower()
    try:
        return _PROFILES[key]
    except KeyError as exc:
        raise ValueError(f"未知桌型: {table_format}") from exc


__all__ = [
    "PositionProfile",
    "SIX_MAX_PROFILE",
    "NINE_MAX_PROFILE",
    "POSITION_ORDER_6MAX",
    "POSITION_ORDER_9MAX",
    "get_profile",
]
