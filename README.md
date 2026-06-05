# Cinematic GenAI Video Pipeline (GCP Compute Engine)

GPU-backed Python service that turns a **structured scene script** into a **cinematic short video (~5 min)** with a strong emphasis on **recurring-character identity consistency**.

This repository is the **GCP video-generation engine only**. The orchestrating LMS backend (Nest.js, AWS) is a separate system; this repo defines and honors a contract it can call. See [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md).

## What this is / is not

- **Is:** an async, single-GPU render engine (FastAPI) that accepts scene jobs, generates identity-consistent keyframes, animates them into clips, assembles an `.mp4`, **muxes the supplied ElevenLabs audio** so total length matches the narration exactly, uploads to the `ocw-lesson-content` S3 bucket, and calls back the orchestrator with the CloudFront URL.
- **Is not:** the LLM story-to-scene parser or the audio generator (both live upstream — ElevenLabs already produced the narration + timestamps; Nest.js maps timestamps to per-scene windows). This engine illustrates existing audio; it does not create or re-time it.

## Hard constraints driving the design

- **GPU budget: ~30 hours total; immediate goal ≥3 finished 5-min videos.** With ~10 GPU-h/video of headroom, the binding constraint is now **consistency/quality, not speed.** We benchmark before we build at scale.
- **Single GPU** (1× NVIDIA L4, 24 GB VRAM today; possibly V100 later). Jobs are serialized.
- **Cross-cloud:** orchestrator on AWS, engine on GCP. Results go straight to AWS S3 to avoid egress friction.

## Status

**⚠️ Direction v2 (2026-06-05) — pivoting to real video.** A test render exposed that the Phase 4–5
pipeline produced *animated stills* (SDXL still → Ken Burns pan/zoom), not video, with poor
character consistency. We are moving to **real self-hosted video generation (Wan 2.2)** with a
**Continuity Director** (cuts vs. continuous takes) and **video-native face-ID**, on an upgraded
A100-class GPU. **New source of truth:** [`docs/CINEMATIC_PIPELINE.md`](docs/CINEMATIC_PIPELINE.md)
(architecture + the prerequisites checklist). Re-phased plan (Phases A–D) in
[`docs/ROADMAP.md`](docs/ROADMAP.md).

**What stands:** Phase 0–3 — the FastAPI engine (`app/`) runs the full job → progress → webhook →
idle loop against a stub generator, verified end-to-end with no GPU ([`docs/ENGINE.md`](docs/ENGINE.md));
the swappable `Generator` protocol, contract, checkpoints, and audio-as-master-clock all survive.

**Retired (Direction v1):** `keyframe.py` (SDXL+IP-Adapter as the identity mechanism),
`kenburns.py` (pan/zoom fill), and the SVD-XT A/B path. `assemble.py` (concat + audio mux) is reused.

## Key documents

| Doc | Purpose |
|-----|---------|
| [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) | Revised functional + non-functional requirements (the source of truth). |
| [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) | The HTTP contract Nest.js implements against this engine. |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phased implementation plan with verification gates. |
