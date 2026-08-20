from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Iterable

from poker.models import Hand, HandDataset

# Preset stake levels shown in the UI (SB/BB). Current data is 0.05/0.1;
# others are reserved for future HH files.
PRESET_STAKES: tuple[str, ...] = (
    "0.02/0.05",
    "0.05/0.1",
    "0.1/0.25",
    "0.2/0.5",
    "0.5/1",
)

# Game types: regular cash (NLH*) vs Rush & Cash speed tables.
GAME_TYPE_NLH = "nlh"
GAME_TYPE_RUSH = "rush"
PRESET_GAME_TYPES: tuple[tuple[str, str], ...] = (
    (GAME_TYPE_NLH, "普通桌"),
    (GAME_TYPE_RUSH, "极速桌"),
)
_VALID_GAME_TYPES = {GAME_TYPE_NLH, GAME_TYPE_RUSH}

_STAKES_RE = re.compile(
    r"\$?(?P<sb>\d+(?:\.\d+)?)\s*/\s*\$?(?P<bb>\d+(?:\.\d+)?)",
)


def normalize_stakes(raw: str) -> str | None:
    """Normalize '$0.05/$0.1' or '0.05/0.1' → '0.05/0.1'."""
    if not raw:
        return None
    m = _STAKES_RE.search(raw.replace(" ", ""))
    if not m:
        return None
    sb = _fmt_level(float(m.group("sb")))
    bb = _fmt_level(float(m.group("bb")))
    return f"{sb}/{bb}"


def _fmt_level(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


@dataclass
class FilterSpec:
    """Analysis filter. Empty stakes / game_types / missing dates means no restriction on that axis."""

    date_from: date | None = None
    date_to: date | None = None
    stakes: list[str] = field(default_factory=list)
    game_types: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> FilterSpec:
        if not payload:
            return cls()

        date_from = _parse_date(payload.get("date_from"))
        date_to = _parse_date(payload.get("date_to"))

        raw_stakes = payload.get("stakes") or []
        stakes: list[str] = []
        for item in raw_stakes:
            key = normalize_stakes(str(item))
            if key and key not in stakes:
                stakes.append(key)

        raw_game_types = payload.get("game_types") or []
        game_types: list[str] = []
        for item in raw_game_types:
            key = str(item).strip().lower()
            if key in _VALID_GAME_TYPES and key not in game_types:
                game_types.append(key)

        return cls(
            date_from=date_from,
            date_to=date_to,
            stakes=stakes,
            game_types=game_types,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "stakes": list(self.stakes),
            "game_types": list(self.game_types),
        }


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    # Accept YYYY-MM-DD (HTML date input) or YYYY/MM/DD
    text = text.replace("/", "-")[:10]
    return date.fromisoformat(text)


def hand_stakes_key(hand: Hand) -> str | None:
    return normalize_stakes(hand.stakes)


def hand_game_type(hand: Hand) -> str:
    """
    Classify table type from HH metadata.

    Rush & Cash (极速桌): table / filename contains RushAndCash.
    Otherwise treat as regular cash NLH (普通桌).
    """
    haystack = f"{hand.table_name} {hand.source_file}".lower()
    if "rushandcash" in haystack:
        return GAME_TYPE_RUSH
    return GAME_TYPE_NLH


def apply_filter(dataset: HandDataset, spec: FilterSpec | None) -> HandDataset:
    """Return a new dataset containing only hands matching the filter."""
    if spec is None:
        return HandDataset(hands=list(dataset.hands), source_label=dataset.source_label)

    stakes_set = {normalize_stakes(s) for s in spec.stakes if normalize_stakes(s)}
    game_type_set = {g for g in spec.game_types if g in _VALID_GAME_TYPES}
    start_dt = datetime.combine(spec.date_from, time.min) if spec.date_from else None
    # Inclusive end date: keep entire calendar day
    end_dt = datetime.combine(spec.date_to, time.max) if spec.date_to else None

    filtered: list[Hand] = []
    for hand in dataset.hands:
        if start_dt and hand.datetime < start_dt:
            continue
        if end_dt and hand.datetime > end_dt:
            continue
        if stakes_set:
            key = hand_stakes_key(hand)
            if key not in stakes_set:
                continue
        if game_type_set:
            if hand_game_type(hand) not in game_type_set:
                continue
        filtered.append(hand)

    return HandDataset(hands=filtered, source_label=dataset.source_label)


def available_stakes(hands: Iterable[Hand]) -> list[str]:
    found = {hand_stakes_key(h) for h in hands}
    found.discard(None)
    # Prefer preset order, then any extras discovered in data
    ordered: list[str] = []
    for preset in PRESET_STAKES:
        if preset in found:
            ordered.append(preset)
            found.discard(preset)
    ordered.extend(sorted(found))  # type: ignore[arg-type]
    return ordered


def available_game_types(hands: Iterable[Hand]) -> list[str]:
    found = {hand_game_type(h) for h in hands}
    return [gid for gid, _ in PRESET_GAME_TYPES if gid in found]


def empty_filter_options() -> dict[str, Any]:
    """Preset filter UI before any hand histories are loaded."""
    return {
        "date_from": None,
        "date_to": None,
        "stakes_presets": [
            {"id": s, "label": s.replace("/", "-"), "has_data": False}
            for s in PRESET_STAKES
        ],
        "stakes_in_data": [],
        "game_types_presets": [
            {"id": gid, "label": label, "has_data": False}
            for gid, label in PRESET_GAME_TYPES
        ],
        "game_types_in_data": [],
    }


def filter_options(dataset: HandDataset) -> dict[str, Any]:
    hands = dataset.sorted_hands()
    present = available_stakes(hands)
    present_set = set(present)
    present_game_types = set(available_game_types(hands))
    return {
        "date_from": hands[0].datetime.date().isoformat() if hands else None,
        "date_to": hands[-1].datetime.date().isoformat() if hands else None,
        "stakes_presets": [
            {
                "id": s,
                "label": s.replace("/", "-"),
                "has_data": s in present_set,
            }
            for s in PRESET_STAKES
        ],
        "stakes_in_data": present,
        "game_types_presets": [
            {
                "id": gid,
                "label": label,
                "has_data": gid in present_game_types,
            }
            for gid, label in PRESET_GAME_TYPES
        ],
        "game_types_in_data": available_game_types(hands),
    }
