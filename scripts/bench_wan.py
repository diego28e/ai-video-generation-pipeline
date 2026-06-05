#!/usr/bin/env python3
"""
Direction v2 / Gate G2' — Wan video benchmark on the A100 (the stack-deciding gate).

Mirrors the old bench_svd.py, but for real video. Renders a clip with Wan 2.2 I2V
(14B) from a conditioning image, measures load/render time + peak VRAM, exports the
mp4, and extrapolates GPU-hours per 5-min video. Two modes:

  I2V (default): animate one image with a scene prompt.
      --image <path|url>            quick smoke
      --job samples/the_weight.json use the real character reference + scene-1 prompt
                                    (tests: does Wan keep the face while animating?)

  FLF2V (--flf2v): first+last-frame interpolation (the CONTINUOUS-mode lever).
      --image <first> --last-image <last>   (defaults to the FLF2V 14B 720P model)

VRAM note: on a 40GB A100 the 14B (MoE, two experts) is tight — offload is ON by
default. Try --no-offload to measure full-GPU speed if it fits.

Gated weights: accept the Wan licenses on Hugging Face + authenticate first
(export HF_TOKEN=<token>  or  hf auth login).

Run on the A100 VM (inside the venv):
    .venv/bin/python scripts/bench_wan.py --job samples/the_weight.json
    .venv/bin/python scripts/bench_wan.py --flf2v --image a.png --last-image b.png
"""
from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)   # for _env_guard
sys.path.insert(0, _ROOT)   # for `app`

from _env_guard import ensure_project_venv  # noqa: E402

I2V_MODEL = "Wan-AI/Wan2.2-I2V-A14B-Diffusers"
FLF2V_MODEL = "Wan-AI/Wan2.1-FLF2V-14B-720P-diffusers"
OUT_DIR = "outputs"
DEFAULT_NEGATIVE = (
    "bright tones, overexposed, static, blurred details, subtitles, worst quality, low quality, "
    "jpeg artifacts, ugly, deformed, disfigured, extra limbs, fused fingers, watermark, text"
)
RES = {"480p": 480 * 832, "720p": 720 * 1280}


def fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"\n[FAIL] {msg}")
    sys.exit(1)


