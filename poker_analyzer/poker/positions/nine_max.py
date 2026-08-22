from __future__ import annotations

from poker.models import Hand
from poker.positions._base import PositionProfile, build_position_map

POSITION_ORDER = ("UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO", "BTN", "SB", "BB")

_MID_LABELS_FULL = ("UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO")

_LAYOUT_MAP = {
    "UTG": "UTG",
    "UTG+1": "UTG1",
    "UTG+2": "UTG2",
    "LJ": "LJ",
    "HJ": "HJ",
    "CO": "CO",
    "BTN": "BTN",
    "SB": "SB",
    "BB": "BB",
}


def _mid_labels(count: int) -> list[str]:
    if count <= 0:
        return []
    if count >= len(_MID_LABELS_FULL):
        return list(_MID_LABELS_FULL[:count])
    return list(_MID_LABELS_FULL[-count:])


def position_map(hand: Hand) -> dict[str, str]:
    n = len(hand.seat_names)
    mid_count = max(0, n - 3) if n >= 2 else 0
    return build_position_map(hand, _mid_labels(mid_count))


def _layout_key(position: str) -> str:
    return _LAYOUT_MAP.get(position, "")


NINE_MAX_PROFILE = PositionProfile(
    table_format="9max",
    order=POSITION_ORDER,
    position_map=position_map,
    layout_key=_layout_key,
)
