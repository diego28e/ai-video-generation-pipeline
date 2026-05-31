#!/usr/bin/env python3
"""
Phase 2 / Gate G2 — video-stage benchmark: SVD-XT (the provisioned baseline).

Animates the G1 keyframe into one clip and measures the numbers that decide the
budget: load time, render time, peak VRAM, frames, and clip seconds. Then it
extrapolates GPU-hours per 5-min story and stories-per-budget under two strategies.

This is the BASELINE. We compare alternatives (e.g. LTX-Video) against these
numbers before locking the stack.

Run on the VM (inside the venv):
    .venv/bin/python scripts/bench_svd.py
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _env_guard import ensure_project_venv  # noqa: E402

MODEL_ID = "stabilityai/stable-video-diffusion-img2vid-xt"
OUT_DIR = "outputs"
DEFAULT_KEYFRAME = os.path.join(OUT_DIR, "g1_keyframe.png")
W, H = 1024, 576


def fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"\n[FAIL] {msg}")
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SVD-XT video-stage benchmark")
    p.add_argument("--keyframe", default=DEFAULT_KEYFRAME, help="input image (default: G1 keyframe)")
    p.add_argument("--num-frames", type=int, default=25)
    p.add_argument("--fps", type=int, default=7, help="playback fps for this clip")
    p.add_argument("--motion-bucket-id", type=int, default=127)
    p.add_argument("--noise-aug", type=float, default=0.02)
    p.add_argument("--decode-chunk-size", type=int, default=8, help="lower = less VRAM at decode")
    p.add_argument("--seed", type=int, default=42)
    # Budget model inputs:
    p.add_argument("--story-seconds", type=float, default=299.0, help="target video length")
    p.add_argument("--scenes", type=int, default=35, help="assumed narration beats for fill strategy")
    p.add_argument("--keyframe-seconds", type=float, default=15.6, help="measured SDXL keyframe time (G1)")
    p.add_argument("--budget-hours", type=float, default=30.0)
    return p.parse_args()


def main() -> None:
    ensure_project_venv()
    args = parse_args()

    if not os.path.exists(args.keyframe):
        fail(f"keyframe not found: {args.keyframe} — run scripts/verify_keyframe.py first.")

    try:
        import torch
        from diffusers import StableVideoDiffusionPipeline
        from diffusers.utils import load_image, export_to_video
    except Exception as exc:  # noqa: BLE001
        fail(f"import failed (torch/diffusers): {exc!r}")

    if not torch.cuda.is_available():
        fail("CUDA not available; run scripts/verify_gpu.py first.")

    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"==> Loading {MODEL_ID} (fp16). First run downloads several GB.")
    print("    NOTE: this model is GATED on Hugging Face. If the load fails with a 401/403,")
    print("    accept the license on its model page and authenticate:")
    print("      huggingface-cli login        (or)   export HF_TOKEN=<your token>")
    t_load = time.perf_counter()
    try:
        pipe = StableVideoDiffusionPipeline.from_pretrained(
            MODEL_ID, torch_dtype=torch.float16, variant="fp16"
        )
    except Exception as exc:  # noqa: BLE001
        fail(f"could not load SVD-XT (gated/auth?): {exc!r}")
    pipe.enable_model_cpu_offload()  # VRAM safety on the 24GB L4 (NFR-3)
    load_dt = time.perf_counter() - t_load
    print(f"    loaded in {load_dt:.1f}s")

    image = load_image(args.keyframe).resize((W, H))
    generator = torch.manual_seed(args.seed)

    print(f"==> Animating: {args.num_frames} frames, motion_bucket_id={args.motion_bucket_id}")
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    frames = pipe(
        image,
        num_frames=args.num_frames,
        fps=args.fps,
        motion_bucket_id=args.motion_bucket_id,
        noise_aug_strength=args.noise_aug,
        decode_chunk_size=args.decode_chunk_size,
        generator=generator,
    ).frames[0]
    torch.cuda.synchronize()
    render_dt = time.perf_counter() - t0
    peak = torch.cuda.max_memory_allocated() / (1024**3)

    out_mp4 = os.path.join(OUT_DIR, "bench_svd.mp4")
    export_to_video(frames, out_mp4, fps=args.fps)

    clip_seconds = args.num_frames / args.fps

    # --- Budget extrapolation ---
    # Strategy A (naive): cover the whole story with back-to-back SVD clips.
    clips_a = math.ceil(args.story_seconds / clip_seconds)
    gpu_a = clips_a * render_dt
    # Strategy B (audio-driven fill): one keyframe + one clip per narration beat,
    # remaining beat duration filled cheaply (Ken Burns / interpolation, ~0 GPU).
    gpu_b = args.scenes * (render_dt + args.keyframe_seconds)

    def per_budget(gpu_seconds_per_video: float) -> float:
        return (args.budget_hours * 3600.0) / gpu_seconds_per_video

    print("\n=== SVD-XT benchmark result ===")
    print(f"render time / clip : {render_dt:.1f}s   ({args.num_frames} frames @ {args.fps}fps = {clip_seconds:.2f}s clip)")
    print(f"peak VRAM          : {peak:.2f} GiB")
    print(f"model load time    : {load_dt:.1f}s (one-time per process)")
    print(f"saved              : {out_mp4}")
    print("\n=== Budget extrapolation (story={:.0f}s, budget={:.0f}h) ===".format(args.story_seconds, args.budget_hours))
    print(f"A) back-to-back clips : {clips_a} clips -> {gpu_a/3600:.2f} GPU-h/video -> ~{per_budget(gpu_a):.0f} videos / {args.budget_hours:.0f}h")
    print(f"B) audio-driven fill  : {args.scenes} scenes -> {gpu_b/3600:.2f} GPU-h/video -> ~{per_budget(gpu_b):.0f} videos / {args.budget_hours:.0f}h")
    print("\nReport render time + peak VRAM back. If B gives too few videos, we benchmark")
    print("a faster alternative (LTX-Video) before locking the stack.")


if __name__ == "__main__":
    main()
