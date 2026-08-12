"""Distributed task queue for running RL experiments from the dashboard.

The default backend is a local asyncio worker pool (priority queue). It can be
swapped for a Ray or Celery backend via the ``MTM_QUEUE_BACKEND`` environment
variable; if the chosen backend is unavailable the manager falls back to the
local implementation.
"""

import asyncio
import json
import logging
import os
import shutil

import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mtm.jobs")


class BaseTaskQueue(ABC):
    """Abstract task queue backend."""

    @abstractmethod
    async def submit(
        self,
        command: List[str],
        job_id: str,
        work_dir: Path,
        meta: dict,
        priority: int = 5,
    ) -> None:
        """Enqueue a job for execution."""

    @abstractmethod
    def stats(self) -> Dict[str, Any]:
        """Return queue/worker statistics."""

    async def shutdown(self) -> None:
        """Stop background workers."""


class LocalTaskQueue(BaseTaskQueue):
    """In-memory priority task queue backed by ``asyncio.PriorityQueue``.

    Lower ``priority`` values are scheduled first. The queue uses a fixed
    number of concurrent workers (default ``MTM_QUEUE_WORKERS`` or 2).
    """

    def __init__(self, job_manager: "JobManager", max_workers: int = 2):
        self.job_manager = job_manager
        self.max_workers = max_workers
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._seq = 0
        self._started = False
        self._worker_tasks: List[asyncio.Task] = []

    async def _start_workers(self) -> None:
        if self._started:
            return
        self._started = True
        self._worker_tasks = [
            asyncio.create_task(self._worker_loop()) for _ in range(self.max_workers)
        ]

    async def submit(
        self,
        command: List[str],
        job_id: str,
        work_dir: Path,
        meta: dict,
        priority: int = 5,
    ) -> None:
        await self._start_workers()
        self._seq += 1
        self._queue.put_nowait(
            (priority, self._seq, job_id, command, work_dir, meta)
        )

    def stats(self) -> Dict[str, Any]:
        queued = self._queue.qsize()
        running = sum(
            1 for j in self.job_manager.jobs.values() if j["status"] == "running"
        )
        completed = sum(
            1
            for j in self.job_manager.jobs.values()
            if j["status"] in ("success", "error", "stopped")
        )
        return {
            "backend": "local",
            "max_workers": self.max_workers,
            "queued": queued,
            "running": running,
            "completed": completed,
        }

    async def _worker_loop(self) -> None:
        while True:
            try:
                priority, seq, job_id, command, work_dir, meta = await self._queue.get()
                try:
                    await self.job_manager._execute(
                        job_id, command, work_dir, meta
                    )
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Queue worker error: %s", exc)

    async def shutdown(self) -> None:
        for t in self._worker_tasks:
            t.cancel()
        await asyncio.gather(*self._worker_tasks, return_exceptions=True)


class RayTaskQueue(BaseTaskQueue):
    """Ray-backed task queue stub (falls back to local if Ray is unavailable)."""

    def __init__(self, job_manager: "JobManager", max_workers: int = 2):
        self.job_manager = job_manager
        self.max_workers = max_workers
        try:
            import ray  # type: ignore

            self.ray = ray
            if not self.ray.is_initialized():
                self.ray.init(ignore_reinit_error=True)
            self._local = LocalTaskQueue(job_manager, max_workers)
            self._available = True
            logger.info("Ray task queue initialized")
        except Exception as exc:
            logger.warning("Ray backend unavailable (%s), falling back to local", exc)
            self._local = LocalTaskQueue(job_manager, max_workers)
            self._available = False

    async def submit(
        self,
        command: List[str],
        job_id: str,
        work_dir: Path,
        meta: dict,
        priority: int = 5,
    ) -> None:
        await self._local.submit(command, job_id, work_dir, meta, priority)

    def stats(self) -> Dict[str, Any]:
        stats = self._local.stats()
        stats["backend"] = "ray" if self._available else "ray-fallback-local"
        return stats

    async def shutdown(self) -> None:
        await self._local.shutdown()


