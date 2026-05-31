#!/usr/bin/env python3
"""
Phase 2 / Gate G2 step 2c — identity-consistency spot check.

The #1 goal is recurring-character identity. Since SVD-XT only animates a still,
identity is decided entirely at the KEYFRAME stage. This places ONE full-appearance
character reference image into several different scenes via IP-Adapter (SDXL) and
saves the keyframes so you can eyeball whether the SAME character persists.

Run on the VM (inside the venv):
    .venv/bin/python scripts/bench_identity.py --reference <URL-or-path-to-character.png>

Example with your LMS character asset:
    .venv/bin/python scripts/bench_identity.py \
        --reference https://d35ivcpjrjjgk.cloudfront.net/lesson-content/Stories-podcast/the-weight/<char>.png
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _env_guard import ensure_project_venv  # noqa: E402

MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
OUT_DIR = os.path.join("outputs", "identity")
W, H = 1024, 576

# IP-Adapter variants for SDXL. 'base' is the most robust default in diffusers
# (pairs with the ViT-bigG encoder under sdxl_models/image_encoder).
ADAPTERS = {
    "base": ("sdxl_models", "ip-adapter_sdxl.bin"),
    "plus": ("sdxl_models", "ip-adapter-plus_sdxl_vit-h.safetensors"),
}


def fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"\n[FAIL] {msg}")
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Identity-consistency spot check (SDXL + IP-Adapter)")
    p.add_argument("--reference", required=True, help="character reference image (URL or local path)")
    p.add_argument("--subject", default="a young boy", help="neutral subject token; IP-Adapter supplies the look")
    p.add_argument("--adapter", choices=list(ADAPTERS), default="base")
    p.add_argument("--scale", type=float, default=0.7, help="IP-Adapter strength (0..1); higher = stronger identity")
    p.add_argument("--steps", type=int, default=30)
    p.add_argument("--seed", type=int, default=1000)
    p.add_argument(
        "--style", default="cinematic 35mm film, moody low-key lighting, shallow depth of field, hyper-realistic",
        help="global style applied to every scene (world/style consistency)",
    )
    return p.parse_args()


def main() -> None:
    ensure_project_venv()
    args = parse_args()

    try:
        import torch
        from diffusers import StableDiffusionXLPipeline
        from diffusers.utils import load_image
    except Exception as exc:  # noqa: BLE001
        fail(f"import failed (torch/diffusers): {exc!r}")

    if not torch.cuda.is_available():
        fail("CUDA not available; run scripts/verify_gpu.py first.")

    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"==> Loading reference image: {args.reference}")
    try:
        ref = load_image(args.reference)  # handles URL or local path
    except Exception as exc:  # noqa: BLE001
        fail(f"could not load reference image: {exc!r}")

    print(f"==> Loading {MODEL_ID} (fp16) on cuda (no offload)")
    pipe = StableDiffusionXLPipeline.from_pretrained(
        MODEL_ID, torch_dtype=torch.float16, variant="fp16", use_safetensors=True
    )
    pipe.to("cuda")

    subfolder, weight_name = ADAPTERS[args.adapter]
    print(f"==> Loading IP-Adapter '{args.adapter}' ({weight_name})")
    try:
        pipe.load_ip_adapter("h94/IP-Adapter", subfolder=subfolder, weight_name=weight_name)
    except Exception as exc:  # noqa: BLE001
        fail(f"could not load IP-Adapter (try --adapter base): {exc!r}")
    pipe.set_ip_adapter_scale(args.scale)

    # Same character, three different story-flavored settings.
    scenes = [
        f"{args.subject} standing on an empty city street at midnight, wet asphalt, neon reflections, wide shot",
        f"{args.subject} walking through a dark park at night, seen from behind",
        f"{args.subject} inside a dim red-lit stairwell of an old building, eerie atmosphere",
    ]
    negative = "blurry, deformed, extra limbs, text, watermark, low quality"

    print(f"==> Generating {len(scenes)} keyframes with the SAME reference (scale={args.scale})")
    torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    for i, scene in enumerate(scenes, start=1):
        generator = torch.Generator(device="cuda").manual_seed(args.seed + i)
        image = pipe(
            prompt=f"{scene}, {args.style}",
            negative_prompt=negative,
            ip_adapter_image=ref,
            width=W, height=H,
            num_inference_steps=args.steps,
            generator=generator,
        ).images[0]
        path = os.path.join(OUT_DIR, f"scene_{i:02d}.png")
        image.save(path)
        print(f"    scene {i}: {path}")
    dt = time.perf_counter() - t0
    peak = torch.cuda.max_memory_allocated() / (1024**3)

    print("\n=== Identity spot-check result ===")
    print(f"keyframes          : {len(scenes)} in {dt:.1f}s ({dt/len(scenes):.1f}s each)")
    print(f"peak VRAM          : {peak:.2f} GiB")
    print(f"output dir         : {OUT_DIR}")
    print("\nNow EYEBALL the images: is it recognizably the SAME character across all three?")
    print("- Too generic / drifting?  raise --scale (e.g. 0.85) or try --adapter plus.")
    print("- Looks like the ref but ignores the scene?  lower --scale (e.g. 0.5).")


if __name__ == "__main__":
    main()