def gpu_telemetry() -> str:
    query = "power.draw,power.limit,clocks.sm,clocks.max.sm,temperature.gpu,utilization.gpu"
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        vals = [v.strip() for v in out.stdout.strip().split(",")]
        keys = ["power_W", "power_limit_W", "sm_MHz", "sm_max_MHz", "temp_C", "util_%"]
        return "  ".join(f"{k}={v}" for k, v in zip(keys, vals))
    except Exception as exc:  # noqa: BLE001
        return f"(nvidia-smi unavailable: {exc})"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Wan video-stage benchmark (G2')")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--image", help="conditioning image (first frame): path or URL")
    src.add_argument("--job", help="v1.1/1.2 job JSON; uses scene-1 prompt + character-1 reference")
    p.add_argument("--last-image", help="last frame for --flf2v")
    p.add_argument("--prompt", help="override the motion prompt")
    p.add_argument("--flf2v", action="store_true", help="first-last-frame mode (CONTINUOUS lever)")
    p.add_argument("--model", help="override the Wan model id")
    p.add_argument("--resolution", choices=list(RES), default="480p")
    p.add_argument("--num-frames", type=int, default=81, help="Wan native default 81 (~5s @16fps)")
    p.add_argument("--fps", type=int, default=16)
    p.add_argument("--steps", type=int, default=40)
    p.add_argument("--guidance", type=float, default=5.0)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--no-offload", action="store_true", help="full pipeline on GPU (measure if 40GB fits)")
    p.add_argument("--runs", type=int, default=2, help="timed runs; reports the MIN")
    p.add_argument("--warmup", type=int, default=1)
    # Budget model:
    p.add_argument("--story-seconds", type=float, default=299.0)
    p.add_argument("--scenes", type=int, default=35, help="assumed shots per 5-min video")
    p.add_argument("--budget-hours", type=float, default=30.0)
    return p.parse_args()


def resolve_inputs(args):
    """Return (first_image_src, last_image_src_or_None, prompt)."""
    if args.job:
        from app.models import JobRequest

        with open(args.job, encoding="utf-8") as f:
            job = JobRequest.model_validate_json(f.read())
        if not job.scenes:
            fail("job has no scenes")
        prompt = args.prompt or job.scenes[0].keyframe_prompt
        if job.global_style:
            prompt = f"{prompt}, {job.global_style}".strip().rstrip(",")
        ref = None
        for c in job.characters:
            if c.primary_reference():
                ref = c.primary_reference()
                break
        if not ref and not args.image:
            fail("job has no character reference; pass --image explicitly")
        return (args.image or ref), args.last_image, prompt
    if not args.image:
        fail("provide --image <path|url> or --job <json>")
    prompt = args.prompt or (
        "cinematic film still in motion, slow push in, moody low-key lighting, 35mm, "
        "shallow depth of field, natural movement"
    )
    return args.image, args.last_image, prompt


def fit_resolution(image, pipe, max_area):
    import numpy as np

    ar = image.height / image.width
    mod = pipe.vae_scale_factor_spatial * pipe.transformer.config.patch_size[1]
    h = round(math.sqrt(max_area * ar)) // mod * mod
    w = round(math.sqrt(max_area / ar)) // mod * mod
    return image.resize((w, h)), int(h), int(w)


def main() -> None:
    ensure_project_venv()
    args = parse_args()
    first_src, last_src, prompt = resolve_inputs(args)
    if args.flf2v and not last_src:
        fail("--flf2v requires --last-image (or a second reference)")

    try:
        import torch
        from diffusers import AutoencoderKLWan, UniPCMultistepScheduler, WanImageToVideoPipeline
        from diffusers.utils import export_to_video, load_image
        from transformers import CLIPVisionModel
    except Exception as exc:  # noqa: BLE001
        fail(f"import failed (need diffusers>=0.35 for Wan): {exc!r}")

    if not torch.cuda.is_available():
        fail("CUDA not available; run scripts/verify_gpu.py first.")
    os.makedirs(OUT_DIR, exist_ok=True)

    model_id = args.model or (FLF2V_MODEL if args.flf2v else I2V_MODEL)
    flow_shift = 5.0 if args.resolution == "720p" else 3.0

    print(f"==> Loading {model_id} (bf16). First run downloads many GB.")
    print("    Gated: accept the license on HF + authenticate (HF_TOKEN / hf auth login) if it 401s.")
    t_load = time.perf_counter()
    try:
        vae = AutoencoderKLWan.from_pretrained(model_id, subfolder="vae", torch_dtype=torch.float32)
        kwargs = {"vae": vae, "torch_dtype": torch.bfloat16}
        try:
            kwargs["image_encoder"] = CLIPVisionModel.from_pretrained(
                model_id, subfolder="image_encoder", torch_dtype=torch.float32
            )
        except Exception:  # noqa: BLE001
            pass  # some I2V variants ship no separate CLIP image_encoder
        pipe = WanImageToVideoPipeline.from_pretrained(model_id, **kwargs)
        pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config, flow_shift=flow_shift)
    except Exception as exc:  # noqa: BLE001
        fail(f"could not load Wan pipeline (gated/auth or version mismatch?): {exc!r}")

    if args.no_offload:
        pipe.to("cuda")
        print("    placement: full pipeline on cuda (no offload)")
    else:
        pipe.enable_model_cpu_offload()  # default: the 14B MoE is tight on 40GB
        print("    placement: model_cpu_offload (VRAM-safe)")
    print(f"    loaded in {time.perf_counter() - t_load:.1f}s")

    first = load_image(first_src)
    first, height, width = fit_resolution(first, pipe, RES[args.resolution])
    call = dict(
        image=first, prompt=prompt, negative_prompt=DEFAULT_NEGATIVE,
        height=height, width=width, num_frames=args.num_frames,
        num_inference_steps=args.steps, guidance_scale=args.guidance,
    )
    if args.flf2v:
        import torchvision.transforms.functional as TF

        last = load_image(last_src)
        if last.size != first.size:
            ratio = max(width / last.width, height / last.height)
            last = TF.center_crop(last.resize((round(last.width * ratio), round(last.height * ratio))),
                                  [height, width])
        call["last_image"] = last

    def render_once():
        gen = torch.Generator(device="cuda").manual_seed(args.seed)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        frames = pipe(generator=gen, **call).frames[0]
        torch.cuda.synchronize()
        return time.perf_counter() - t0, frames

    mode = "FLF2V" if args.flf2v else "I2V"
    print(f"==> {mode}: {args.num_frames} frames @ {args.fps}fps, {width}x{height}, {args.steps} steps")
    print(f"    prompt: {prompt[:90]}{'...' if len(prompt) > 90 else ''}")
    print(f"    GPU before: {gpu_telemetry()}")

    for w in range(args.warmup):
        wt, _ = render_once()
        print(f"    [warmup {w+1}/{args.warmup}] {wt:.1f}s   GPU: {gpu_telemetry()}")

    torch.cuda.reset_peak_memory_stats()
    times, frames = [], None
    for r in range(args.runs):
        dt, frames = render_once()
        times.append(dt)
        print(f"    [run {r+1}/{args.runs}] {dt:.1f}s   GPU: {gpu_telemetry()}")

    render_dt = min(times)
    peak = torch.cuda.max_memory_allocated() / (1024**3)
    out_mp4 = os.path.join(OUT_DIR, f"bench_wan_{mode.lower()}.mp4")
    export_to_video(frames, out_mp4, fps=args.fps)
    clip_seconds = args.num_frames / args.fps

    # --- Budget extrapolation (one clip + ~one anchor frame per shot) ---
    gpu_per_video = args.scenes * render_dt
    videos = (args.budget_hours * 3600.0) / gpu_per_video if gpu_per_video else 0

    print(f"\n=== Wan {mode} benchmark ===")
    print(f"render time / clip : {render_dt:.1f}s (best of {args.runs}; {min(times):.1f}-{max(times):.1f}s)")
    print(f"                     ({args.num_frames} frames @ {args.fps}fps = {clip_seconds:.2f}s of video)")
    print(f"peak VRAM          : {peak:.2f} GiB   (A100 40GB -> watch headroom)")
    print(f"saved              : {out_mp4}")
    print(f"\n=== Budget (story={args.story_seconds:.0f}s, ~{args.scenes} shots, budget={args.budget_hours:.0f}h) ===")
    print(f"~{gpu_per_video/3600:.2f} GPU-h/video  ->  ~{videos:.1f} videos / {args.budget_hours:.0f}h")
    print("\nJudge from the mp4: motion quality, identity hold (same face?), artifacts on our art style.")
    print("Compare I2V vs FLF2V, and 480p vs 720p, before locking the stack at G2'.")


if __name__ == "__main__":
    main()
