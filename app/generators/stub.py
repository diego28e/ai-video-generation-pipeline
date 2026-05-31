"""No-GPU stub generator for Phase 3 / Gate G3 (still used when ENGINE_GENERATOR=stub).

Exercises the whole queue -> checkpoint -> webhook -> assemble flow with no GPU.
"""
from __future__ import annotations

import asyncio
import os

from ..checkpoints import ensure_job_dir, scene_done
from ..models import JobRequest
from .base import OnSceneCompleted


class StubGenerator:
    name = "stub"

    def __init__(self, scene_seconds: float = 0.2) -> None:
        self.scene_seconds = scene_seconds

    async def render_job(self, job: JobRequest, work_dir: str, on_scene_completed: OnSceneCompleted) -> str:
        d = ensure_job_dir(work_dir, job.job_id)
        for s in job.ordered_scenes():
            if not scene_done(work_dir, job.job_id, s.sequence):
                await asyncio.sleep(self.scene_seconds)  # stand-in for keyframe + fill
                with open(os.path.join(d, f"scene_{s.sequence:03d}.txt"), "w", encoding="utf-8") as f:
                    f.write(
                        f"[stub] scene {s.sequence} ({s.start_seconds:.2f}-{s.end_seconds:.2f}s, "
                        f"motion={s.camera_motion})\nprompt: {s.keyframe_prompt[:120]}\n"
                    )
            await on_scene_completed(s.sequence, self.scene_seconds)

        out = os.path.join(d, "final.mp4")
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"[stub] assembled {len(job.scenes)} scenes; audio={job.audio.url}")
        return out
