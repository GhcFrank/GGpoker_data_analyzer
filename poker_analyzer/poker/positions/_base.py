from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from poker.models import Hand


def seat_order_clockwise(seats: list[int] | set[int], start_seat: int) -> list[int]:
    ordered = sorted(seats)
    if not ordered:
        return []
    after = [s for s in ordered if s > start_seat]
    before = [s for s in ordered if s <= start_seat]
    return after + before


def build_position_map(hand: Hand, mid_labels: list[str]) -> dict[str, str]:
    """Map player name → position label for occupied seats."""
    if hand.button_seat is None or not hand.seat_names:
        return {}
    clockwise = seat_order_clockwise(hand.seat_names.keys(), hand.button_seat)
    n = len(clockwise)
    if n < 2:
        return {}
    names = hand.seat_names
    result: dict[str, str] = {}
    if n == 2:
        result[names[clockwise[0]]] = "SB"
        result[names[clockwise[1]]] = "BB"
        return result
    result[names[clockwise[0]]] = "SB"
    result[names[clockwise[1]]] = "BB"
    result[names[clockwise[-1]]] = "BTN"
    mid_seats = clockwise[2:-1]
    for seat, label in zip(mid_seats, mid_labels):
        result[names[seat]] = label
    return result


@dataclass(frozen=True)
class PositionProfile:
    table_format: str
    order: tuple[str, ...]
    position_map: Callable[[Hand], dict[str, str]]
    layout_key: Callable[[str], str]

    def positions_in_front(self, hero_pos: str) -> list[str]:
        if hero_pos not in self.order:
            return []
        return list(self.order[: self.order.index(hero_pos)])

    def positions_except(self, hero_pos: str) -> list[str]:
        return [p for p in self.order if p != hero_pos]
