from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from poker.service import get_service

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Poker Analyzer", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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
async def api_metric(metric_id: str):
    """
    Compute a single metric.

    Each metric has its own endpoint path so new analyses can be added
    without touching existing ones.
    """
    try:
        return get_service().compute_metric(metric_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# Convenience aliases for phase-1 metrics (explicit, stable URLs)
@app.get("/api/profit/curve")
async def api_profit_curve():
    return get_service().compute_metric("profit_curve")
