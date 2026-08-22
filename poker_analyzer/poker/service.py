from __future__ import annotations

from pathlib import Path
from typing import Any

from poker.config import format_data_dir, load_data_dir, resolve_data_dir, save_data_dir
from poker.filters import FilterSpec, apply_filter, filter_options
from poker.metrics.base import get_metric, list_metrics, load_builtin_metrics
from poker.models import HandDataset
from poker.sources import LocalDirectorySource


class AnalysisService:
    """Orchestrates data loading and metric computation."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        load_builtin_metrics()
        self.data_dir = resolve_data_dir(data_dir) if data_dir else load_data_dir()
        self._dataset: HandDataset | None = None

    def set_data_dir(self, data_dir: Path | str, *, persist: bool = True) -> Path:
        path = resolve_data_dir(data_dir)
        if persist:
            save_data_dir(path)
        self.data_dir = path
        self._dataset = None
        return path

    def reload(self) -> HandDataset:
        source = LocalDirectorySource(self.data_dir)
        self._dataset = source.load()
        return self._dataset

    @property
    def is_loaded(self) -> bool:
        return self._dataset is not None

    @property
    def dataset(self) -> HandDataset:
        if self._dataset is None:
            self.reload()
        assert self._dataset is not None
        return self._dataset

    def _count_source_files(self) -> int:
        if not self.data_dir.exists():
            return 0
        return sum(1 for p in self.data_dir.glob("*.txt") if p.is_file())

    def dir_info(self) -> dict[str, Any]:
        from poker.filters import filter_options_from_directory

        return {
            "data_dir": format_data_dir(self.data_dir),
            "data_dir_resolved": str(self.data_dir),
            "source": None,
            "hand_count": 0,
            "file_count": self._count_source_files(),
            "date_range": {"start": None, "end": None},
            "filter": filter_options_from_directory(self.data_dir),
            "metrics": list_metrics(),
            "loaded": False,
        }

    def ensure_loaded(self) -> HandDataset:
        return self.dataset

    def summary(self) -> dict[str, Any]:
        if self._dataset is None:
            return self.dir_info()
        ds = self._dataset
        return {
            "data_dir": format_data_dir(self.data_dir),
            "data_dir_resolved": str(self.data_dir),
            "source": ds.source_label,
            "hand_count": len(ds.hands),
            "file_count": len({h.source_file for h in ds.hands}),
            "date_range": {
                "start": ds.hands[0].datetime.isoformat(sep=" ") if ds.hands else None,
                "end": ds.hands[-1].datetime.isoformat(sep=" ") if ds.hands else None,
            },
            "filter": filter_options(ds),
            "metrics": list_metrics(),
            "loaded": True,
        }

    def filtered_dataset(self, spec: FilterSpec | None = None) -> HandDataset:
        return apply_filter(self.dataset, spec)

    def compute_metric(
        self,
        metric_id: str,
        spec: FilterSpec | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        effective = spec or FilterSpec()
        if not effective.table_format:
            raise ValueError("请先选择桌型（6-max 或 9-max）")
        metric = get_metric(metric_id)
        filtered = self.filtered_dataset(spec)
        result = metric.compute(filtered, options=options)
        result["filter"] = effective.to_dict()
        result["filtered_hand_count"] = len(filtered.hands)
        result["total_hand_count"] = len(self.dataset.hands)
        return result

    def replay_hand(
        self,
        source: str,
        index: int,
        spec: FilterSpec | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from poker.replay import get_replay

        filtered = self.filtered_dataset(spec)
        effective = spec or FilterSpec()
        if not effective.table_format:
            raise ValueError("请先选择桌型（6-max 或 9-max）")
        result = get_replay(filtered, source, index, options)
        result["source"] = source
        result["filter"] = effective.to_dict()
        return result


_service: AnalysisService | None = None


def get_service() -> AnalysisService:
    global _service
    if _service is None:
        _service = AnalysisService()
    return _service


def reset_service(data_dir: Path | str | None = None) -> AnalysisService:
    global _service
    if data_dir is None:
        _service = AnalysisService()
    else:
        _service = AnalysisService(data_dir)
        save_data_dir(_service.data_dir)
    return _service
