# Roadmap — Phased Implementation

Each phase ends with a **git round** (commit message provided for your approval) and, where
applicable, a **verification gate** that must pass before the next phase. Verification-first:
we prove each layer works before stacking the next.

Legend: 🧱 scaffold · ⚙️ runtime code · 🔬 measurement · 🚦 gate

---

## ⚠️ Direction v2 (2026-06-05) — real video (Wan) + Continuity Director

The Phase 4–5 approach (SDXL still per scene → Ken Burns pan/zoom) is **superseded**: it produced
"images with zoom," not video, and character identity never held. We are moving to **real
self-hosted video generation (Wan 2.2)** with a **Continuity Director** (cuts vs. continuous takes)
and **video-native face-ID**. See [`CINEMATIC_PIPELINE.md`](CINEMATIC_PIPELINE.md) for the
architecture and the **prerequisites checklist** (GPU upgrade, HF access, disk, real job JSON).

**What survives:** Phase 0–3 (engine skeleton, contract, job lifecycle, checkpoints, webhooks,
audio-as-master-clock, the swappable `Generator` protocol). **What is retired:** `kenburns.py`,
the SVD-XT A/B path, and SDXL+IP-Adapter as the identity mechanism.

Re-phased plan below as **Phases A–D** (replacing the old Phases 4–6).

### Phase A — GPU upgrade + Wan environment  ⚙️🚦G1′
- Provision the new GPU VM (A100-class; see `CINEMATIC_PIPELINE.md` §6–7); off by default.
- Pin a Wan-capable stack (bump `diffusers`; add Wan + the face-ID/reference deps). HF auth for
  gated Wan models.
- **Gate G1′:** fresh env renders **one Wan clip** from a reference image on the new GPU.

### Phase B — Wan benchmark + identity + transition modes  🔬🚦G2′  ← *decides the stack with footage*
- `scripts/bench_wan.py` (mirrors the old `bench_svd.py`): render 2–3 **real** `the-weight` beats.
- Measure seconds/clip + VRAM on the new GPU → **real cost per 5-min video** (the old ~30 GPU-h
  budget is void).
- Judge from footage: (a) Wan I2V quality + identity (Phantom/VACE/ConsisID, or Wan 2.7 R2V),
  (b) **last-frame chaining** (CONTINUOUS), (c) **location-anchor reuse** (CUT_SAME_SCENE),
  (d) clean HARD_CUT.
- **Gate G2′:** stack + identity method + per-mode recipe locked from real footage; cost confirmed.

### Phase C — Rewrite the generator (Continuity Director + Wan recipes)  ⚙️
- New `WanGenerator` behind the existing `Generator` protocol: **Continuity Director** (3-tier
  decision), **location-anchor cache**, per-mode conditioning → Wan I2V/FLF2V → fill each scene's
  exact `start..end` window → concat + mux (existing `assemble.py`). Keep checkpoint/resume (FR-9).
- Implement `scene_group_id` / `shot_relation` parsing (v1.2) + the heuristic fallback.

### Phase D — Full render + delivery  ⚙️🚦G4
- Full `the-weight` render on real assets; **identity gate G4** (boy recognizable across scenes;
  motion is real; cuts read as cuts). Then boto3 S3 upload + CloudFront URL + idle lifecycle.

---

## Historical phases (Direction v1 — kept for the audit trail)

> Phases 4–6 below describe the retired SDXL+Ken Burns approach. Superseded by Phases A–D above.

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

## Phase 3 — Engine skeleton (no real generation)  ⚙️🚦G3  ✅ PASSED
- FastAPI app: `/health`, `/status`, `POST /jobs`, `GET /jobs/{id}` (`app/`).
- In-memory single-GPU worker + **stub** generator; per-job filesystem checkpoints (`WORK_DIR`).
- Auth (bearer + HMAC over raw body); GPU-second accounting; v1.1 payload validation
  (timing invariant, `characters_present` ⊆ `characters[]`).
- Outbound webhooks (`scene_completed`/`job_completed`/`job_failed`/`idle`) — HMAC-signed.
- **Gate G3 result (verified locally, no GPU):** 202 → progress → done; idle callback delivered;
  idempotent re-submit → 200; bad token/HMAC → 401; bad timing → 400. See `docs/ENGINE.md`.

## Phase 4 — Stage A: identity-locked keyframes  ⚙️  (SUPERSEDED by Phase A–C — see Direction v2)
- `app/generators/keyframe.py` — `KeyframeGenerator` (SDXL fp16 + IP-Adapter, no offload):
  conditions each scene on the present character's primary reference; applies `global_style`;
  neutralizes identity (scale 0) for no-character scenes; records the seed.
- `scripts/gen_keyframes.py` — verify on a full v1.1 job (`--job`) or quick 3-scene smoke
  (`--reference`). `samples/the_weight.template.json` is a fill-in starting point.
- **Verify on the VM:** keyframes for the story's scenes are identity-consistent in the real
  `global_style`. Then Phase 5 wires this into the engine's real generator. See `docs/PHASE4.md`.
- Implement the chosen keyframe generator + character reference conditioning + `global_style`.
- Seed recording, VRAM-safe load/offload.

## Phase 5 — Stage B+C: duration-fill, assemble + audio mux  ⚙️  (SUPERSEDED by Phase A–D — Ken Burns retired)
- **Decision: Ken Burns default, SVD A/B toggle.** Ken Burns = exact duration, honors
  `camera_motion`, style-safe, CPU/ffmpeg (no VRAM juggling — only SDXL on GPU).
- `kenburns.py` (pan/zoom fill) + `assemble.py` (ffmpeg concat + audio fetch + mux + exact length)
  + `cinematic.py` (`CinematicGenerator.render_job`); engine selects via `ENGINE_GENERATOR=cinematic`.
- `scripts/render_job.py` renders a full job offline; SVD A/B via `bench_svd.py --keyframe`.
- **Verified locally (no GPU):** Stage C produced an exact-duration muxed mp4; G3 still green after
  the `render_job` refactor. **Verify on VM:** render the-weight end-to-end. See `docs/PHASE5.md`.

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
