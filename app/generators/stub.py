"""No-GPU stub generator for Phase 3 / Gate G3.

Simulates render time and writes placeholder artifacts so the whole queue ->
checkpoint -> webhook -> assemble flow can be exercised end-to-end without a GPU.
"""
from __future__ import annotations

import asyncio
import os
import time

from ..models import JobRequest, Scene


class StubGenerator:
    name = "stub"

    def __init__(self, scene_seconds: float = 0.2) -> None:
        self.scene_seconds = scene_seconds

    async def render_scene(self, job: JobRequest, scene: Scene, work_dir: str) -> float:
        from ..checkpoints import ensure_job_dir

        t0 = time.perf_counter()
        await asyncio.sleep(self.scene_seconds)  # stand-in for keyframe + clip + fill
        d = ensure_job_dir(work_dir, job.job_id)
        with open(os.path.join(d, f"scene_{scene.sequence:03d}.txt"), "w", encoding="utf-8") as f:
            f.write(
                f"[stub] scene {scene.sequence} "
                f"({scene.start_seconds:.2f}-{scene.end_seconds:.2f}s, motion={scene.camera_motion})\n"
                f"prompt: {scene.keyframe_prompt[:120]}\n"
                f"characters: {', '.join(scene.characters_present) or '(none)'}\n"
            )
        return time.perf_counter() - t0

    async def assemble(self, job: JobRequest, work_dir: str) -> str:
        from ..checkpoints import ensure_job_dir

        d = ensure_job_dir(work_dir, job.job_id)
        out = os.path.join(d, "final.mp4")
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"[stub] assembled {len(job.scenes)} scenes; audio={job.audio.url}")
        return out
