"""Per-job filesystem checkpoints under WORK_DIR (crash-resume; see REQUIREMENTS FR-9)."""
from __future__ import annotations

import json
import os
from typing import Optional


def job_dir(work_dir: str, job_id: str) -> str:
    # job_id is a UUID/slug from the LMS; keep it filesystem-safe.
    safe = "".join(c for c in job_id if c.isalnum() or c in ("-", "_", "."))
    return os.path.join(work_dir, safe or "job")


def ensure_job_dir(work_dir: str, job_id: str) -> str:
    d = job_dir(work_dir, job_id)
    os.makedirs(d, exist_ok=True)
    return d


def save_state(work_dir: str, job_id: str, state: dict) -> None:
    d = ensure_job_dir(work_dir, job_id)
    tmp = os.path.join(d, "state.json.tmp")
    final = os.path.join(d, "state.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, final)  # atomic


def load_state(work_dir: str, job_id: str) -> Optional[dict]:
    p = os.path.join(job_dir(work_dir, job_id), "state.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None


def _done_marker(work_dir: str, job_id: str, sequence: int) -> str:
    return os.path.join(job_dir(work_dir, job_id), f"scene_{sequence:03d}.done")


def scene_done(work_dir: str, job_id: str, sequence: int) -> bool:
    return os.path.exists(_done_marker(work_dir, job_id, sequence))


def mark_scene_done(work_dir: str, job_id: str, sequence: int) -> None:
    open(_done_marker(work_dir, job_id, sequence), "w").close()
