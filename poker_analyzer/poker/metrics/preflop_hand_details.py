from __future__ import annotations

from typing import Any, Iterable, Mapping

from poker.equity import UNKNOWN_COMBO, hole_combo_label
from poker.models import Action, Hand


def player_cards(hand: Hand, name: str) -> tuple[str, ...] | None:
    """Return a player's normalized two-card holding when it is available."""
    cards = hand.shown_cards.get(name)
    if cards and len(cards) >= 2:
        return cards[:2]
    if name == "Hero" and hand.hero_cards:
        tokens = tuple(part for part in hand.hero_cards.split() if part)
        if len(tokens) >= 2:
            return tokens[:2]
    return None


def combo_or_unknown(hand: Hand, name: str) -> str:
    cards = player_cards(hand, name)
    if cards is None:
        return UNKNOWN_COMBO
    return hole_combo_label(cards)


def first_raising_actor_after(hand: Hand, start_index: int) -> Action | None:
    """First opponent raise before action returns to Hero on the same street."""
    street = hand.actions[start_index].street
    for action in hand.actions[start_index + 1 :]:
        if action.street != street or action.is_hero:
            break
        if action.action in ("raise", "bet"):
            return action
    return None


def combo_table(labels: Iterable[str]) -> list[dict[str, Any]]:
    values = list(labels)
    total = len(values)
    counts: dict[str, int] = {}
    for label in values:
        counts[label] = counts.get(label, 0) + 1

    def sort_key(item: tuple[str, int]) -> tuple[int, int, str]:
        label, count = item
        if label == UNKNOWN_COMBO:
            return (1, 0, label)
        return (0, -count, label)

    return [
        {
            "hand": label,
            "count": count,
            "pct": round(100.0 * count / total, 2) if total else None,
        }
        for label, count in sorted(counts.items(), key=sort_key)
    ]


def build_hand_details(labels_by_stat: Mapping[str, Iterable[str]]) -> dict[str, dict[str, Any]]:
    """Format actor-bound event labels for the common API/UI detail contract."""
    details: dict[str, dict[str, Any]] = {}
    for stat_key, labels in labels_by_stat.items():
        values = list(labels)
        details[stat_key] = {
            "count": len(values),
            "hands": combo_table(values),
        }
    return details
