"""FastAPI dashboard for Modernise-TradeMaster."""

import json
import os
import shutil
import sys
import tempfile
import asyncio
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import pandas as pd
try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None
import yaml
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

# Allow imports from repo root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard.jobs import JobManager
from dashboard import analytics

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_ROOT = REPO_ROOT / "config" / "input_config"
DATA_ROOT = REPO_ROOT / "data" / "data"
EXPERIMENT_ROOT = REPO_ROOT / "experiment"

app = FastAPI(title="Modernise-TradeMaster Dashboard", version="0.3.0")
START_TIME = time.time()

# Static sector mapping for the supported data universes used by the dashboard demos.
UNIVERSE_SECTOR = {
    "BTC": "Cryptocurrency",
    "BTC_even": "Cryptocurrency",
    "BTC_for_iRDPG": "Cryptocurrency",
    "OE_BTC": "Cryptocurrency",
    "ETH": "Cryptocurrency",
    "dj30": "US Equities",
    "sz50": "China A-Shares",
    "exchange": "FX / Commodities",
}

WORK_ROOT = Path(tempfile.gettempdir()) / "mtm_dashboard_jobs"
job_manager = JobManager(work_root=WORK_ROOT, repo_root=REPO_ROOT)

app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "active_jobs": sum(1 for j in job_manager.jobs.values() if j["status"] == "running"),
        "queued_jobs": sum(1 for j in job_manager.jobs.values() if j["status"] == "queued"),
        "version": app.version,
    }


@app.get("/api/v1/queue/stats")
async def queue_stats() -> Dict[str, Any]:
    """Runtime status of the distributed task queue."""
    return job_manager.queue_stats()


# ---------------------------------------------------------------------------
# Catalog endpoints
# ---------------------------------------------------------------------------

@app.get("/api/v1/agents")
async def list_agents() -> List[Dict[str, Any]]:
    """List agent configs from config/input_config/agent."""
    agents = []
    if CONFIG_ROOT.exists():
        for task_dir in (CONFIG_ROOT / "agent").iterdir():
            if task_dir.is_dir():
                for config_file in task_dir.glob("*.yml"):
                    agents.append(
                        {
                            "task": task_dir.name,
                            "name": config_file.stem,
                            "path": str(config_file.relative_to(REPO_ROOT)),
                        }
                    )
    return sorted(agents, key=lambda x: (x["task"], x["name"]))


@app.get("/api/v1/envs")
async def list_envs() -> List[Dict[str, Any]]:
    """List environment configs from config/input_config/env."""
    envs = []
    if CONFIG_ROOT.exists():
        env_dir = CONFIG_ROOT / "env"
        for task_dir in env_dir.iterdir():
            if task_dir.is_dir():
                for sub_dir in task_dir.iterdir():
                    if sub_dir.is_dir():
                        for config_file in sub_dir.glob("*.yml"):
                            envs.append(
                                {
                                    "task": task_dir.name,
                                    "scenario": sub_dir.name,
                                    "name": config_file.stem,
                                    "path": str(config_file.relative_to(REPO_ROOT)),
                                }
                            )
    return sorted(envs, key=lambda x: (x["task"], x["scenario"], x["name"]))


@app.get("/api/v1/datasets")
async def list_datasets() -> List[Dict[str, Any]]:
    """List available CSV datasets under data/data."""
    datasets = []
    if DATA_ROOT.exists():
        for dataset_dir in DATA_ROOT.iterdir():
            if dataset_dir.is_dir():
                for csv_file in dataset_dir.glob("*.csv"):
                    datasets.append(
                        {
                            "universe": dataset_dir.name,
                            "name": csv_file.name,
                            "path": str(csv_file.relative_to(REPO_ROOT)),
                        }
                    )
    return sorted(datasets, key=lambda x: (x["universe"], x["name"]))


@app.get("/api/v1/experiments")
async def list_experiment_scripts() -> List[Dict[str, Any]]:
    """List experiment runner scripts from experiment/."""
    scripts = []
    if EXPERIMENT_ROOT.exists():
        for task_dir in EXPERIMENT_ROOT.iterdir():
            if task_dir.is_dir():
                for agent_dir in task_dir.iterdir():
                    if agent_dir.is_dir():
                        exp_file = agent_dir / "experiment.py"
                        if exp_file.exists():
                            scripts.append(
                                {
                                    "task": task_dir.name,
                                    "agent": agent_dir.name,
                                    "path": str(exp_file.relative_to(REPO_ROOT)),
                                }
                            )
    return sorted(scripts, key=lambda x: (x["task"], x["agent"]))


