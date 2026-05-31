"""CinematicGenerator (Phase 5) — the real pipeline behind the engine.

Per scene:  identity-locked keyframe (SDXL+IP-Adapter, GPU)  ->  Ken Burns fill to the
scene's exact duration (CPU).  Then concat all scene clips + mux the narration (ffmpeg).

Default path uses only SDXL on the GPU (Ken Burns is CPU), so there's no VRAM juggling.
SVD-XT animation is offered as a separate A/B tool (scripts/bench_svd.py --keyframe), not
baked into the assembled video — to avoid warping artifacts on painterly art.

Crash-resume (FR-9): keyframes and clips are written under work_dir/<job_id>/ and skipped
if they already exist.
"""
from __future__ import annotations

import asyncio
import logging
import os

from ..checkpoints import ensure_job_dir
from ..models import JobRequest, Scene
from .assemble import assemble
from .base import OnSceneCompleted
from .kenburns import render_scene_clip

log = logging.getLogger("engine.cinematic")


def _scene_reference(job: JobRequest, scene: Scene):
    by_id = {c.id: c for c in job.characters}
    for cid in scene.characters_present:
        c = by_id.get(cid)
        if c and c.primary_reference():
            return c.primary_reference()
    return None


class CinematicGenerator:
    name = "cinematic"

    def __init__(self, settings) -> None:
        self.settings = settings
        self.fps = settings.kenburns_fps
        self._keyframer = None  # lazy (loads torch/SDXL only when first used)

    def _ensure_keyframer(self):
        if self._keyframer is None:
            from .keyframe import KeyframeGenerator

            self._keyframer = KeyframeGenerator(
                adapter=self.settings.ip_adapter,
                scale=self.settings.ip_adapter_scale,
                steps=self.settings.sdxl_steps,
            )
        return self._keyframer

    async def render_job(self, job: JobRequest, work_dir: str, on_scene_completed: OnSceneCompleted) -> str:
        jdir = ensure_job_dir(work_dir, job.job_id)
        kf_dir = os.path.join(jdir, "keyframes")
        clip_dir = os.path.join(jdir, "clips")
        os.makedirs(kf_dir, exist_ok=True)
        os.makedirs(clip_dir, exist_ok=True)

        keyframer = self._ensure_keyframer()
        clips: list[str] = []

        for scene in job.ordered_scenes():
            kf_path = os.path.join(kf_dir, f"scene_{scene.sequence:03d}.png")
            clip_path = os.path.join(clip_dir, f"scene_{scene.sequence:03d}.mp4")
            gpu_seconds = 0.0

            if not os.path.exists(kf_path):
                meta = await asyncio.to_thread(
                    keyframer.generate,
                    prompt=scene.keyframe_prompt,
                    out_path=kf_path,
                    global_style=job.global_style,
                    negative_prompt=scene.negative_prompt,
                    reference_url=_scene_reference(job, scene),
                    seed=scene.seed,
                )
                gpu_seconds = meta["seconds"]
                log.info("scene %d keyframe: %.1fs seed=%s ref=%s",
                         scene.sequence, meta["seconds"], meta["seed"], meta["had_reference"])

            if not os.path.exists(clip_path):
                await asyncio.to_thread(
                    render_scene_clip,
                    kf_path, clip_path, scene.duration, self.fps, scene.camera_motion, scene.motion_strength,
                )

            clips.append(clip_path)
            await on_scene_completed(scene.sequence, gpu_seconds)

        final_path = os.path.join(jdir, "final.mp4")
        await asyncio.to_thread(assemble, clips, job.audio.url, final_path, jdir)
        # free the SDXL pipeline between jobs (keeps VRAM clean for the next job)
        self._keyframer = None
        return final_path
