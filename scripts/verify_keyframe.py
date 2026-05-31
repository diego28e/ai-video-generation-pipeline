#!/usr/bin/env python3
"""
Phase 1 / Gate G1 (part 2) — end-to-end keyframe generation smoke test.

Generates ONE 1024x576 cinematic keyframe with SDXL in fp16 to prove the full
diffusers path works on the L4, and prints timing + peak VRAM. The timing here
is an EARLY signal for the G2 budget math (per-keyframe seconds), not the final
benchmark.

First run downloads SDXL base weights (~7 GB) to the HF cache.

Run on the VM:  python scripts/verify_keyframe.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _env_guard import ensure_project_venv  # noqa: E402

OUT_DIR = "outputs"
OUT_PATH = os.path.join(OUT_DIR, "g1_keyframe.png")
MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
WIDTH, HEIGHT = 1024, 576  # cinematic 16:9
SEED = 1234


def fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"\n[FAIL] {msg}")
    sys.exit(1)


def main() -> None:
    ensure_project_venv()
    try:
        import torch
        from diffusers import StableDiffusionXLPipeline
    except Exception as exc:  # noqa: BLE001
        fail(f"import failed (torch/diffusers): {exc!r}")

    if not torch.cuda.is_available():
        fail("CUDA not available; run scripts/verify_gpu.py first.")

    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"==> Loading {MODEL_ID} (fp16). First run downloads ~7GB...")
    t_load = time.perf_counter()
    pipe = StableDiffusionXLPipeline.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.float16,
        variant="fp16",
        use_safetensors=True,
    )
    # VRAM-safe on the 24GB L4 (NFR-3). cpu offload trades a little speed for headroom.
    pipe.enable_model_cpu_offload()
    print(f"    loaded in {time.perf_counter() - t_load:.1f}s")

    prompt = (
        "cinematic wide shot, an empty city street past midnight, wet asphalt, "
        "a small park to one side, moody low-key lighting, 35mm film, "
        "shallow depth of field, hyper-realistic"
    )
    negative = "blurry, deformed, text, watermark, low quality"

    generator = torch.Generator(device="cuda").manual_seed(SEED)

    print("==> Generating 1 keyframe (30 steps, 1024x576)...")
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    image = pipe(
        prompt=prompt,
        negative_prompt=negative,
        width=WIDTH,
        height=HEIGHT,
        num_inference_steps=30,
        generator=generator,
    ).images[0]
    torch.cuda.synchronize()
    dt = time.perf_counter() - t0

    peak = torch.cuda.max_memory_allocated() / (1024**3)
    image.save(OUT_PATH)

    print("\n=== G1 keyframe result ===")
    print(f"render time        : {dt:.1f}s  (seed={SEED})")
    print(f"peak VRAM          : {peak:.2f} GiB")
    print(f"saved              : {OUT_PATH}")
    print("\n[OK] Keyframe generation passed. Inspect the image, then we can")
    print("     proceed to the G2 model-evaluation benchmark.")


if __name__ == "__main__":
    main()
