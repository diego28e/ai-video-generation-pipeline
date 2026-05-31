# Roadmap — Phased Implementation

Each phase ends with a **git round** (commit message provided for your approval) and, where
applicable, a **verification gate** that must pass before the next phase. Verification-first:
we prove each layer works before stacking the next.

Legend: 🧱 scaffold · ⚙️ runtime code · 🔬 measurement · 🚦 gate

---

## Phase 0 — Foundation & repo  🧱  ← **current round**
- Requirements, API contract, roadmap docs.
- Repo scaffold, `.gitignore`, `.env.example`.
- `git init` + first commit (you run the commands).
- **Deliverable:** reviewable direction + initialized repo. No runtime code yet.

## Phase 1 — Reproducible environment & GPU verification  ⚙️🚦G1  ✅ PASSED
- `venv` bootstrap script (replaces `--break-system-packages`) + venv guard in every script.
- Pinned base `requirements.txt` (torch 2.5.1+cu121 + diffusers/transformers/accelerate/...).
- `scripts/verify_gpu.py` + `scripts/verify_keyframe.py`. See `docs/SETUP.md`.
- **Gate G1 result:** L4 / 22.0 GiB / CUDA 12.1; SDXL keyframe **15.6 s**, peak **5.11 GiB**.

## Phase 2 — Model evaluation & benchmark  🔬🚦G2  ← **current; decides the stack**
- See `docs/BENCHMARK.md` for protocol + the live results table.
- **Step 2a (now):** video-stage baseline — `scripts/bench_svd.py` (SVD-XT, the provisioned stack).
- **Step 2b:** if SVD-XT misses the budget, benchmark a faster alternative (LTX-Video) before deciding.
- **Step 2c:** identity spot-check — SDXL + identity adapter across 3 scenes.
- **Gate G2:** stack locked with data; 70h budget feasibility confirmed (or scope adjusted).
- *(This is where your "evaluate alternatives" decision is cashed in, with real numbers.)*

## Phase 3 — Engine skeleton (no real generation)  ⚙️🚦G3
- FastAPI app: `/health`, `/status`, `POST /jobs`, `GET /jobs/{id}`.
- Durable queue + single-worker loop + **stub** generator.
- Auth (bearer + HMAC), structured logging, GPU-hour accounting scaffold.
- Outbound webhooks (scene/job/idle) against a local mock receiver.
- **Gate G3:** submit a job → 202 → progress → completion + idle callback, end-to-end, no GPU.

## Phase 4 — Stage A: identity-locked keyframes  ⚙️
- Implement the chosen keyframe generator + character reference conditioning + `global_style`.
- Seed recording, VRAM-safe load/offload.

## Phase 5 — Stage B+C: animation, duration-fill, assemble + audio mux  ⚙️
- I2V animation per keyframe; fill each scene's exact `start..end` window (camera move /
  interpolation / multi-clip); `.mp4` encode (H.264); concatenate scenes.
- Fetch the supplied audio and **mux it** (ffmpeg); force total length == audio length.
- Adds a system dependency: **ffmpeg** (apt) — noted in Phase 1 env setup.

## Phase 6 — Delivery & lifecycle  ⚙️🚦G4
- boto3 S3 upload (scoped IAM); real job/scene webhooks; idle callback wired.
- Per-scene checkpointing + crash-recovery resume.
- **Gate G4:** a real short story renders end-to-end; characters recognizable across scenes.

## Phase 7 — Orchestration hardening & deployment  ⚙️
- Optional `IDLE_SHUTDOWN_MINUTES` self-stop strategy.
- systemd unit for the engine; **deployment decision**: GitHub Actions self-hosted runner vs.
  scripted `git pull` + service restart. *Recommendation:* start scripted/manual; add GitHub
  Actions self-hosted runner only once the flow is stable (a self-hosted runner on a metered
  GPU VM that's off most of the time adds little early on).

## Phase 8 — (Deferred, needs decision) Audio & V100 migration
- Narration (TTS) / music / subtitles muxing — only if you want it.
- Re-validate pipeline + VRAM on the V100 VM.

---

## Deployment note (you're open to GitHub Actions)
For a single GPU VM that is **off most of the time**, a webhook-triggered CI deploy can't reach
a powered-down host. Practical options, simplest first:
1. **Manual/scripted** `git pull && systemctl restart genai-engine` over SSH — fine through Phase 6.
2. **GitHub Actions + self-hosted runner on the VM** — only runs while the VM is up; good once
   sessions are routine. We'd register the runner as a service.
3. **Image bake** (build a GCP machine image per release) — best for spinning the V100 VM later.

We'll finalize this at Phase 7.
