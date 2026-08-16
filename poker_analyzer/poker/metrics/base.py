from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Type

from poker.models import HandDataset


class Metric(ABC):
    """
    One analysis concern = one metric plugin.

    Add a new file under poker/metrics/, subclass Metric, and call
    ``register(YourMetric())`` — the API and UI discover it automatically.
    """

    id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str] = ""
    chart_type: ClassVar[str] = "line"  # hint for frontend

    @abstractmethod
    def compute(self, dataset: HandDataset, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a JSON-serializable payload for this metric."""
        raise NotImplementedError


_REGISTRY: dict[str, Metric] = {}


def register(metric: Metric | Type[Metric]) -> Metric | Type[Metric]:
    """Register a metric instance, or a Metric subclass (auto-instantiated)."""
    instance: Metric
    if isinstance(metric, type):
        instance = metric()
    else:
        instance = metric

    if not getattr(instance, "id", None):
        raise ValueError("Metric must define a non-empty id")
    _REGISTRY[instance.id] = instance
    return metric


def get_metric(metric_id: str) -> Metric:
    try:
        return _REGISTRY[metric_id]
    except KeyError as exc:
        raise KeyError(f"Unknown metric: {metric_id}") from exc


def list_metrics() -> list[dict[str, str]]:
    return [
        {
            "id": m.id,
            "name": m.name,
            "description": m.description,
            "chart_type": m.chart_type,
        }
        for m in _REGISTRY.values()
    ]


def load_builtin_metrics() -> None:
    """Import built-in metric modules so they self-register."""
    from poker.metrics import preflop_analysis  # noqa: F401
    from poker.metrics import profit  # noqa: F401
    from poker.metrics import when_i_raise  # noqa: F401
