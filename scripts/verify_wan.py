#!/usr/bin/env python3
"""
Direction v2 / Gate G1' — prove the Wan stack works on the A100.

Renders ONE short clip with the SMALL Wan 2.1 T2V 1.3B model (tiny download,
fits 40GB trivially) to confirm the install path end-to-end: diffusers Wan
pipeline -> bf16 transformer -> Wan VAE decode -> mp4 export. This is the cheap
install proof; the REAL target (Wan 2.2 I2V 14B + FLF2V + identity) is exercised
by scripts/bench_wan.py at Gate G2'.

First run downloads the 1.3B weights to the HF cache. Some Wan repos are gated:
authenticate first (export HF_TOKEN=<token>  or  hf auth login) and accept the
model license on Hugging Face.

Run on the A100 VM (inside the venv):
    .venv/bin/python scripts/verify_wan.py

L4 / 24GB stopgap (while A100 quota is pending): test motion with the low-VRAM 5B model
(the 14B does NOT fit 24GB). See docs/CINEMATIC_PIPELINE.md §9b:
    .venv/bin/python scripts/verify_wan.py --model Wan-AI/Wan2.2-TI2V-5B-Diffusers \
        --height 480 --width 832 --num-frames 49 --fps 24 --steps 25
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _env_guard import ensure_project_venv  # noqa: E402

OUT_DIR = "outputs"
OUT_PATH = os.path.join(OUT_DIR, "g1_wan.mp4")
DEFAULT_MODEL = "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"


def fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"\n[FAIL] {msg}")
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Wan install proof (G1')")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Wan T2V model id (default: small 1.3B)")
    p.add_argument("--num-frames", type=int, default=33, help="frames (kept low for a fast proof)")
    p.add_argument("--fps", type=int, default=16)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--width", type=int, default=832)
    p.add_argument("--steps", type=int, default=30)
    p.add_argument("--guidance", type=float, default=5.0)
    p.add_argument("--flow-shift", type=float, default=3.0, help="3.0 for 480p, 5.0 for 720p")
    p.add_argument("--seed", type=int, default=1234)
    return p.parse_args()


def main() -> None:
    ensure_project_venv()
    args = parse_args()

    try:
        import torch
        from diffusers import AutoencoderKLWan, UniPCMultistepScheduler, WanPipeline
        from diffusers.utils import export_to_video
    except Exception as exc:  # noqa: BLE001
        fail(f"import failed (torch/diffusers too old for Wan? need diffusers>=0.35): {exc!r}")

    if not torch.cuda.is_available():
        fail("CUDA not available; run scripts/verify_gpu.py first.")

    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"==> Loading {args.model} (bf16). First run downloads the weights.")
    print("    If this fails with 401/403, the model is gated: accept its license on")
    print("    Hugging Face and authenticate (export HF_TOKEN=<token>  or  hf auth login).")
    t_load = time.perf_counter()
    try:
        vae = AutoencoderKLWan.from_pretrained(args.model, subfolder="vae", torch_dtype=torch.float32)
        pipe = WanPipeline.from_pretrained(args.model, vae=vae, torch_dtype=torch.bfloat16)
        pipe.scheduler = UniPCMultistepScheduler.from_config(
            pipe.scheduler.config, flow_shift=args.flow_shift
        )
    except Exception as exc:  # noqa: BLE001
        fail(f"could not load Wan pipeline (gated/auth or version mismatch?): {exc!r}")
    pipe.to("cuda")  # 1.3B fits 40GB easily; the 14B benchmark handles offload separately
    print(f"    loaded in {time.perf_counter() - t_load:.1f}s")

    prompt = (
        "cinematic film still in motion, a small boy in an oversized grey coat walks down an "
        "empty city street past midnight, wet asphalt reflecting streetlights, slow push in, "
        "moody low-key lighting, 35mm, shallow depth of field"
    )
    negative = (
        "bright tones, overexposed, static, blurred details, subtitles, worst quality, low quality, "
        "jpeg artifacts, ugly, deformed, disfigured, extra limbs, fused fingers, watermark, text"
    )

    print(f"==> Generating 1 clip ({args.num_frames} frames @ {args.fps}fps, {args.width}x{args.height})...")
    generator = torch.Generator(device="cuda").manual_seed(args.seed)
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    frames = pipe(
        prompt=prompt,
        negative_prompt=negative,
        height=args.height,
        width=args.width,
        num_frames=args.num_frames,
        num_inference_steps=args.steps,
        guidance_scale=args.guidance,
        generator=generator,
    ).frames[0]
    torch.cuda.synchronize()
    dt = time.perf_counter() - t0
    peak = torch.cuda.max_memory_allocated() / (1024**3)

    export_to_video(frames, OUT_PATH, fps=args.fps)

    print("\n=== G1' Wan result ===")
    print(f"render time        : {dt:.1f}s  (seed={args.seed})")
    print(f"peak VRAM          : {peak:.2f} GiB")
    print(f"saved              : {OUT_PATH}  ({args.num_frames/args.fps:.2f}s of video)")
    print("\n[OK] Wan path works. Next: scripts/bench_wan.py for the real 14B I2V/FLF2V benchmark (G2').")


if __name__ == "__main__":
    main()
