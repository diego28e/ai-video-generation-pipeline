#!/usr/bin/env python3
"""Render a story to real video with Wan 2.2 TI2V-5B on a 24 GB GPU (L4 stopgap).

Replaces the retired Ken Burns path with ACTUAL video generation, sized to fit 24 GB.
Reads a v1.1/1.2 job JSON (real audio + character URLs; keep it gitignored in samples/).

Run on the VM (inside the venv; accept the Wan license + authenticate to HF first):
  # Quick representative slice of YOUR story (no re-authoring) — recommended first:
  .venv/bin/python scripts/render_wan5b.py --job samples/the_weight.json --max-seconds 30
  # Full ~5-min render (can take HOURS on an L4 — see notes printed at start):
  .venv/bin/python scripts/render_wan5b.py --job samples/the_weight.json
"""
from __future__ import annotations

import argparse
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
    ap = argparse.ArgumentParser(description="Render a story to real video with Wan 5B (24GB)")
    ap.add_argument("--job", required=True, help="path to a v1.1/1.2 job JSON (real URLs)")
    ap.add_argument("--work", default="./work", help="working dir for clips/output")
    ap.add_argument("--max-seconds", type=float, default=None, help="render only the first N seconds of the story")
    ap.add_argument("--max-scenes", type=int, default=None, help="render only the first N scenes")
    ap.add_argument("--width", type=int, default=832, help="snapped to a multiple of 16 (default 480p-ish)")
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--steps", type=int, default=30, help="fewer = faster, lower quality")
    ap.add_argument("--guidance", type=float, default=5.0)
    ap.add_argument("--use-reference", action="store_true",
                    help="feed the character reference as the I2V first frame (best-effort identity)")
    ap.add_argument("--no-offload", action="store_true",
                    help="full pipeline on GPU instead of CPU offload (only if it fits)")
    args = ap.parse_args()

    from app.generators.wan5b import Wan5BGenerator
    from app.models import JobRequest

    with open(args.job, encoding="utf-8") as f:
        job = JobRequest.model_validate_json(f.read())

    windows = job.scene_windows()
    n_total = len(windows)
    n_planned = n_total
    if args.max_scenes is not None:
        n_planned = min(n_planned, args.max_scenes)
    if args.max_seconds is not None:
        n_planned = min(n_planned, sum(1 for _, vs, _ in windows if vs < args.max_seconds))
    span = args.max_seconds if args.max_seconds else job.audio.duration_seconds

    print(f"==> job {job.job_id}: {n_total} scenes, audio {job.audio.duration_seconds:.1f}s")
    print(f"==> rendering {n_planned} scene(s) covering ~{span:.0f}s at {args.width}x{args.height}, "
          f"{args.steps} steps, offload={not args.no_offload}")
    print("    NOTE: Wan 5B is REAL video generation but lower fidelity than the 14B target.")
    print("    NOTE: the L4 is ~2-4x slower than a 4090; a FULL 5-min render can take several HOURS.")
    print("    Clips are checkpointed under work/<job_id>/clips/ — re-running resumes where it stopped.\n")

    gen = Wan5BGenerator(
        width=args.width, height=args.height, steps=args.steps, guidance=args.guidance,
        offload=not args.no_offload, use_reference=args.use_reference,
    )

    t_start = time.perf_counter()

    def on_scene(sequence: int, gpu_seconds: float) -> None:
        elapsed = time.perf_counter() - t_start
        print(f"  scene {sequence} clip ready ({gpu_seconds:.1f}s gpu, {elapsed/60:.1f} min elapsed)")

    out = gen.render_job(
        job, args.work, on_scene,
        max_seconds=args.max_seconds, max_scenes=args.max_scenes,
    )
    print(f"\n[OK] final video -> {out}  ({(time.perf_counter() - t_start)/60:.1f} min total)")


if __name__ == "__main__":
    main()
