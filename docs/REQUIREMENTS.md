# Requirements — Cinematic GenAI Video Pipeline (GCP Engine)

**Status:** Draft v1 (Phase 0) · **Owner:** Diego · **Last updated:** 2026-05-30

This document supersedes the original FRD. It records *what changed and why*, so the
reasoning is auditable. It is the source of truth; code follows this, not the reverse.

---

## 0. Changes from the original FRD (and why)

| # | Original FRD said | Revised | Why |
|---|---|---|---|
| 1 | `video_motion_prompt` steers motion | **Removed as a text driver.** Motion is controlled by model-specific parameters. | SVD-XT (and most current I2V models) take an **image**, not a text motion prompt. The field was unusable as written. |
| 2 | SDXL per-scene keyframes | **Identity-locked keyframe stage** (reference image + identity-preserving generation). | Recurring-character identity is the stated #1 goal; independent SDXL gens cannot deliver it. |
| 3 | Lock stack to SDXL + SVD-XT | **Swappable generator interface; stack chosen at the Phase 2 benchmark gate.** | The provisioned stack is weakest on consistency and may be too slow for the GPU-hour budget. Decision must be data-driven. |
| 4 | `--break-system-packages` (PEP 668 bypass) | **Virtual environment (venv) or container; no system-package writes.** | Reproducibility and snapshot safety. `python3-venv` is already installed. |
| 5 | FastAPI webhook listener (implies always-up server) | **Session-based always-on engine + busy/idle status + idle callback.** | The VM is off by default and GPU hours are scarce; orchestration must minimize idle GPU time. |
| 6 | `motion_bucket_id` (SVD-specific) in the contract | **Generalized `motion_strength` + `camera_motion`**, mapped per-model. | Keeps the public contract independent of the chosen model. |
| 7 | Render exactly 25 frames @ 8fps | **Per-scene `duration_seconds`; frames/fps derived from the chosen model.** | Different models have different native frame counts/fps; 8fps looks choppy. |
| 8 | (absent) | **GPU-hour accounting as a first-class feature.** | The GPU-hour budget is a hard ceiling and must be observable in real time. |
| 9 | (absent) | **Crash recovery / per-scene checkpointing.** | A failure at scene 80/96 must not waste ~3 GPU-hours of completed work. |
| 10 | Generate audio + video | **Audio already exists (ElevenLabs).** Engine generates *visuals only* and **muxes the supplied audio** into the final MP4. | The narration + transcript already live in the LMS; we only illustrate them. |
| 11 | Free-running clip count/length | **Audio is the master clock.** Each scene carries exact `start_seconds`/`end_seconds`; total video length == audio length exactly. | Visuals must line up with what the narrator is saying and not drift. |

---

## 0b. Current production target (as of 2026-05-30)

The GPU budget is now **~30 GPU-hours** (down from 70), and the immediate goal is **at least 3
finished ~5-min videos**. This *loosens* the per-video time pressure dramatically (~10 GPU-h/video
of headroom), so the binding constraint shifts from **speed** to **identity consistency &
quality**. Phase 2 prioritizes the identity benchmark accordingly; raw clip speed is secondary.

## 1. Goal & success criteria

**Goal:** Produce cinematic visuals that **illustrate an existing narrated audio track**
(ElevenLabs TTS, already in the LMS) for a ~5-minute short story, with **recurring characters
that remain visually identifiable across scenes** and a **consistent art style/world**. The
engine does **not** generate audio; it generates moving images and muxes the supplied audio.

**Definition of done (per video):**
- All scenes rendered and assembled into a single `.mp4`, with the **supplied audio muxed in**.
- **Total video length equals the audio length exactly**; each scene occupies its assigned
  `start_seconds`/`end_seconds` window so visuals match what is being narrated.
- Named characters are recognizably the same person across the scenes they appear in
  (measured at the Phase 2 gate — see §7).
- Final asset uploaded to the `ocw-lesson-content` S3 bucket; the orchestrator is notified
  with the **CloudFront URL**.
- Total GPU time per video recorded and within the project's per-video budget envelope.

---

## 2. Scope

**In scope (this repo):**
- Async render engine (FastAPI) on the GCP GPU VM.
- Keyframe generation with identity + style consistency.
- Image-to-video animation, per-scene clip encoding, full-video assembly.
- **Filling each scene's exact `start_seconds`/`end_seconds` window** (camera move / interpolation /
  multi-clip subdivision) and **muxing the supplied ElevenLabs audio** into a single MP4 whose
  length matches the audio exactly.
