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
| Model | Steps | Size | Placement | Render time | Peak VRAM |
|-------|-------|------|-----------|-------------|-----------|
| SDXL base 1.0 | 30 | 1024×576 | cpu offload | ~48 s | 5.1 GiB |
| SDXL base 1.0 (+IP-Adapter) | 30 | 1024×576 | **full GPU (`to('cuda')`)** | **7.5 s** | 12.9 GiB |

> **Key finding:** for SDXL, **full-GPU placement is ~6× faster** than `enable_model_cpu_offload()`
> (7.5 s vs ~48 s). Offload overhead dominates small models. → keyframe stage runs **without offload**.
> For SVD-XT (heavy), offload vs no-offload was only ~3% (177.7 s → 172.4 s), so it's a non-issue there.

### Video stage
| Model | Frames | fps | Clip len | Render time | Peak VRAM | Status |
|-------|--------|-----|----------|-------------|-----------|--------|
| SVD-XT (`stable-video-diffusion-img2vid-xt`), offload | 25 | 7 | ~3.57 s | **177.7 s** (best of 3, ±0.2 s) | **10.83 GiB** | ✅ **LOCKED** |
| SVD-XT, `--no-offload` | 25 | 7 | ~3.57 s | 172.4 s | 13.32 GiB | ~3% faster — offload not the bottleneck |
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

| Reference type | Adapter | Scale | Style used | Same character across 3 scenes? | Notes |
|---|---|---|---|---|---|
| `the-boy.png` (real LMS asset) | IP-Adapter base (sdxl) | 0.7 | cinematic (test default) | **_pending visual review_** | ran clean, 7.5 s/keyframe, 12.9 GiB |

⚠️ The test used the script's default **cinematic** style, but the real art direction is
**"Painterly storybook illustration, warm muted palette, 1950s small-town."** Re-run with the real
style for a true read: `--style "Painterly storybook illustration, warm muted palette, 1950s small-town"`.
Tuning: raise `--scale` (→0.85) / `--adapter plus` if identity drifts; lower (→0.5) if scenes are ignored.

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
