# Cinematic GenAI Video Pipeline (GCP Compute Engine)

GPU-backed Python service that turns a **structured scene script** into a **cinematic short video (~5 min)** with a strong emphasis on **recurring-character identity consistency**.

This repository is the **GCP video-generation engine only**. The orchestrating LMS backend (Nest.js, AWS) is a separate system; this repo defines and honors a contract it can call. See [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md).

## What this is / is not

- **Is:** an async, single-GPU render engine (FastAPI) that accepts scene jobs, generates identity-consistent keyframes, animates them into clips, assembles an `.mp4`, uploads to S3, and calls back the orchestrator.
- **Is not:** the LLM story-to-scene parser (that lives in Nest.js), and — for now — not an audio/narration mixer (see open decisions in [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md)).

## Hard constraints driving the design

- **GPU budget: ~70 hours total.** Every design choice is measured against this. We benchmark before we build at scale.
- **Single GPU** (1× NVIDIA L4, 24 GB VRAM today; possibly V100 later). Jobs are serialized.
- **Cross-cloud:** orchestrator on AWS, engine on GCP. Results go straight to AWS S3 to avoid egress friction.

## Status

Phase 0 — Foundation. No runtime code yet. See [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Key documents

| Doc | Purpose |
|-----|---------|
| [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) | Revised functional + non-functional requirements (the source of truth). |
| [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) | The HTTP contract Nest.js implements against this engine. |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phased implementation plan with verification gates. |