- S3 upload (boto3) to `ocw-lesson-content` and orchestrator callbacks (per-scene, per-job, idle),
  returning the **CloudFront URL**.
- Busy/idle status surface + GPU-hour accounting.
- Durable job queue + crash recovery on a single GPU.
- Reproducible environment (venv/container) + GPU verification + benchmark harness.

**Out of scope (Nest.js / AWS side — documented, not built here):**
- LLM story → scene-array extraction.
- **Audio generation (already done via ElevenLabs)** and **timestamp→scene alignment** (Nest.js
  uses ElevenLabs word timestamps to stamp each scene's `start_seconds`/`end_seconds`).
- Job dispatch, retry policy, and the "queue drained → email me" action.
- Persisting/serving final videos in the LMS.

**Resolved:**
- **Character reference images** are produced upstream by the LMS's existing character pipeline
  and hosted under the per-story CDN directory:
  `https://d35ivcpjrjjgk.cloudfront.net/lesson-content/Stories-podcast/{story_slug}/`.
  The engine fetches them by URL (no upload endpoint needed).

**Resolved (cont.):**
- **S3-key ↔ CloudFront-path mapping** — confirmed by the LMS `output.key_prefix`:
  `s3_key = key_prefix + "/" + filename`, `video_url = {CLOUDFRONT_BASE_URL}/{s3_key}` (path == key,
  no origin rewrite). e.g. `.../lesson-content/Stories-podcast/the-weight/video/final.mp4`.

**Open decisions (need your input before the relevant phase):**
- **Deployment method** (GitHub Actions self-hosted runner vs. scripted `git pull` + systemd) — Phase 7.

---

## 3. Architecture (target)

```
[AWS: Nest.js LMS]
   │  1. LLM parses story → scene array (Nest.js side, out of scope here)
   │  2. POST /jobs  (HMAC-signed)  ──────────────►  [GCP VM: FastAPI engine]
   │                                                      │ 202 Accepted + job_id
   │                                                      ▼
   │                                              durable job queue (1 GPU, serialized)
   │                                                      │
   │           per-scene & per-job webhooks  ◄──────  render worker:
   │                                                   Stage A: identity-locked keyframe
   │                                                   Stage B: image→video animation
   │                                                   Stage C: encode clip → assemble mp4
   │                                                      │
   │   GET /status (idle|busy, queue depth, GPU hours) ◄──┤
   │                                                      ▼
   │   idle callback  ◄──────── queue drained ───  [AWS S3]  ◄── upload final .mp4
   │   (Nest.js emails Diego to shut the VM down)
```

**Generation strategy (the core idea):** identity is solved primarily at the **keyframe**
stage (a per-character reference image conditions every keyframe the character appears in).
The video model only *animates* an already-consistent frame. This isolates the hardest
problem (identity) to the most controllable stage.

**Audio is the master clock:** the ElevenLabs audio (and per-scene `start_seconds`/`end_seconds`
computed from its word timestamps by Nest.js) is the authority. The engine renders visuals to
fill each window, concatenates them, muxes the audio, and forces the final length to match the
audio exactly. The engine never generates or re-times audio — it only consumes it.

---

## 4. Functional requirements

### FR-1 Job ingestion
- `POST /jobs` accepts a job payload (see [`API_CONTRACT.md`](API_CONTRACT.md)), validates it,
  enqueues it, and returns **202 Accepted** with a `job_id` **immediately**.
- Requests are authenticated (shared secret / HMAC). Unauthenticated requests are rejected.

### FR-2 Durable, serialized queue
- Jobs persist to disk so a process restart resumes pending/in-progress work.
- Exactly one job renders at a time (single GPU). Queue position is queryable.

### FR-3 Stage A — identity-locked keyframe
- For each scene, generate a 16:9 cinematic keyframe at the model's native target size.
- Characters listed in `characters_present` are conditioned on their reference image /
  identity embedding so they stay recognizable.
- A `global_style` string is applied to every keyframe for world/style consistency.
- Per-scene RNG seeds are recorded for reproducibility.

### FR-4 Stage B — animation & duration fill (audio-driven)
- Animate each keyframe into a clip using the chosen I2V model.
- `motion_strength` and `camera_motion` map to the model's motion controls.
- **Each scene must fill its exact window** `scene_duration = end_seconds - start_seconds`.
  Since I2V native clips are short (~3–4 s), the engine fills the window using, in order of
  preference for GPU economy: (a) slow camera move / Ken Burns on the keyframe, (b) frame
  interpolation to stretch a short clip smoothly, (c) multi-clip subdivision for long beats.
- The chosen fill strategy and its cost are validated at the G2 benchmark gate.

### FR-5 Stage C — assemble, mux audio, exact-length
- Encode each scene clip to `.mp4` (H.264, web-friendly).
- Concatenate scene clips in `scene_sequence` order to form the silent visual track.
- **Fetch the supplied `audio.url` and mux it** into the final MP4.
- **Force total duration to equal the audio length exactly** (trim/pad the final frame as needed);
  log any per-scene drift between target window and rendered length.

### FR-6 Delivery
- Upload the final `.mp4` (and optionally per-scene clips) to the **`ocw-lesson-content`** S3
  bucket via boto3.
- POST a per-job success/failure webhook with the **CloudFront URL** (the distribution already
  fronts that bucket) plus the S3 key and metadata.

### FR-7 Status & accounting
- `GET /status` returns `{state, current_job, queue_depth, gpu, cumulative_gpu_seconds, uptime}`.
- `GET /jobs/{id}` returns progress (`scenes_done/scenes_total`, ETA, per-scene status).
- The engine tracks cumulative GPU busy seconds (toward the GPU-hour budget) and exposes it.

### FR-8 Idle lifecycle
- When the queue drains and no job is running, the engine POSTs an **idle callback** to the
  orchestrator so Nest.js can email Diego to shut down the VM.
- Optional self-managed `IDLE_SHUTDOWN_MINUTES`: the engine may initiate OS shutdown after N
  idle minutes (off by default during development).

### FR-9 Crash recovery
- Completed scenes are checkpointed (keyframe + clip persisted). On restart, an interrupted
  job resumes from the first incomplete scene rather than re-rendering completed work.

---

## 5. Non-functional requirements

- **NFR-1 GPU economy:** minimize idle GPU time; never re-render checkpointed work; record all GPU time.
- **NFR-2 Reproducibility:** pinned dependencies; venv/container; recorded seeds & model versions per job.
- **NFR-3 Single-GPU safety:** stay within 24 GB VRAM (model offload/sequencing as needed); no OOM crashes.
- **NFR-4 Observability:** structured logs per job/scene; timings; clear failure reasons in callbacks.
- **NFR-5 Security:** scoped AWS IAM creds (S3 PutObject on the target bucket only); secrets via env, never committed; HMAC-verified inbound and signed outbound webhooks.
- **NFR-6 Portability:** swappable generator interface so the L4→V100 move (or a model change) does not require rearchitecting.

---

## 6. Environment (verified + corrections)

- **VM:** GCP `g2-standard-4` — 4 vCPU, 16 GB RAM, **1× NVIDIA L4 (24 GB)**, 100 GB balanced PD.
- **OS:** Ubuntu 24.04 LTS · **NVIDIA driver 580** · Python **3.12.3**.
- **CUDA/PyTorch:** PyTorch built for **CUDA 12.1 (cu121)** — `torch.cuda.is_available() == True` ✅ (verified).
- **Correction:** install into a **venv** (or container), **not** system Python via `--break-system-packages`.
- **Note for later:** a planned **V100** VM is older architecture (no bf16) and the common variant has **16 GB** VRAM — re-validate VRAM headroom and precision before assuming it's a straight upgrade.

---

## 7. Verification-first gates

No phase advances without its gate passing.

- **G1 (Env):** fresh venv reproduces a working `torch.cuda.is_available() == True` + a 1-image SDXL/keyframe gen.
- **G2 (Benchmark — critical):** measured wall-clock per keyframe and per clip on the L4 for each
  candidate stack; extrapolated GPU-hours per 5-min video; identity-consistency spot check.
  **This gate decides the model stack and confirms the GPU-hour budget is feasible.**
- **G3 (Engine):** queue + status + callbacks work end-to-end against a stubbed generator.
- **G4 (Quality):** a full short story renders with characters recognizable across scenes.

---

## 8. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Per-clip render too slow for GPU-hour budget | Few/no full videos | G2 benchmark before scale; consider faster model / fewer-longer clips |
| Identity drift across scenes | Fails primary goal | Reference-conditioned keyframes; per-character embedding; G4 gate |
| VRAM OOM with two pipelines | Crashes | Sequential load + offload; measured at G1/G2 |
| Crash mid-batch wastes GPU hours | Budget burn | Per-scene checkpointing (FR-9) |
| Cross-cloud credential leak | Security | Scoped IAM, secrets in env, signed webhooks |
| Choppy 3-sec hard cuts | Poor cinematics | Per-scene duration; evaluate longer-clip models at G2 |
