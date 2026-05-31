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

**Phase 3 complete — engine skeleton (G3 passed).** Stack locked at G2 (SDXL+IP-Adapter → SVD-XT;
~5.6 GPU-h for 3 videos; identity greenlit). The FastAPI engine (`app/`) runs the full
job → progress → webhook → idle loop against a stub generator — verified end-to-end with no GPU (see [`docs/ENGINE.md`](docs/ENGINE.md)).

**Phase 4–5 built — the full render pipeline (Stages A–C):** identity-locked SDXL+IP-Adapter
keyframes ([`keyframe.py`](app/generators/keyframe.py)) → Ken Burns fill to each scene's exact
duration ([`kenburns.py`](app/generators/kenburns.py)) → ffmpeg concat + audio mux
([`assemble.py`](app/generators/assemble.py)), tied together by `CinematicGenerator`
(`ENGINE_GENERATOR=cinematic`). SVD-XT animation is an A/B toggle, not baked in (painterly-art
artifacts). Stage C + the engine refactor verified locally; **render the real story on the VM** via
[`docs/PHASE5.md`](docs/PHASE5.md). **Next: Phase 6** — S3 upload + CloudFront URL + idle lifecycle.
Phases in [`docs/ROADMAP.md`](docs/ROADMAP.md); dev loop in [`docs/WORKFLOW.md`](docs/WORKFLOW.md).

## Key documents

| Doc | Purpose |
|-----|---------|
| [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) | Revised functional + non-functional requirements (the source of truth). |
| [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) | The HTTP contract Nest.js implements against this engine. |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phased implementation plan with verification gates. |