# ---------------------------------------------------------------------------
# System & resource endpoints
# ---------------------------------------------------------------------------

def _read_mem_gb() -> Dict[str, float]:
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()

        def val(key: str) -> float:
            line = next((l for l in lines if l.startswith(key)), "")
            return int(line.split()[1]) / (1024 * 1024) if line else 0.0

        return {"total_gb": round(val("MemTotal"), 2), "available_gb": round(val("MemAvailable"), 2)}
    except Exception:
        return {"total_gb": 0.0, "available_gb": 0.0}


def _read_disk_gb() -> Dict[str, float]:
    try:
        du = shutil.disk_usage(str(REPO_ROOT))
        return {"total_gb": round(du.total / 1e9, 1), "free_gb": round(du.free / 1e9, 1)}
    except Exception:
        return {"total_gb": 0.0, "free_gb": 0.0}


def _read_load() -> Dict[str, float]:
    try:
        one, five, fifteen = os.getloadavg()
        return {"1m": round(one, 2), "5m": round(five, 2), "15m": round(fifteen, 2)}
    except Exception:
        return {}


@app.get("/api/v1/system")
async def system_stats() -> Dict[str, Any]:
    """Runtime health of the dashboard host."""
    mem = _read_mem_gb()
    disk = _read_disk_gb()
    return {
        "platform": "Modernise-TradeMaster Dashboard",
        "version": app.version,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "cpu_count": os.cpu_count() or 1,
        "memory_gb": mem,
        "memory_used_pct": round((mem["total_gb"] - mem["available_gb"]) / mem["total_gb"] * 100, 2) if mem.get("total_gb") else 0.0,
        "disk": disk,
        "disk_used_pct": round((disk["total_gb"] - disk["free_gb"]) / disk["total_gb"] * 100, 2) if disk.get("total_gb") else 0.0,
        "load": _read_load(),
    }


def _resolve_repo_file(root: Path, rel: str) -> Path:
    """Resolve a path that may be stored relative to REPO_ROOT by stripping the root prefix."""
    try:
        prefix = str(root.relative_to(REPO_ROOT)) + "/"
    except ValueError:
        prefix = ""
    if prefix and rel.startswith(prefix):
        rel = rel[len(prefix):]
    target = (root / rel).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise HTTPException(status_code=400, detail="path outside allowed directory")
    if not target.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return target


@app.get("/api/v1/config")
async def read_config(path: str = Query(..., description="config path relative to repo")) -> Any:
    """Read a YAML config file under config/input_config."""
    target = _resolve_repo_file(CONFIG_ROOT, path)
    try:
        return yaml.safe_load(target.read_text()) or {}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to parse config: {exc}")


@app.get("/api/v1/datasets/preview")
async def preview_dataset(path: str = Query(..., description="dataset path relative to repo"), rows: int = Query(20, ge=1, le=200)) -> Dict[str, Any]:
    """Return a CSV preview (columns + head rows)."""
    target = _resolve_repo_file(DATA_ROOT, path)
    try:
        df = pd.read_csv(target, nrows=rows)
        return {
            "path": path,
            "columns": list(df.columns),
            "rows": df.head(rows).to_dict(orient="records"),
            "shape": [df.shape[0], df.shape[1]],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to read dataset: {exc}")


# ---------------------------------------------------------------------------
# Job endpoints
# ---------------------------------------------------------------------------

@app.post("/api/v1/jobs/demo")
async def start_demo_job(payload: dict):
    """Start a Q-learning demo job on a selected dataset."""
    data_path = payload.get("data")
    if not data_path:
        raise HTTPException(status_code=400, detail="data path is required")
    full_data = REPO_ROOT / data_path
    if not full_data.exists():
        raise HTTPException(status_code=404, detail=f"dataset not found: {data_path}")

    episodes = int(payload.get("episodes", 200))
    lr = float(payload.get("lr", 0.1))
    eps = float(payload.get("eps", 0.1))
    gamma = float(payload.get("gamma", 0.9))

    output_dir = WORK_ROOT / str(uuid.uuid4())[:8]
    command = [
        sys.executable,
        "-u",
        str((Path(__file__).parent / "runners" / "demo_strategy.py").resolve()),
        "--data",
        str(full_data.resolve()),
        "--output",
        str(output_dir),
        "--episodes",
        str(episodes),
        "--lr",
        str(lr),
        "--eps",
        str(eps),
        "--gamma",
        str(gamma),
    ]

    job_id = await job_manager.start(
        command,
        job_type="demo",
        meta={
            "data": data_path,
            "episodes": episodes,
            "lr": lr,
            "eps": eps,
            "gamma": gamma,
        },
        work_dir=output_dir,
    )
    return {"job_id": job_id, "status": "running"}


@app.post("/api/v1/jobs/experiment")
async def start_experiment_job(payload: dict):
    """Start an experiment runner script as a background job."""
    script_path = payload.get("script")
    if not script_path:
        raise HTTPException(status_code=400, detail="script path is required")

    full_script = REPO_ROOT / script_path
    if not full_script.exists():
        raise HTTPException(status_code=404, detail=f"script not found: {script_path}")

    output_dir = WORK_ROOT / str(uuid.uuid4())[:8]
    command = [sys.executable, "-u", str(full_script.resolve())]
    # Add any extra arguments passed by the UI
    for key, value in payload.get("args", {}).items():
        command.extend([f"--{key}", str(value)])

    job_id = await job_manager.start(
        command,
        job_type="experiment",
        meta={"script": script_path, "args": payload.get("args", {})},
        work_dir=output_dir,
    )
    return {"job_id": job_id, "status": "running"}


@app.get("/api/v1/jobs")
async def list_jobs():
    return job_manager.list_jobs()


@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: str, tail: int = Query(200, ge=0, le=5000)):
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    job["log"] = job_manager.read_log(job_id, tail=tail)
    return job


