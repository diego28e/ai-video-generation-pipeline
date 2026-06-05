---
name: pivot-to-wan-video
description: Major direction change (2026-06-05) — abandon Ken Burns/SVD stills-with-zoom for real self-hosted Wan video generation with face-ID and last-frame chaining.
metadata:
  type: project
---

On 2026-06-05 Diego rejected the shipped output: the current pipeline (SDXL+IP-Adapter still per scene → Ken Burns pan/zoom → mux) produces "images with zoom" with terrible character consistency. SVD-XT was deliberately disabled in Phase 5 (warps painterly art), so no real video model is in the production path.

**Decision:** build **real generative video on self-hosted infra** (no commercial API). Target **Wan 2.2 (14B)** — open quality leader for human subjects, with the identity ecosystem (Phantom / VACE / ConsisID / Wan 2.7 R2V) for face-ID locking and **FLF2V + last-frame→next-clip chaining** for cross-clip continuity. Diego chose "upgrade to a face-ID model" for identity and is willing to upgrade the GPU.

**Why:** the stated #1 goal is recurring-character consistency + cinematic motion; the old stack delivered neither. Wan natively solves identity (video-level, not bolted onto a still) and continuity.

**How to apply:** L4 24GB is too compute-weak for Wan 14B at production scale (fits VRAM but ~minutes/clip) → plan a GCP GPU upgrade (A100-class: a2-highgpu-1g/A100-40GB recommended). The old ~30 GPU-h budget is void; re-baseline at a new benchmark gate on the REAL assets (production JSON has live URLs; the committed `samples/the_weight.template.json` is mock — save real one as gitignored `samples/the_weight.json`). The API contract + engine skeleton (Generator protocol, job lifecycle, checkpoints, webhooks, audio-as-master-clock) survive; only the generator internals (keyframe/kenburns/svd) get replaced. Verify Wan version (2.2 vs 2.7 R2V) and identity method from rendered footage before locking.

**Continuity Director (key design, 2026-06-05):** clips are NOT blindly last-frame-chained — cinema is mostly cuts, and chaining across a cut morphs. Three independent consistency axes: (1) character identity [always on, via face-ID], (2) world/location/style [per scene-group], (3) temporal motion [only continuous takes]. Three transition modes route conditioning: CONTINUOUS (chain last frame), CUT_SAME_SCENE (cached per-location establishing "location anchor" reused as reference, no pixel carryover), HARD_CUT (identity only). Mode decided 3-tier: explicit contract fields `scene_group_id`+`shot_relation` (authoritative, LMS/LLM fills) → heuristic (time gap, characters_present delta, prompt similarity) → default-to-cut + guardrail (downgrade bad `continue` to cut). All modes reduce to "produce conditioning frame(s) → Wan I2V/FLF2V". Full design in docs/CINEMATIC_PIPELINE.md; contract v1.2 in docs/API_CONTRACT.md.
