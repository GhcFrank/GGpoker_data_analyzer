from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

from poker.filters import FilterSpec
from poker.service import get_service

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Poker Analyzer", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class AnalyzeFilter(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    stakes: list[str] = Field(default_factory=list)


def _spec_from_body(body: AnalyzeFilter | None) -> FilterSpec:
    payload: dict[str, Any] | None = body.model_dump() if body else None
    return FilterSpec.from_payload(payload)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"title": "Poker Analyzer"})


@app.get("/api/summary")
async def api_summary():
    return get_service().summary()


@app.post("/api/reload")
async def api_reload():
    """Re-scan local data directory (useful after adding new HH files)."""
    get_service().reload()
    return get_service().summary()


@app.get("/api/metrics")
async def api_metrics():
    """List all registered metric plugins."""
    return {"metrics": get_service().summary()["metrics"]}


@app.get("/api/metrics/{metric_id}")
async def api_metric_get(metric_id: str):
    """Compute a metric on the full dataset (no filter)."""
    try:
        return get_service().compute_metric(metric_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/metrics/{metric_id}")
async def api_metric_post(metric_id: str, body: AnalyzeFilter | None = None):
    """Compute a metric on the filtered dataset."""
    try:
        return get_service().compute_metric(metric_id, _spec_from_body(body))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/analyze/{metric_id}")
async def api_analyze(metric_id: str, body: AnalyzeFilter | None = None):
    """Alias for filtered metric compute (local analyze button)."""
    return await api_metric_post(metric_id, body)


@app.get("/api/profit/curve")
async def api_profit_curve():
    return get_service().compute_metric("profit_curve")


@app.post("/api/profit/curve")
async def api_profit_curve_filtered(body: AnalyzeFilter | None = None):
    return get_service().compute_metric("profit_curve", _spec_from_body(body))