@app.get("/api/v1/jobs/{job_id}/tail")
async def tail_job_log(job_id: str, lines: int = Query(100, ge=1, le=5000)):
    return {"job_id": job_id, "log": job_manager.read_log(job_id, tail=lines)}


@app.get("/api/v1/jobs/{job_id}/files")
async def list_job_files(job_id: str):
    return {"job_id": job_id, "files": job_manager.list_files(job_id)}


@app.get("/api/v1/jobs/{job_id}/files/{name}")
async def read_job_file(job_id: str, name: str):
    content = job_manager.read_file(job_id, name)
    if content is None:
        raise HTTPException(status_code=404, detail="file not found or not readable")
    return PlainTextResponse(content)


@app.post("/api/v1/jobs/{job_id}/stop")
async def stop_job(job_id: str):
    stopped = await job_manager.stop(job_id)
    if not stopped:
        raise HTTPException(status_code=400, detail="job not running or not found")
    return {"status": "stopped"}


@app.delete("/api/v1/jobs/{job_id}")
async def delete_job(job_id: str):
    deleted = job_manager.delete(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="job not found")
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Results endpoints
# ---------------------------------------------------------------------------

def _read_job_equity_and_trades(job_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[np.ndarray]]:
    """Load equity, trades and the dataset close prices for a job."""
    job = job_manager.get(job_id)
    if not job:
        return [], [], None
    work_dir = Path(job["work_dir"])

    equity = []
    if (work_dir / "equity.csv").exists():
        df = pd.read_csv(work_dir / "equity.csv")
        equity = df.to_dict(orient="records")

    trades = []
    trades_path = work_dir / "trades.csv"
    if trades_path.exists() and trades_path.stat().st_size > 0:
        tdf = pd.read_csv(trades_path)
        trades = tdf.head(500).to_dict(orient="records")

    close = None
    try:
        data_path = job.get("meta", {}).get("data")
        if data_path:
            target = _resolve_repo_file(DATA_ROOT, data_path)
            df = pd.read_csv(target)
            if "close" in df.columns:
                close = df["close"].dropna().astype(float).values
    except Exception:
        close = None

    return equity, trades, close


def _load_job_analytics(job_id: str) -> Dict[str, Any]:
    """Compute analytics bundle for a completed job."""
    equity, trades, close = _read_job_equity_and_trades(job_id)
    return analytics.compute_result_analytics(equity, trades, close)


@app.get("/api/v1/jobs/{job_id}/results")
async def get_results(job_id: str) -> Dict[str, Any]:
    """Read metrics, equity curve, trades, analytics and output files from a completed job."""
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    work_dir = Path(job["work_dir"])
    metrics = {}
    if (work_dir / "metrics.json").exists():
        metrics = json.loads((work_dir / "metrics.json").read_text())

    equity, trades, close = _read_job_equity_and_trades(job_id)
    analytics_data = analytics.compute_result_analytics(equity, trades, close)

    return {
        "metrics": metrics,
        "analytics": analytics_data,
        "equity": equity,
        "drawdown": analytics_data["rolling"].get("drawdown", []),
        "files": job_manager.list_files(job_id),
    }


