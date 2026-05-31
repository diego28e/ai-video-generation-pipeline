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

Phase 2 — Model evaluation & benchmark. **G1 passed** (L4 / 22 GiB / CUDA 12.1; SDXL keyframe
15.6 s, 5.11 GiB). Now benchmarking the video stage + identity to lock the stack within the
~30 GPU-hour budget — see [`docs/BENCHMARK.md`](docs/BENCHMARK.md). Dev workflow in
[`docs/WORKFLOW.md`](docs/WORKFLOW.md); phases in [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Key documents

| Doc | Purpose |
|-----|---------|
| [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) | Revised functional + non-functional requirements (the source of truth). |
| [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) | The HTTP contract Nest.js implements against this engine. |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phased implementation plan with verification gates. |
