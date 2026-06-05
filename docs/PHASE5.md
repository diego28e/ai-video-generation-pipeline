# Phase 5 — Animation, duration-fill, assemble + audio mux (Stage B+C)

> **⚠️ SUPERSEDED (2026-06-05, Direction v2).** The Ken Burns / SVD approach described here is
> retired in favor of real Wan video. See [`CINEMATIC_PIPELINE.md`](CINEMATIC_PIPELINE.md) and the
> Phase A–D plan in [`ROADMAP.md`](ROADMAP.md). `assemble.py` (concat + audio mux) is the only part
> carried forward. Kept for the audit trail.

Turns identity-locked keyframes into the final, narration-synced `.mp4`.

**Decision (your call): Ken Burns by default, SVD as an A/B toggle.** SVD-XT warps painterly art and
costs ~172 s/clip; Ken Burns (slow pan/zoom on the static keyframe) gives the exact scene duration,
honors `camera_motion`, preserves the illustration style, and is near-free (CPU/ffmpeg).

## Pipeline (per job)
```
for each scene:  SDXL+IP-Adapter keyframe (GPU)  ->  Ken Burns clip to exact duration (CPU)
then:            concat scene clips  ->  fetch + mux narration audio  ->  final.mp4 (== audio length)
```
Only **SDXL** is resident on the GPU (Ken Burns is CPU), so no VRAM juggling. Keyframes + clips are
checkpointed under `WORK_DIR/<job_id>/` so a re-dispatched job resumes (FR-9).

## Modules
- `app/generators/kenburns.py` — pan/zoom fill (push_in/pull_out/pan_*/tilt_*/static), H.264.
- `app/generators/assemble.py` — ffmpeg concat + audio fetch + mux + exact length.
- `app/generators/cinematic.py` — `CinematicGenerator` (the real `render_job`).
- Engine selects it via `ENGINE_GENERATOR=cinematic` (default `stub`).
- `camera_motion` → Ken Burns direction; `motion_strength` (0..1) → pan/zoom amount.

## Verify on the VM (inside the venv)
ffmpeg is already installed (Phase 1 `install_system_deps.sh`).

**Easiest — render the real story offline (no HTTP):**
```bash
cp samples/the_weight.template.json samples/the_weight.json   # fill in REAL audio.url + the-boy ref url
.venv/bin/python scripts/render_job.py --job samples/the_weight.json
#   -> work/the-weight-local-test/final.mp4 (length == audio). Watch it.
```

**Through the engine (the production path):**
```bash
ENGINE_GENERATOR=cinematic .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# then POST a real v1.1 job (the LMS does this in production)
```

**SVD A/B (judge motion vs artifacts on a painterly keyframe):**
```bash
.venv/bin/python scripts/bench_svd.py --keyframe work/the-weight-local-test/keyframes/scene_002.png
#   -> outputs/bench_svd.mp4 — compare its motion to the Ken Burns clip; decide if SVD is worth integrating.
```

## What to report back
- Does `final.mp4` play start-to-finish, length == narration, visuals matching the story beats?
- Total render time + the per-scene keyframe GPU seconds (sanity vs ~7.5 s/keyframe).
- SVD A/B verdict: does SVD motion improve a painterly scene, or warp it?

## Verified locally (no GPU)
- Stage C end-to-end: Ken Burns clips → concat → mux produced a 1024×576 / 24 fps mp4 of the
  **exact** target duration with both audio+video streams.
- Engine G3 still green after the `render_job` refactor; checkpoint writes hardened against a
  transient Windows `os.replace` lock (no effect on Linux).