def _sector_exposure(universe: str) -> Dict[str, float]:
    sector = UNIVERSE_SECTOR.get(universe, "Diversified / Unknown")
    return {sector: 100.0}


@app.get("/api/v1/jobs/{job_id}/risk")
async def get_job_risk(job_id: str) -> Dict[str, Any]:
    """Portfolio risk telemetry for a completed job."""
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    analytics_data = _load_job_analytics(job_id)
    risk = analytics_data.get("risk", {}) or {}
    data_path = job.get("meta", {}).get("data", "")
    universe = Path(data_path).parent.name if data_path else ""
    risk["sector_exposure"] = _sector_exposure(universe)
    risk.setdefault(
        "exposure",
        {
            "long_pct": risk.get("long_pct"),
            "short_pct": risk.get("short_pct"),
            "cash_pct": risk.get("cash_pct"),
            "net_exposure_pct": risk.get("net_exposure_pct"),
            "gross_exposure_pct": risk.get("gross_exposure_pct"),
            "max_concentration_pct": risk.get("max_concentration_pct"),
        },
    )
    return risk


@app.get("/api/v1/jobs/{job_id}/compass")
async def get_job_compass(job_id: str) -> Dict[str, Any]:
    """PRUDEX-Compass evaluation for a completed job."""
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    analytics_data = _load_job_analytics(job_id)
    agent_type = job.get("type", "unknown")
    data_path = job.get("meta", {}).get("data", "")
    return analytics.compute_prudex_compass(
        analytics_data, agent_type=agent_type, data_path=data_path
    )