class CeleryTaskQueue(BaseTaskQueue):
    """Celery-backed task queue stub (falls back to local if Celery is unavailable)."""

    def __init__(self, job_manager: "JobManager", max_workers: int = 2):
        self.job_manager = job_manager
        self.max_workers = max_workers
        try:
            from celery import Celery  # type: ignore

            self.celery = Celery("mtm_dashboard")
            self._available = True
        except Exception as exc:
            logger.warning(
                "Celery backend unavailable (%s), falling back to local", exc
            )
            self._available = False
        self._local = LocalTaskQueue(job_manager, max_workers)

    async def submit(
        self,
        command: List[str],
        job_id: str,
        work_dir: Path,
        meta: dict,
        priority: int = 5,
    ) -> None:
        await self._local.submit(command, job_id, work_dir, meta, priority)

    def stats(self) -> Dict[str, Any]:
        stats = self._local.stats()
        stats["backend"] = "celery" if self._available else "celery-fallback-local"
        return stats

    async def shutdown(self) -> None:
        await self._local.shutdown()


def _make_queue(job_manager: "JobManager", backend: str, max_workers: int) -> BaseTaskQueue:
    backend = backend.lower()
    if backend == "ray":
        return RayTaskQueue(job_manager, max_workers)
    if backend == "celery":
        return CeleryTaskQueue(job_manager, max_workers)
    return LocalTaskQueue(job_manager, max_workers)


