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
    """Analysis filter. Empty stakes / missing dates means no restriction on that axis."""

    date_from: date | None = None
    date_to: date | None = None
    stakes: list[str] = field(default_factory=list)

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

        return cls(date_from=date_from, date_to=date_to, stakes=stakes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "stakes": list(self.stakes),
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


def apply_filter(dataset: HandDataset, spec: FilterSpec | None) -> HandDataset:
    """Return a new dataset containing only hands matching the filter."""
    if spec is None:
        return HandDataset(hands=list(dataset.hands), source_label=dataset.source_label)

    stakes_set = {normalize_stakes(s) for s in spec.stakes if normalize_stakes(s)}
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


def filter_options(dataset: HandDataset) -> dict[str, Any]:
    hands = dataset.sorted_hands()
    present = available_stakes(hands)
    present_set = set(present)
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
    }
