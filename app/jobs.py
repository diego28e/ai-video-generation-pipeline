"""In-memory job registry + single-GPU serialized worker.

The LMS owns the durable queue (BullMQ + Postgres). Here we only need:
  - a one-at-a-time worker (single GPU),
  - per-job filesystem checkpoints for crash-resume (FR-9),
  - GPU-second accounting toward the budget,
  - outbound webhooks (scene/job/idle).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from . import checkpoints as cp
from .config import get_settings
from .gpu import gpu_status
from .models import JobRequest
from .webhooks import emit, emit_idle

log = logging.getLogger("engine.jobs")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    def __init__(self, generator) -> None:
        self.gen = generator
        self.settings = get_settings()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._records: dict[str, dict] = {}
        self._requests: dict[str, JobRequest] = {}
        self._current: Optional[str] = None
        self._cumulative_gpu_s: float = 0.0
        self._started = time.time()
        self._last_callback_url: Optional[str] = None
        self._worker: Optional[asyncio.Task] = None

    # ---- lifecycle ----
    def start(self) -> None:
        self._worker = asyncio.create_task(self._run(), name="render-worker")

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass

    # ---- public API ----
    async def submit(self, req: JobRequest) -> tuple[int, str]:
        """Returns (queue_position, kind) where kind in {new, existing, conflict}."""
        existing = self._requests.get(req.job_id)
        if existing is not None:
            if existing.model_dump() != req.model_dump():
                return self._records[req.job_id]["queue_position"], "conflict"
            return self._records[req.job_id]["queue_position"], "existing"

        position = self._queue.qsize() + (1 if self._current else 0)
        record = {
            "job_id": req.job_id,
            "status": "queued",
            "scenes_done": 0,
            "scenes_total": len(req.scenes),
            "error": None,
            "gpu_seconds_used": 0.0,
            "video_url": None,
            "queue_position": position,
        }
        self._records[req.job_id] = record
        self._requests[req.job_id] = req
        self._last_callback_url = req.callback.url
        cp.save_state(self.settings.work_dir, req.job_id, record)
        await self._queue.put(req.job_id)
        log.info("queued job %s (%d scenes, position %d)", req.job_id, record["scenes_total"], position)
        return position, "new"

    def record(self, job_id: str) -> Optional[dict]:
        return self._records.get(job_id)

    def status(self) -> dict:
        current = None
        if self._current:
            rec = self._records[self._current]
            current = {
                "job_id": self._current,
                "sequence": rec["scenes_done"],
                "scenes_total": rec["scenes_total"],
            }
        return {
            "state": "busy" if self._current else "idle",
            "current_job": current,
            "queue_depth": self._queue.qsize(),
            "gpu": gpu_status(),
            "cumulative_gpu_seconds": round(self._cumulative_gpu_s, 2),
            "gpu_budget_seconds": self.settings.gpu_budget_seconds,
            "uptime_seconds": round(time.time() - self._started, 1),
            "schema_version": self.settings.schema_version,
        }

    def progress(self, job_id: str) -> Optional[dict]:
        rec = self._records.get(job_id)
        if not rec:
            return None
        done, total = rec["scenes_done"], rec["scenes_total"]
        eta = None
        if rec["status"] == "rendering" and done > 0:
            per = rec["gpu_seconds_used"] / done
            eta = round(per * max(total - done, 0), 1)
        return {
            "job_id": job_id,
            "status": rec["status"],
            "scenes_done": done,
            "scenes_total": total,
            "eta_seconds": eta,
            "gpu_seconds_used": round(rec["gpu_seconds_used"], 2),
            "error": rec["error"],
            "video_url": rec["video_url"],
        }

    # ---- delivery helpers ----
    def _s3_key(self, req: JobRequest) -> str:
        return f"{req.output.key_prefix.rstrip('/')}/final.mp4"

    def _video_url(self, req: JobRequest) -> str:
        base = self.settings.cloudfront_base_url.rstrip("/")
        key = self._s3_key(req)
        return f"{base}/{key}" if base else f"s3://{req.output.bucket}/{key}"

    # ---- worker ----
    async def _run(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._process(job_id)
            except Exception:  # noqa: BLE001
                log.exception("unexpected error processing %s", job_id)
            finally:
                self._current = None
                self._queue.task_done()
            if self._queue.empty() and self._current is None:
                await emit_idle(
                    {
                        "queue_depth": 0,
                        "cumulative_gpu_seconds": round(self._cumulative_gpu_s, 2),
                        "idle_since": _now_iso(),
                    },
                    fallback_url=self._last_callback_url,
                )

    async def _process(self, job_id: str) -> None:
        req = self._requests[job_id]
        rec = self._records[job_id]
        self._current = job_id
        rec["status"] = "rendering"
        cp.save_state(self.settings.work_dir, job_id, rec)
        log.info("rendering job %s", job_id)

        try:
            for scene in req.ordered_scenes():
                if cp.scene_done(self.settings.work_dir, job_id, scene.sequence):
                    log.info("job %s scene %d already done (resume)", job_id, scene.sequence)
                    rec["scenes_done"] = max(rec["scenes_done"], scene.sequence)
                    continue
                gpu_s = await self.gen.render_scene(req, scene, self.settings.work_dir)
                self._cumulative_gpu_s += gpu_s
                rec["gpu_seconds_used"] += gpu_s
                rec["scenes_done"] += 1
                cp.mark_scene_done(self.settings.work_dir, job_id, scene.sequence)
                cp.save_state(self.settings.work_dir, job_id, rec)
                await emit(req, "scene_completed", {
                    "job_id": job_id, "sequence": scene.sequence, "scenes_total": rec["scenes_total"],
                })

            rec["status"] = "uploading"
            cp.save_state(self.settings.work_dir, job_id, rec)
            await self.gen.assemble(req, self.settings.work_dir)  # (real S3 upload arrives in Phase 6)

            rec["video_url"] = self._video_url(req)
            rec["status"] = "done"
            cp.save_state(self.settings.work_dir, job_id, rec)
            log.info("job %s done -> %s", job_id, rec["video_url"])
            await emit(req, "job_completed", {
                "job_id": job_id,
                "status": "done",
                "video_url": rec["video_url"],
                "s3_key": self._s3_key(req),
                "bucket": req.output.bucket,
                "duration_seconds": req.audio.duration_seconds,
                "gpu_seconds_used": round(rec["gpu_seconds_used"], 2),
            })
        except Exception as exc:  # noqa: BLE001
            rec["status"] = "failed"
            rec["error"] = str(exc)
            cp.save_state(self.settings.work_dir, job_id, rec)
            log.exception("job %s failed", job_id)
            await emit(req, "job_failed", {
                "job_id": job_id, "status": "failed", "error": str(exc), "scenes_done": rec["scenes_done"],
            })
