from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from poker.metrics.base import get_metric, list_metrics, load_builtin_metrics
from poker.models import HandDataset
from poker.sources import LocalDirectorySource

# Default: repo's ../data relative to this package's project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT.parent / "data"


class AnalysisService:
    """Orchestrates data loading and metric computation."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        load_builtin_metrics()
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self._dataset: HandDataset | None = None

    def reload(self) -> HandDataset:
        source = LocalDirectorySource(self.data_dir)
        self._dataset = source.load()
        return self._dataset

    @property
    def dataset(self) -> HandDataset:
        if self._dataset is None:
            self.reload()
        assert self._dataset is not None
        return self._dataset

    def summary(self) -> dict[str, Any]:
        ds = self.dataset
        return {
            "source": ds.source_label,
            "hand_count": len(ds.hands),
            "file_count": len({h.source_file for h in ds.hands}),
            "date_range": {
                "start": ds.hands[0].datetime.isoformat(sep=" ") if ds.hands else None,
                "end": ds.hands[-1].datetime.isoformat(sep=" ") if ds.hands else None,
            },
            "metrics": list_metrics(),
        }

    def compute_metric(self, metric_id: str) -> dict[str, Any]:
        metric = get_metric(metric_id)
        return metric.compute(self.dataset)


@lru_cache(maxsize=1)
def get_service() -> AnalysisService:
    return AnalysisService()
