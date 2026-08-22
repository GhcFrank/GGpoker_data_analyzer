from __future__ import annotations

from poker.models import Hand
from poker.positions._base import PositionProfile, build_position_map, seat_order_clockwise

POSITION_ORDER = ("UTG", "HJ", "CO", "BTN", "SB", "BB")

_LAYOUT = frozenset(POSITION_ORDER)


def _mid_labels(count: int) -> list[str]:
    if count <= 0:
        return []
    if count == 1:
        return ["CO"]
    if count == 2:
        return ["UTG", "CO"]
    if count == 3:
        return ["UTG", "HJ", "CO"]
    extras = count - 3
    return ["UTG"] + [f"UTG+{i}" for i in range(1, extras + 1)] + ["HJ", "CO"]


def position_map(hand: Hand) -> dict[str, str]:
    if hand.button_seat is None or not hand.seat_names:
        return {}
    clockwise = seat_order_clockwise(hand.seat_names.keys(), hand.button_seat)
    mid_count = max(0, len(clockwise) - 3) if len(clockwise) > 2 else 0
    return build_position_map(hand, _mid_labels(mid_count))


def _layout_key(position: str) -> str:
    if position in _LAYOUT:
        return position
    if position.startswith("UTG"):
        return "UTG"
    return ""


SIX_MAX_PROFILE = PositionProfile(
    table_format="6max",
    order=POSITION_ORDER,
    position_map=position_map,
    layout_key=_layout_key,
)
