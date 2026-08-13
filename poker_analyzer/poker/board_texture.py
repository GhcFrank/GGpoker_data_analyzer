from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

RANK_ORDER = "23456789TJQKA"
HIGH_RANKS = frozenset("AKQJ")

# Straight rank windows (indices into RANK_ORDER; -1 = wheel ace low).
_STRAIGHT_WINDOWS: tuple[frozenset[int], ...] = tuple(
    frozenset(range(start, start + 5)) for start in range(len(RANK_ORDER) - 4)
) + (frozenset({-1, 0, 1, 2, 3}),)


def parse_card(card: str) -> tuple[str, str]:
    """Return (rank, suit) from a card token like 'Ad' or 'Ts'."""
    text = card.strip()
    if len(text) < 2:
        raise ValueError(f"invalid card: {card!r}")
    rank = text[0].upper()
    suit = text[-1].lower()
    return rank, suit


def _rank_variants(rank: str) -> list[int]:
    if rank == "A":
        return [len(RANK_ORDER) - 1, -1]
    return [RANK_ORDER.index(rank)]


def _value_combos(cards: Iterable[str]) -> list[tuple[int, ...]]:
    combos: list[tuple[int, ...]] = [()]
    for card in cards:
        rank, _ = parse_card(card)
        next_combos: list[tuple[int, ...]] = []
        for prefix in combos:
            for value in _rank_variants(rank):
                next_combos.append(prefix + (value,))
        combos = next_combos
    return combos


def flop_high_card(cards: Iterable[str]) -> bool:
    """At least one flop card is A, K, Q, or J."""
    return any(parse_card(c)[0] in HIGH_RANKS for c in cards)


def flop_low_card(cards: Iterable[str]) -> bool:
    """No flop card is A, K, Q, or J."""
    return not flop_high_card(cards)


def flop_has_ace(cards: Iterable[str]) -> bool:
    """Flop contains at least one ace."""
    return any(parse_card(c)[0] == "A" for c in cards)


def flop_paired(cards: Iterable[str]) -> bool:
    """Flop has a paired board (two or more cards share rank)."""
    ranks = [parse_card(c)[0] for c in cards]
    return len(ranks) != len(set(ranks))


def flop_monotone(cards: Iterable[str]) -> bool:
    """All three flop cards share the same suit."""
    card_list = list(cards)
    if len(card_list) != 3:
        return False
    suits = {parse_card(c)[1] for c in card_list}
    return len(suits) == 1


def flop_flush_draw(cards: Iterable[str]) -> bool:
    """Two or more flop cards share a suit (flush draw possible)."""
    suits = [parse_card(c)[1] for c in cards]
    return max(suits.count(s) for s in set(suits)) >= 2


def flop_can_make_straight(cards: Iterable[str]) -> bool:
    """Three flop cards can belong to the same 5-card straight."""
    card_list = list(cards)
    if len(card_list) != 3:
        return False
    for combo in _value_combos(card_list):
        values = set(combo)
        for window in _STRAIGHT_WINDOWS:
            if len(values & window) >= 3:
                return True
    return False


def flop_can_draw_straight(cards: Iterable[str]) -> bool:
    """At least two flop cards fit a straight window within a 4-rank span."""
    card_list = list(cards)
    if len(card_list) != 3:
        return False
    for combo in _value_combos(card_list):
        values = sorted(set(combo))
        for window in _STRAIGHT_WINDOWS:
            in_window = sorted(v for v in values if v in window)
            if len(in_window) >= 2 and in_window[-1] - in_window[0] <= 3:
                return True
    return False


@dataclass(frozen=True)
class FlopTexture:
    high_card: bool
    low_card: bool
    has_ace: bool
    straight_made: bool
    straight_draw: bool
    flush_draw: bool
    monotone: bool
    paired: bool


# Filterable axes for When I Raise (high/low merged into high_card yes/no).
FLOP_FILTER_KEYS: tuple[str, ...] = (
    "high_card",
    "has_ace",
    "straight_made",
    "straight_draw",
    "flush_draw",
    "monotone",
    "paired",
)
FLOP_TEXTURE_KEYS = FLOP_FILTER_KEYS  # alias


def classify_flop(cards: Iterable[str]) -> FlopTexture:
    """Classify a 3-card flop against all texture flags."""
    card_list = tuple(cards)
    return FlopTexture(
        high_card=flop_high_card(card_list),
        low_card=flop_low_card(card_list),
        has_ace=flop_has_ace(card_list),
        straight_made=flop_can_make_straight(card_list),
        straight_draw=flop_can_draw_straight(card_list),
        flush_draw=flop_flush_draw(card_list),
        monotone=flop_monotone(card_list),
        paired=flop_paired(card_list),
    )


def flop_texture_matches(cards: Iterable[str], constraints: dict[str, bool]) -> bool:
    """
    Return True when every enabled constraint matches the flop.

    constraints maps filter key → desired bool (True=是, False=否).
    Empty dict means no texture restriction.
    """
    if not constraints:
        return True
    texture = classify_flop(cards)
    for key, want in constraints.items():
        if key not in FLOP_FILTER_KEYS:
            continue
        if bool(getattr(texture, key)) != bool(want):
            return False
    return True
