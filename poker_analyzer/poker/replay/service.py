from __future__ import annotations

from typing import Any

from poker.models import HandDataset
from poker.replay.matchers import SOURCES, matcher_for
from poker.replay.serialize import serialize_hand


def get_replay(
    dataset: HandDataset,
    source: str,
    index: int,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one matching hand. Scans in order; does not keep other hands."""
    if source not in SOURCES:
        raise ValueError(f"未知回放来源: {source}")
    try:
        index = int(index)
    except (TypeError, ValueError) as exc:
        raise ValueError("index 必须是整数") from exc
    if index < 0:
        raise ValueError("index 必须 >= 0")

    matches = matcher_for(source, options)
    found = None
    total = 0
    for hand in dataset.sorted_hands():
        if not matches(hand):
            continue
        if total == index:
            found = hand
        total += 1

    if total == 0:
        return {"index": 0, "total": 0, "hand": None}
    if found is None:
        raise ValueError(f"index {index} 超出范围 0..{total - 1}")
    opts = options or {}
    return {"index": index, "total": total, "hand": serialize_hand(found, table_format=opts.get("table_format"))}
