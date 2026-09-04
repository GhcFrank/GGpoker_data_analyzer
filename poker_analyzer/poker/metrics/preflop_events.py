from __future__ import annotations

from collections.abc import Iterable
from typing import Any


# Public event keys are deliberately independent from UI labels.  The mapped
# attribute is the single membership definition shared by metric aggregation
# and replay filtering.
EVENT_ATTRIBUTES: dict[str, dict[str, str]] = {
    "open_raise": {
        "all_fold": "all_fold",
        "faced_3bet": "faced_3bet",
    },
    "3bet": {
        "opener_responded": "opener_acted",
        "opener_fold": "opener_fold",
        "opener_call": "opener_call",
        "opener_4bet": "opener_4bet",
        "all_fold": "all_fold",
        "cold_4bet": "cold_4bet",
    },
    "4bet": {
        "threebettor_faced": "threebettor_faced",
        "all_fold": "all_fold",
        "faced_5bet": "faced_5bet",
        "threebettor_call": "threebettor_call",
    },
    "5bet": {
        "fourbettor_faced": "fourbettor_faced",
        "fourbettor_fold": "fourbettor_fold",
        "fourbettor_call": "fourbettor_call",
    },
}


def spot_matches_event(action: str, spot: Any, event_key: str | None) -> bool:
    """Whether one already-extracted base spot belongs to ``event_key``.

    An empty event selects the complete base sample.  Unknown event keys fail
    closed so stale or forged client state cannot broaden the replay sample.
    """
    key = str(event_key or "").strip().lower()
    if not key:
        return True
    attribute = EVENT_ATTRIBUTES.get(action, {}).get(key)
    return bool(attribute and getattr(spot, attribute, False))


def spots_for_event(action: str, spots: Iterable[Any], event_key: str) -> list[Any]:
    return [spot for spot in spots if spot_matches_event(action, spot, event_key)]


def build_event_counts(action: str, spots: Iterable[Any]) -> dict[str, int]:
    """Aggregate event membership without re-reading or re-parsing hands."""
    values = list(spots)
    return {
        event_key: sum(1 for spot in values if spot_matches_event(action, spot, event_key))
        for event_key in EVENT_ATTRIBUTES.get(action, {})
    }