@app.get("/api/v1/jobs/{job_id}/pride")
async def get_job_pride(job_id: str) -> Dict[str, Any]:
    """PRIDE-Star metric radar for a completed job."""
    if not job_manager.get(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    analytics_data = _load_job_analytics(job_id)
    return analytics.compute_pride_star(analytics_data)


# ---------------------------------------------------------------------------
# Real-time job stream
# ---------------------------------------------------------------------------

@app.get("/api/v1/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    """Server-sent events endpoint for live job status, metrics and log tail."""

    async def event_generator():
        last_log = ""
        last_status = None
        finished_loops = 0
        while True:
            job = job_manager.get(job_id)
            if not job:
                yield f"event: error\ndata: {json.dumps({'detail': 'job not found'})}\n\n"
                break

            log = job_manager.read_log(job_id, tail=200)
            metrics = job_manager.read_metrics(job_id)
            status = job["status"]
            payload = {
                "status": status,
                "log": log,
                "metrics": metrics,
                "finished": job.get("finished"),
                "returncode": job.get("returncode"),
            }

            # Only emit if something changed or still running
            if log != last_log or status != last_status or status == "running":
                yield f"event: update\ndata: {json.dumps(payload)}\n\n"
                last_log = log
                last_status = status

            if status in ("success", "error", "stopped"):
                finished_loops += 1
                if finished_loops >= 3:
                    yield f"event: close\ndata: {json.dumps({'status': status})}\n\n"
                    break

            await asyncio.sleep(1.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Live market snapshot
# ---------------------------------------------------------------------------

MARKET_CACHE: Dict[str, Any] = {"data": {}, "ts": 0.0}
MARKET_TICKERS = ["SPY", "QQQ", "GLD", "TLT", "BTC-USD", "ETH-USD", "^VIX"]


def _fetch_market_snapshot() -> Dict[str, Any]:
    """Fetch last close/change for a hard-coded watchlist via yfinance."""
    if yf is None:
        return {"error": "yfinance not installed", "quotes": []}

    quotes = []
    for ticker in MARKET_TICKERS:
        try:
            hist = yf.Ticker(ticker).history(period="2d", interval="1d")
            if hist is None or hist.empty:
                continue
            hist = hist.dropna()
            if len(hist) < 1:
                continue
            last = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2] if len(hist) > 1 else last
            change = (last / prev - 1.0) * 100 if prev else 0.0
            quotes.append({
                "ticker": ticker,
                "price": round(float(last), 4),
                "change_pct": round(float(change), 4),
                "currency": "USD" if "USD" not in ticker else "USD",
            })
        except Exception as exc:
            quotes.append({"ticker": ticker, "error": str(exc)})
    return {"quotes": quotes, "timestamp": time.time()}


def _build_lob(mid: float, ticker: str, levels: int = 10) -> Dict[str, Any]:
    """Construct a synthetic order-book ladder around the last mid price."""
    base_spread_bps = 5.0 if "USD" not in ticker.upper() else 15.0
    base_spread = mid * base_spread_bps / 10000.0
    level_step = base_spread / 2.0

    bids = []
    asks = []
    total_bid_size = 0
    total_ask_size = 0

    for i in range(levels):
        offset = base_spread / 2.0 + i * level_step
        bid_price = mid - offset
        ask_price = mid + offset
        bid_size = int(max(1, round(1000 * np.exp(-0.2 * i) + np.random.randint(-50, 50))))
        ask_size = int(max(1, round(1000 * np.exp(-0.2 * i) + np.random.randint(-50, 50))))
        bids.append({
            "level": i + 1,
            "price": round(float(bid_price), 4),
            "size": bid_size,
            "cum_size": None,
        })
        asks.append({
            "level": i + 1,
            "price": round(float(ask_price), 4),
            "size": ask_size,
            "cum_size": None,
        })
        total_bid_size += bid_size
        total_ask_size += ask_size

    cum_bid = 0
    for b in bids:
        cum_bid += b["size"]
        b["cum_size"] = cum_bid
    cum_ask = 0
    for a in asks:
        cum_ask += a["size"]
        a["cum_size"] = cum_ask

    spread = round(asks[0]["price"] - bids[0]["price"], 4)
    spread_bps = round((spread / mid) * 10000, 2) if mid else 0.0
    total_depth = total_bid_size + total_ask_size
    imbalance = round((total_bid_size - total_ask_size) / max(total_depth, 1), 4)

    flow = []
    for _ in range(20):
        side = "buy" if np.random.random() > 0.5 else "sell"
        size = int(np.random.randint(10, 200))
        jitter = np.random.uniform(0, max(spread / 2.0, 0.01))
        price = round(mid + (jitter if side == "buy" else -jitter), 4)
        flow.append({
            "side": side,
            "size": size,
            "price": price,
            "timestamp": round(time.time() - np.random.uniform(0, 60), 2),
        })
    flow.sort(key=lambda x: x["timestamp"], reverse=True)

    return {
        "ticker": ticker,
        "mid": round(float(mid), 4),
        "spread": spread,
        "spread_bps": spread_bps,
        "bid_depth": total_bid_size,
        "ask_depth": total_ask_size,
        "total_depth": total_depth,
        "imbalance": imbalance,
        "bids": bids,
        "asks": asks,
        "flow": flow,
        "timestamp": time.time(),
    }


def _fetch_lob_snapshot(ticker: str = "SPY") -> Dict[str, Any]:
    """Fetch last price and build a synthetic LOB ladder."""
    if yf is None:
        return {"error": "yfinance not installed", "ticker": ticker}
    try:
        hist = yf.Ticker(ticker).history(period="2d", interval="1d")
        if hist is None or hist.empty:
            return {"error": f"no market data for {ticker}", "ticker": ticker}
        mid = float(hist["Close"].dropna().iloc[-1])
        return _build_lob(mid, ticker)
    except Exception as exc:
        return {"error": str(exc), "ticker": ticker}


LOB_CACHE: Dict[str, Any] = {"data": {}, "ts": 0.0}


@app.get("/api/v1/market/lob")
async def market_lob(ticker: str = Query("SPY", description="Underlying ticker for LOB")) -> Dict[str, Any]:
    """Simulated 10-level limit order book and order-flow tape.

    Uses live yfinance close as the mid price and generates synthetic depth
    around it. This is a visual/quantitative representation suitable for
    dashboard exploration; for live production LOB data, wire a real feed.
    """
    now = time.time()
    cache_key = ticker.upper()
    if now - LOB_CACHE["ts"] > 5 or LOB_CACHE["data"].get("ticker") != cache_key:
        data = await run_in_threadpool(lambda: _fetch_lob_snapshot(cache_key))
        LOB_CACHE["data"] = data
        LOB_CACHE["ts"] = now
    return LOB_CACHE["data"]


@app.get("/api/v1/market/snapshot")
async def market_snapshot() -> Dict[str, Any]:
    """Cached live market snapshot for the dashboard Market Monitor."""
    if time.time() - MARKET_CACHE["ts"] > 60:
        data = await run_in_threadpool(_fetch_market_snapshot)
        MARKET_CACHE["data"] = data
        MARKET_CACHE["ts"] = time.time()
    return MARKET_CACHE["data"]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
