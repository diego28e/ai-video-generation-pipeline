# Phase 2 — Model Evaluation & Benchmark (Gate G2)

**Purpose:** lock the model stack with measured numbers — before we build the engine on top of it.
Verification-first: no stack is "chosen" until its numbers are in the table below.

**Updated target (2026-05-30):** budget is now **~30 GPU-hours**, goal **≥3 finished 5-min videos**.
That's ~10 GPU-h/video of headroom, so **speed is no longer the binding constraint — identity
consistency is.** We still record the SVD-XT speed number (cheap), but the priority shifts to the
identity spot-check (step 2c).

The pipeline has two GPU stages, benchmarked independently:
- **Keyframe stage** (identity + style) — the consistency lever.
- **Video stage** (image→video animation) — the cost driver for the budget.

---

## Recorded results

### Keyframe stage
| Model | Steps | Size | Render time | Peak VRAM | Notes |
|-------|-------|------|-------------|-----------|-------|
| SDXL base 1.0 | 30 | 1024×576 | **15.6 s / 48.2 s** | **5.11 GiB** | two cold runs varied 3.6× |

> **L4 power note:** the keyframe denoise loop measured 3.25 it/s once and 1.11 s/it another time
> — same code/model. The L4 is a **72 W** card; sustained clocks vary widely. **Lesson:** trust
> warmed-up, multi-run **minimums**, not single cold runs. `bench_svd.py` now does warmup + N runs
> and prints `nvidia-smi` power/clock each run so we can see throttling. Use `min` for planning.

### Video stage
| Model | Frames | fps | Clip len | Render time | Peak VRAM | Status |
|-------|--------|-----|----------|-------------|-----------|--------|
| SVD-XT (`stable-video-diffusion-img2vid-xt`), offload | 25 | 7 | ~3.57 s | **177.7 s** (best of 3, ±0.2 s) | **10.83 GiB** | ✅ **LOCKED** |
| SVD-XT, `--no-offload` | 25 | 7 | ~3.57 s | _pending A/B_ | _pending_ | expected faster (util was 45–56%) |
| LTX-Video (alternative) | — | — | — | _not run_ | — | not needed — budget already won on speed |

**Budget verdict (PASSED):** strategy B = **1.88 GPU-h/video** → 3 videos ≈ **5.6 GPU-h** vs the
~30 h budget (~5× headroom). Decision: **lock SVD-XT for the video stage.**

**GPU was starved, not throttled:** during render, `sm_MHz` sat at max (2040) and power at ~48/72 W
with **util ~45–56%** — classic CPU-offload bottleneck. `--no-offload` puts the full pipeline on the
22 GiB card (peak was only 10.83 GiB with offload) to reclaim the idle ~50%. This is an iteration-speed
optimization, not a budget requirement.

---

### Identity (step 2c) — the actual #1 goal
Approach: full-appearance reference image → **IP-Adapter (SDXL)** at the keyframe stage; SVD-XT then
animates the identity-locked keyframe. No new dependencies.

| Reference type | Adapter | Scale | Same character across 3 scenes? | Notes |
|---|---|---|---|---|
| full-body image | IP-Adapter base (sdxl) | 0.7 | _pending eyeball_ | run `scripts/bench_identity.py --reference <url>` |

Tuning: raise `--scale` (→0.85) or `--adapter plus` if identity drifts; lower it (→0.5) if scenes are ignored.

## How to run (on the VM, inside the venv)

```bash
mkdir -p outputs                 # safety; .gitkeep also ships the dir
# Video-stage baseline (SVD-XT). SVD-XT is GATED on HF — authenticate first:
hf auth login                    # (huggingface-cli is deprecated); or: export HF_TOKEN=<token>
# Defaults: 1 warmup + 3 timed runs, reports the MIN and prints GPU power/clock per run.
.venv/bin/python scripts/bench_svd.py | tee outputs/bench_svd.txt
```

```bash
# Identity spot-check (step 2c) — point it at your real character reference:
.venv/bin/python scripts/bench_identity.py --reference <url-or-path-to-character.png>
# then open outputs/identity/scene_01..03.png and judge consistency.
```

The SVD script prints render time, peak VRAM, and a budget extrapolation under two strategies:
- **A) back-to-back clips:** cover the full 299 s story with ~84 SVD clips (no fill).
- **B) audio-driven fill:** one keyframe + one clip per narration beat (~35), remaining beat
  duration filled cheaply (Ken Burns / interpolation, ~0 GPU). This is our intended approach.

---

## Decision criteria (how G2 closes)

1. **Budget:** does strategy B comfortably yield **≥3 videos within ~30 h**? (With the keyframe at
   15.6 s and the fill strategy, this is very likely yes even if SVD-XT is slow.) Only if SVD-XT
   somehow blows the budget do we benchmark **LTX-Video**.
2. **VRAM:** stays safely under 22 GiB with keyframe + video pipelines (offload as needed).
3. **Identity (next sub-step):** with an identity adapter on the keyframe stage, does a character
   stay recognizable across 3 scenes? (Separate identity benchmark — added after the video number.)

**G2 is closed when:** the chosen keyframe + video models have numbers in the tables above, the
budget math supports the required number of videos, and the identity spot-check passes.

> We benchmark the **provisioned baseline (SVD-XT) first** on purpose: it's the known-good stack,
> so its number is the anchor. We only spend GPU time on alternatives if the anchor falls short.
