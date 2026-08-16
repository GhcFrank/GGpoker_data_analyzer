from __future__ import annotations

from functools import lru_cache
from itertools import combinations
from random import Random
from typing import Iterable, Sequence

RANK_ORDER = "23456789TJQKA"
SUIT_ORDER = "cdhs"
UNKNOWN_COMBO = "未知"

# 5-high wheel uses rank index of 5 (3).
_STRAIGHT_HIGHS = tuple(range(12, 3, -1))
_WHEEL_MASK = (1 << 12) | 0b1111  # A,2,3,4,5


def parse_card(card: str) -> tuple[str, str]:
    text = card.strip()
    if len(text) < 2:
        raise ValueError(f"invalid card: {card!r}")
    rank = text[0].upper()
    if rank == "1" and len(text) >= 3 and text[1].upper() == "0":
        rank = "T"
        suit = text[-1].lower()
    else:
        suit = text[-1].lower()
    if rank == "10":
        rank = "T"
    if rank not in RANK_ORDER or suit not in SUIT_ORDER:
        raise ValueError(f"invalid card: {card!r}")
    return rank, suit


def card_to_int(card: str) -> int:
    rank, suit = parse_card(card)
    return RANK_ORDER.index(rank) * 4 + SUIT_ORDER.index(suit)


def parse_hole_cards(raw: str | Sequence[str] | None) -> tuple[int, int] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        tokens = [p for p in raw.replace(",", " ").split() if p]
    else:
        tokens = [str(p) for p in raw]
    if len(tokens) < 2:
        return None
    try:
        a, b = card_to_int(tokens[0]), card_to_int(tokens[1])
    except ValueError:
        return None
    if a == b:
        return None
    return (a, b)


def hole_combo_label(raw: str | Sequence[str] | None) -> str:
    """AKs / AKo / AA. Suited and offsuit are distinct."""
    parsed = parse_hole_cards(raw)
    if parsed is None:
        return UNKNOWN_COMBO
    r1, r2 = parsed[0] // 4, parsed[1] // 4
    s1, s2 = parsed[0] % 4, parsed[1] % 4
    if r1 < r2:
        r1, r2, s1, s2 = r2, r1, s2, s1
    hi, lo = RANK_ORDER[r1], RANK_ORDER[r2]
    if r1 == r2:
        return f"{hi}{lo}"
    return f"{hi}{lo}{'s' if s1 == s2 else 'o'}"


def _best_straight(mask: int) -> int:
    """Highest rank index of a 5-card straight, or -1."""
    for high in _STRAIGHT_HIGHS:
        window = 0b11111 << (high - 4)
        if mask & window == window:
            return high
    if mask & _WHEEL_MASK == _WHEEL_MASK:
        return 3
    return -1


def _top_ranks(mask: int, n: int) -> list[int]:
    ranks: list[int] = []
    bit = 12
    while bit >= 0 and len(ranks) < n:
        if mask & (1 << bit):
            ranks.append(bit)
        bit -= 1
    return ranks


def evaluate7(cards: Sequence[int]) -> int:
    """
    Comparable 7-card strength. Higher is better.

    Layout: category in the high bits, then kickers.
    8 SF, 7 quads, 6 boat, 5 flush, 4 straight, 3 trips, 2 two-pair, 1 pair, 0 high.
    """
    rank_mask = 0
    suit_masks = [0, 0, 0, 0]
    counts = [0] * 13
    for c in cards:
        rank = c >> 2
        suit = c & 3
        counts[rank] += 1
        rank_mask |= 1 << rank
        suit_masks[suit] |= 1 << rank

    flush_mask = 0
    for sm in suit_masks:
        if sm.bit_count() >= 5:
            flush_mask = sm
            break

    quads = trips = 0
    pairs: list[int] = []
    for rank in range(12, -1, -1):
        n = counts[rank]
        if n == 4:
            quads = rank
        elif n == 3 and trips == 0:
            trips = rank
        elif n == 3:
            pairs.append(rank)
        elif n == 2:
            pairs.append(rank)

    if flush_mask:
        sf = _best_straight(flush_mask)
        if sf >= 0:
            return (8 << 20) | sf

    if quads:
        kicker = next(r for r in range(12, -1, -1) if r != quads and counts[r])
        return (7 << 20) | (quads << 8) | kicker
    if trips and pairs:
        return (6 << 20) | (trips << 8) | pairs[0]
    lower_trips = next((r for r in range(12, -1, -1) if r != trips and counts[r] == 3), -1) if trips else -1
    if trips and lower_trips >= 0:
        return (6 << 20) | (trips << 8) | lower_trips

    if flush_mask:
        kick = _top_ranks(flush_mask, 5)
        value = 5 << 20
        shift = 16
        for k in kick:
            value |= k << shift
            shift -= 4
        return value

    straight = _best_straight(rank_mask)
    if straight >= 0:
        return (4 << 20) | straight
    def _pad(ranks: list[int], n: int) -> list[int]:
        return (ranks + [0] * n)[:n]

    if trips:
        kick = _pad([r for r in range(12, -1, -1) if r != trips and counts[r]], 2)
        return (3 << 20) | (trips << 8) | (kick[0] << 4) | kick[1]
    if len(pairs) >= 2:
        used = {pairs[0], pairs[1]}
        kicker = next((r for r in range(12, -1, -1) if r not in used and counts[r]), 0)
        return (2 << 20) | (pairs[0] << 8) | (pairs[1] << 4) | kicker
    if pairs:
        kick = _pad([r for r in range(12, -1, -1) if r != pairs[0] and counts[r]], 3)
        return (1 << 20) | (pairs[0] << 12) | (kick[0] << 8) | (kick[1] << 4) | kick[2]
    kick = _top_ranks(rank_mask, 5)
    value = 0
    shift = 16
    for k in kick:
        value |= k << shift
        shift -= 4
    return value