class JobManager:
    def __init__(
        self,
        work_root: Path,
        repo_root: Optional[Path] = None,
        max_workers: Optional[int] = None,
        backend: Optional[str] = None,
    ):
        self.work_root = Path(work_root)
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.repo_root = Path(repo_root) if repo_root else self.work_root.parent
        self.jobs: Dict[str, dict] = {}

        backend = backend or os.environ.get("MTM_QUEUE_BACKEND", "local")
        max_workers = max_workers or int(os.environ.get("MTM_QUEUE_WORKERS", "2"))
        self.queue = _make_queue(self, backend, max_workers)

    async def start(
        self,
        command: List[str],
        job_type: str,
        meta: dict,
        work_dir: Optional[Path] = None,
        priority: int = 5,
    ) -> str:
        job_id = str(uuid.uuid4())[:8]
        if work_dir is None:
            work_dir = self.work_root / job_id
        work_dir.mkdir(parents=True, exist_ok=True)

        log_path = work_dir / "stdout.log"
        err_path = work_dir / "stderr.log"
        meta_path = work_dir / "meta.json"

        meta_record = {
            "type": job_type,
            "created": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "command": command,
            **meta,
        }
        meta_path.write_text(json.dumps(meta_record, indent=2, default=str))

        self.jobs[job_id] = {
            "proc": None,
            "work_dir": work_dir,
            "log_path": log_path,
            "err_path": err_path,
            "meta": meta_record,
            "command": command,
            "status": "queued",
            "priority": priority,
            "seq": time.time(),
            "started": None,
            "finished": None,
            "returncode": None,
        }

        await self.queue.submit(command, job_id, work_dir, meta_record, priority)
        return job_id

    async def _execute(self, job_id: str, command: List[str], work_dir: Path, meta: dict):
        job = self.jobs.get(job_id)
        if not job or job.get("status") != "queued":
            return

        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(self.repo_root)
        if existing_pythonpath:
            env["PYTHONPATH"] += os.pathsep + existing_pythonpath

        try:
            with open(job["log_path"], "w") as out, open(job["err_path"], "w") as err:
                proc = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=out,
                    stderr=err,
                    cwd=str(self.repo_root),
                    env=env,
                    start_new_session=True,
                )
        except Exception as exc:
            logger.exception("Failed to start job %s: %s", job_id, exc)
            job["status"] = "error"
            job["finished"] = time.time()
            job["returncode"] = -1
            return

        job["proc"] = proc
        job["status"] = "running"
        job["started"] = time.time()

        returncode = await proc.wait()
        job["returncode"] = returncode
        job["status"] = "success" if returncode == 0 else "error"
        job["finished"] = time.time()

    def read_log(self, job_id: str, tail: Optional[int] = None) -> str:
        job = self.jobs.get(job_id)
        if not job:
            return ""
        out = job["log_path"].read_text(errors="replace") if job["log_path"].exists() else ""
        err = job["err_path"].read_text(errors="replace") if job["err_path"].exists() else ""
        text = out + "\n" + err
        if tail:
            lines = text.splitlines()
            return "\n".join(lines[-tail:])
        return text

    def read_metrics(self, job_id: str) -> Optional[dict]:
        """Read live training metrics if the job writes a live_metrics.json file."""
        job = self.jobs.get(job_id)
        if not job:
            return None
        metrics_path = Path(job["work_dir"]) / "live_metrics.json"
        if not metrics_path.exists():
            return None
        try:
            return json.loads(metrics_path.read_text())
        except Exception:
            return None

    def list_files(self, job_id: str) -> List[dict]:
        job = self.jobs.get(job_id)
        if not job:
            return []
        wd = Path(job["work_dir"])
        if not wd.exists():
            return []
        return [
            {"name": f.name, "size": f.stat().st_size}
            for f in sorted(wd.iterdir())
            if f.is_file()
        ]

    def read_file(self, job_id: str, name: str) -> Optional[str]:
        job = self.jobs.get(job_id)
        if not job:
            return None
        wd = Path(job["work_dir"]).resolve()
        target = (wd / name).resolve()
        if not str(target).startswith(str(wd)) or not target.exists():
            return None
        if target.suffix.lower() in {".pth", ".pt", ".bin", ".pickle", ".pkl"}:
            return None
        return target.read_text(errors="replace")

    def list_jobs(self) -> List[dict]:
        result = []
        for jid, job in self.jobs.items():
            result.append(self._to_summary(jid, job))
        return sorted(result, key=lambda x: x.get("created", ""), reverse=True)

    def get(self, job_id: str) -> Optional[dict]:
        job = self.jobs.get(job_id)
        if not job:
            return None
        return self._to_summary(job_id, job)

    def _queue_position(self, job_id: str, job: dict) -> Optional[int]:
        if job.get("status") != "queued":
            return None
        try:
            seq = float(job.get("seq", 0))
        except Exception:
            seq = 0
        position = 0
        for jid, j in self.jobs.items():
            if j.get("status") != "queued":
                continue
            try:
                other_seq = float(j.get("seq", 0))
            except Exception:
                other_seq = 0
            if other_seq < seq:
                position += 1
        return position

    def _to_summary(self, job_id: str, job: dict) -> dict:
        duration = None
        if job.get("started") and job.get("finished"):
            duration = round(job["finished"] - job["started"], 2)
        elif job.get("started"):
            duration = round(time.time() - job["started"], 2)

        return {
            "id": job_id,
            "type": job["meta"].get("type", job.get("type", "unknown")),
            "status": job["status"],
            "priority": job.get("priority", 5),
            "queue_position": self._queue_position(job_id, job),
            "command": " ".join(job["command"]),
            "created": job["meta"].get("created"),
            "started": job.get("started"),
            "finished": job.get("finished"),
            "duration_sec": duration,
            "returncode": job.get("returncode"),
            "work_dir": str(job["work_dir"]),
            "files": self.list_files(job_id),
            "meta": job["meta"],
        }

    async def stop(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job:
            return False
        if job["status"] == "running" and job.get("proc"):
            proc = job["proc"]
            try:
                proc.terminate()
                await asyncio.sleep(0.5)
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
            except Exception:
                pass
            job["status"] = "stopped"
            job["finished"] = time.time()
            return True
        if job["status"] == "queued":
            job["status"] = "stopped"
            job["finished"] = time.time()
            return True
        return False

    def delete(self, job_id: str):
        job = self.jobs.pop(job_id, None)
        if job and job["work_dir"].exists():
            shutil.rmtree(job["work_dir"], ignore_errors=True)
        return bool(job)

    def queue_stats(self) -> Dict[str, Any]:
        return self.queue.stats()

    async def shutdown(self):
        await self.queue.shutdown()
