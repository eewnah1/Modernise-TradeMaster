"""FastAPI dashboard for Modernise-TradeMaster."""

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Allow imports from repo root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard.jobs import JobManager

app = FastAPI(title="Modernise-TradeMaster Dashboard", version="0.1.0")

WORK_ROOT = Path(tempfile.gettempdir()) / "mtm_dashboard_jobs"
job_manager = JobManager(work_root=WORK_ROOT)

app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_ROOT = REPO_ROOT / "config" / "input_config"
DATA_ROOT = REPO_ROOT / "data" / "data"
EXPERIMENT_ROOT = REPO_ROOT / "experiment"


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "active_jobs": sum(1 for j in job_manager.jobs.values() if j["status"] == "running"),
    }


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
async def get_job(job_id: str):
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    job["log"] = job_manager.read_log(job_id)
    return job


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


@app.get("/api/v1/jobs/{job_id}/results")
async def get_results(job_id: str) -> Dict[str, Any]:
    """Read metrics, equity curve and trades from a completed demo job."""
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    work_dir = Path(job["work_dir"])
    metrics = {}
    if (work_dir / "metrics.json").exists():
        metrics = json.loads((work_dir / "metrics.json").read_text())

    equity = []
    if (work_dir / "equity.csv").exists():
        import pandas as pd
        df = pd.read_csv(work_dir / "equity.csv")
        equity = df.to_dict(orient="records")

    trades = []
    trades_path = work_dir / "trades.csv"
    if trades_path.exists() and trades_path.stat().st_size > 0:
        import pandas as pd
        tdf = pd.read_csv(trades_path)
        trades = tdf.head(200).to_dict(orient="records")

    return {"metrics": metrics, "equity": equity, "trades": trades}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
