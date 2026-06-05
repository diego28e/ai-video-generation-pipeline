"""Wan 2.2 TI2V-5B generator — REAL video generation, sized for a 24 GB GPU (L4 stopgap).

This is the low-VRAM test path while the A100 quota for the 14B is pending. Per scene it
generates an actual Wan video clip (a diffusion-transformer video model — same class of tech
as Veo/Kling, just a smaller open model = lower fidelity), retimes it to the scene's exact
window, encodes it identically to every other clip, then concat + mux the narration.

API verified against the diffusers Wan docs + the Wan2.2-TI2V-5B model card (2026-06):
  - pipeline class: WanPipeline (image= optional -> I2V if given, else T2V)
  - num_frames must be 4k+1; native 121 @ 24 fps (~5 s); 720p = 1280x704
  - 24 GB needs enable_model_cpu_offload() (the 14B does NOT fit 24 GB at all)

NOT the final pipeline: no Continuity Director / face-ID / FLF2V yet (that's Phase C on the
A100). This exists to let you eyeball real motion on your story on the L4. Identity is best-
effort here (optional reference as the I2V first frame); real identity is the 14B + face-ID job.

Crash-resume: each scene clip is checkpointed under work_dir/<job_id>/clips/ and skipped if
present — important because a full 5-min render on the L4 can take hours.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from ..checkpoints import ensure_job_dir
from ..models import JobRequest
from .assemble import assemble
from .base import OnSceneCompleted

log = logging.getLogger("engine.wan5b")

MODEL_ID = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
DEFAULT_NEGATIVE = (
    "bright tones, overexposed, static, blurred details, subtitles, worst quality, low quality, "
    "jpeg artifacts, ugly, deformed, disfigured, extra limbs, fused fingers, watermark, text"
)


def _snap_4k1(n: int, lo: int = 25, hi: int = 121) -> int:
    """Wan requires num_frames == 4k+1. Clamp then snap down to the nearest valid count."""
    n = max(lo, min(hi, n))
    return ((n - 1) // 4) * 4 + 1


def _snap_dim(x: int, mod: int = 16) -> int:
    return max(mod, (x // mod) * mod)


def _scene_reference(job: JobRequest, scene) -> Optional[str]:
    by_id = {c.id: c for c in job.characters}
    for cid in scene.characters_present:
        c = by_id.get(cid)
        if c and c.primary_reference():
            return c.primary_reference()
    return None


class Wan5BGenerator:
    name = "wan5b"

    def __init__(
        self,
        *,
        width: int = 832,
        height: int = 480,
        fps: int = 24,
        steps: int = 30,
        guidance: float = 5.0,
        offload: bool = True,
        use_reference: bool = False,
        model_id: str = MODEL_ID,
    ) -> None:
        self.width = _snap_dim(width)
        self.height = _snap_dim(height)
        self.fps = fps
        self.steps = steps
        self.guidance = guidance
        self.offload = offload
        self.use_reference = use_reference
        self.model_id = model_id
        self._pipe = None
        self._ref_cache: dict[str, object] = {}

    def _ensure_pipe(self):
        if self._pipe is not None:
            return self._pipe
        import torch
        from diffusers import AutoencoderKLWan, UniPCMultistepScheduler, WanPipeline

        t0 = time.perf_counter()
        vae = AutoencoderKLWan.from_pretrained(self.model_id, subfolder="vae", torch_dtype=torch.float32)
        pipe = WanPipeline.from_pretrained(self.model_id, vae=vae, torch_dtype=torch.bfloat16)
        flow_shift = 5.0 if max(self.width, self.height) >= 1280 else 3.0
        pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config, flow_shift=flow_shift)
        if self.offload:
            pipe.enable_model_cpu_offload()  # required on 24 GB
        else:
            pipe.to("cuda")
        # Decode-time VRAM relief (safe no-ops if unavailable on this diffusers build).
        for fn in ("enable_vae_tiling", "enable_vae_slicing"):
            try:
                getattr(pipe.vae, fn)()
            except Exception:  # noqa: BLE001
                pass
        self._pipe = pipe
        log.info("Wan5B pipeline loaded in %.1fs (%dx%d, offload=%s)",
                 time.perf_counter() - t0, self.width, self.height, self.offload)
        return pipe

    def _reference(self, url: str):
        if url not in self._ref_cache:
            from diffusers.utils import load_image

            self._ref_cache[url] = load_image(url).resize((self.width, self.height))
        return self._ref_cache[url]

    def _encode_clip(self, frames, target_frames: int, out_path: str) -> None:
        """Resample the generated frames to exactly target_frames and encode at self.fps.
        Identical codec/fps/size across clips so assemble() can concat with -c copy."""
        import imageio.v2 as imageio
        import numpy as np

        n = len(frames)
        # nearest-index map: duplicates (slow) if target>n, drops (fast) if target<n.
        idx = [min(n - 1, round(i * (n - 1) / max(1, target_frames - 1))) for i in range(target_frames)]
        writer = imageio.get_writer(
            out_path, fps=self.fps, codec="libx264", quality=7,
            pixelformat="yuv420p", macro_block_size=16,
        )
        try:
            for j in idx:
                writer.append_data(np.asarray(frames[j]))
        finally:
            writer.close()

    def _generate_scene(self, job: JobRequest, scene, duration: float, out_path: str) -> float:
        import torch

        pipe = self._ensure_pipe()
        target_frames = max(1, round(duration * self.fps))
        gen_frames = _snap_4k1(target_frames)

        prompt = scene.keyframe_prompt
        if job.global_style:
            prompt = f"{prompt}, {job.global_style}".strip().rstrip(",")

        kwargs = dict(
            prompt=prompt,
            negative_prompt=scene.negative_prompt or DEFAULT_NEGATIVE,
            height=self.height,
            width=self.width,
            num_frames=gen_frames,
            num_inference_steps=self.steps,
            guidance_scale=self.guidance,
        )
        ref = _scene_reference(job, scene) if self.use_reference else None
        if ref:
            kwargs["image"] = self._reference(ref)  # -> I2V (first frame = character reference)

        seed = scene.seed if scene.seed is not None else int.from_bytes(os.urandom(4), "big")
        generator = torch.Generator(device="cuda").manual_seed(seed)

        t0 = time.perf_counter()
        out = pipe(generator=generator, **kwargs).frames[0]
        gpu_seconds = time.perf_counter() - t0

        self._encode_clip(out, target_frames, out_path)
        log.info("scene %d: %d->%d frames, %.1fs gpu, seed=%s ref=%s",
                 scene.sequence, gen_frames, target_frames, gpu_seconds, seed, bool(ref))
        return gpu_seconds

    def render_job(
        self,
        job: JobRequest,
        work_dir: str,
        on_scene_completed: OnSceneCompleted,
        *,
        max_seconds: Optional[float] = None,
        max_scenes: Optional[int] = None,
    ) -> str:
        """Synchronous render (call from a thread/asyncio.to_thread if needed).
        max_seconds / max_scenes render only the first slice of the story (no re-authoring)."""
        import asyncio

        jdir = ensure_job_dir(work_dir, job.job_id)
        clip_dir = os.path.join(jdir, "clips")
        os.makedirs(clip_dir, exist_ok=True)

        clips: list[str] = []
        rendered_seconds = 0.0
        count = 0
        for scene, v_start, v_end in job.scene_windows():
            if max_seconds is not None and v_start >= max_seconds:
                break
            if max_scenes is not None and count >= max_scenes:
                break
            end = min(v_end, max_seconds) if max_seconds is not None else v_end
            duration = end - v_start
            if duration <= 0:
                continue

            clip_path = os.path.join(clip_dir, f"scene_{scene.sequence:03d}.mp4")
            gpu_seconds = 0.0
            if not os.path.exists(clip_path):
                gpu_seconds = self._generate_scene(job, scene, duration, clip_path)

            clips.append(clip_path)
            rendered_seconds += max(1, round(duration * self.fps)) / self.fps
            count += 1
            res = on_scene_completed(scene.sequence, gpu_seconds)
            if asyncio.iscoroutine(res):  # support async callbacks too
                asyncio.get_event_loop().run_until_complete(res)

        if not clips:
            raise RuntimeError("no scenes rendered (check max_seconds/max_scenes)")

        final_path = os.path.join(jdir, "final.mp4")
        partial = max_seconds is not None or max_scenes is not None
        assemble(clips, job.audio.url, final_path, jdir,
                 trim_seconds=rendered_seconds if partial else None)
        self._pipe = None
        return final_path