def _matchup_key(hero: tuple[int, int], villain: tuple[int, int]) -> tuple[int, ...]:
    h = tuple(sorted(hero))
    v = tuple(sorted(villain))
    if h <= v:
        return h + v
    return v + h


def _same_category_tie(hero: tuple[int, int], villain: tuple[int, int]) -> bool:
    """Identical rank pattern and suitedness → 50% by symmetry (AA vs AA, AKs vs AKs)."""
    hr = sorted((hero[0] >> 2, hero[1] >> 2))
    vr = sorted((villain[0] >> 2, villain[1] >> 2))
    if hr != vr:
        return False
    hs = (hero[0] & 3) == (hero[1] & 3)
    vs = (villain[0] & 3) == (villain[1] & 3)
    return hs == vs


def _enumerate_equity(a: int, b: int, c: int, d: int) -> float:
    used = {a, b, c, d}
    deck = [i for i in range(52) if i not in used]
    wins = ties = 0
    total = 0
    h7 = [a, b, 0, 0, 0, 0, 0]
    v7 = [c, d, 0, 0, 0, 0, 0]
    for board in combinations(deck, 5):
        h7[2], h7[3], h7[4], h7[5], h7[6] = board
        v7[2], v7[3], v7[4], v7[5], v7[6] = board
        eh = evaluate7(h7)
        ev = evaluate7(v7)
        if eh > ev:
            wins += 1
        elif eh == ev:
            ties += 1
        total += 1
    return (wins + 0.5 * ties) / total if total else 0.5


def _sample_equity(a: int, b: int, c: int, d: int, samples: int = 40000) -> float:
    used = {a, b, c, d}
    deck = [i for i in range(52) if i not in used]
    rng = Random((a, b, c, d, samples))
    wins = ties = 0
    h7 = [a, b, 0, 0, 0, 0, 0]
    v7 = [c, d, 0, 0, 0, 0, 0]
    n = len(deck)
    for _ in range(samples):
        # Partial Fisher–Yates for 5 board cards.
        for i in range(5):
            j = rng.randrange(i, n)
            deck[i], deck[j] = deck[j], deck[i]
        board = deck[0], deck[1], deck[2], deck[3], deck[4]
        h7[2], h7[3], h7[4], h7[5], h7[6] = board
        v7[2], v7[3], v7[4], v7[5], v7[6] = board
        eh = evaluate7(h7)
        ev = evaluate7(v7)
        if eh > ev:
            wins += 1
        elif eh == ev:
            ties += 1
    return (wins + 0.5 * ties) / samples


@lru_cache(maxsize=4096)
def _equity_cached(a: int, b: int, c: int, d: int, swapped: bool) -> float:
    hero = (a, b)
    villain = (c, d)
    if _same_category_tie(hero, villain):
        return 0.5
    equity = _sample_equity(a, b, c, d)
    return 1.0 - equity if swapped else equity


def preflop_equity(hero_cards: Iterable[str] | str, villain_cards: Iterable[str] | str) -> float | None:
    """Hero equity vs villain on a random full runout (ties count as half)."""
    hero = parse_hole_cards(hero_cards if isinstance(hero_cards, str) else tuple(hero_cards))
    villain = parse_hole_cards(villain_cards if isinstance(villain_cards, str) else tuple(villain_cards))
    if hero is None or villain is None:
        return None
    if set(hero) & set(villain):
        return None
    key = _matchup_key(hero, villain)
    swapped = tuple(sorted(hero)) != key[:2]
    return _equity_cached(key[0], key[1], key[2], key[3], swapped)
