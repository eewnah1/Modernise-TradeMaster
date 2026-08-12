"""In-memory job manager for running RL experiments from the dashboard."""

import asyncio
import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


class JobManager:
    def __init__(self, work_root: Path, repo_root: Optional[Path] = None):
        self.work_root = Path(work_root)
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.repo_root = Path(repo_root) if repo_root else self.work_root.parent
        self.jobs: Dict[str, dict] = {}

    async def start(
        self,
        command: List[str],
        job_type: str,
        meta: dict,
        work_dir: Optional[Path] = None,
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

        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(self.repo_root)
        if existing_pythonpath:
            env["PYTHONPATH"] += os.pathsep + existing_pythonpath

        loop = asyncio.get_event_loop()
        with open(log_path, "w") as out, open(err_path, "w") as err:
            proc = await loop.run_in_executor(
                None,
                lambda: subprocess.Popen(
                    command,
                    stdout=out,
                    stderr=err,
                    cwd=str(self.repo_root),
                    env=env,
                    start_new_session=True,
                ),
            )

        self.jobs[job_id] = {
            "proc": proc,
            "work_dir": work_dir,
            "log_path": log_path,
            "err_path": err_path,
            "meta": meta_record,
            "command": command,
            "status": "running",
            "started": time.time(),
            "finished": None,
            "returncode": None,
        }

        asyncio.create_task(self._monitor(job_id))
        return job_id

    async def _monitor(self, job_id: str):
        job = self.jobs[job_id]
        proc = job["proc"]
        loop = asyncio.get_event_loop()
        returncode = await loop.run_in_executor(None, proc.wait)

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
        return sorted(result, key=lambda x: x["created"], reverse=True)

    def get(self, job_id: str) -> Optional[dict]:
        job = self.jobs.get(job_id)
        if not job:
            return None
        return self._to_summary(job_id, job)

    def _to_summary(self, job_id: str, job: dict) -> dict:
        return {
            "id": job_id,
            "type": job["meta"].get("type", job.get("type", "unknown")),
            "status": job["status"],
            "command": " ".join(job["command"]),
            "created": job["meta"].get("created"),
            "started": job["started"],
            "finished": job["finished"],
            "returncode": job["returncode"],
            "work_dir": str(job["work_dir"]),
            "files": self.list_files(job_id),
        }

    async def stop(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job or job["status"] != "running":
            return False
        proc = job["proc"]
        proc.terminate()
        await asyncio.sleep(0.5)
        if proc.poll() is None:
            proc.kill()
        job["status"] = "stopped"
        job["finished"] = time.time()
        return True

    def delete(self, job_id: str):
        job = self.jobs.pop(job_id, None)
        if job and job["work_dir"].exists():
            shutil.rmtree(job["work_dir"], ignore_errors=True)
        return bool(job)
