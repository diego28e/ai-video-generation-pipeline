#!/usr/bin/env python3
"""Render a full job to a final .mp4 offline (no HTTP/LMS) — Phase 5 verification.

Runs the real CinematicGenerator: SDXL+IP-Adapter keyframe -> Ken Burns fill -> ffmpeg mux.
Reads a v1.1 job JSON (with REAL audio + character URLs; keep it in gitignored samples/).

Run on the VM (inside the venv):
  cp samples/the_weight.template.json samples/the_weight.json   # then fill in real URLs
  .venv/bin/python scripts/render_job.py --job samples/the_weight.json
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)   # for _env_guard
sys.path.insert(0, _ROOT)   # for `app`

from _env_guard import ensure_project_venv  # noqa: E402


def main() -> None:
    ensure_project_venv()
    ap = argparse.ArgumentParser(description="Render a job to final.mp4 (offline)")
    ap.add_argument("--job", required=True, help="path to a v1.1 job JSON (real URLs)")
    ap.add_argument("--work", default="./work", help="working dir for keyframes/clips/output")
    args = ap.parse_args()

    from app.config import get_settings
    from app.generators.cinematic import CinematicGenerator
    from app.models import JobRequest

    with open(args.job, encoding="utf-8") as f:
        job = JobRequest.model_validate_json(f.read())
    print(f"==> job {job.job_id}: {len(job.scenes)} scenes, audio {job.audio.duration_seconds:.1f}s")

    gen = CinematicGenerator(get_settings())

    async def on_scene(sequence: int, gpu_seconds: float) -> None:
        print(f"  scene {sequence} clip ready ({gpu_seconds:.1f}s gpu)")

    async def run() -> None:
        t0 = time.perf_counter()
        out = await gen.render_job(job, args.work, on_scene)
        print(f"\n[OK] final video -> {out}  ({time.perf_counter() - t0:.1f}s total)")

    asyncio.run(run())


if __name__ == "__main__":
    main()
