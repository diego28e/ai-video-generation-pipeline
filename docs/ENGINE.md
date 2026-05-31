# Engine — run & test (Phase 3 skeleton)

The engine (`app/`) is a FastAPI service. Phase 3 uses a **stub generator** (no GPU), so this
whole guide runs anywhere Python + the runtime deps are installed.

## Layout
```
app/
├── main.py          # FastAPI app + routes (/health, /status, /jobs, /jobs/{id})
├── config.py        # settings from .env (pydantic-settings)
├── models.py        # v1.1 contract models + validation (timing invariant, characters_present)
├── auth.py          # bearer + HMAC over the raw body
├── security.py      # HMAC sign/verify
├── jobs.py          # in-memory single-GPU worker + GPU accounting + webhooks
├── checkpoints.py   # per-job WORK_DIR/{job_id}/ state + resume markers (FR-9)
├── webhooks.py      # signed outbound events (scene/job/idle) + retry
├── gpu.py           # GPU status (degrades gracefully without torch)
└── generators/
    ├── base.py      # Generator protocol (the swappable boundary, NFR-6)
    └── stub.py      # no-GPU stub (Phase 3); real SDXL/SVD arrive in Phase 4/5
```

## Run the engine
```bash
# on the VM (inside the venv), from the repo root:
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# health check:
curl -s http://127.0.0.1:8000/health
```
Config comes from `.env` (see `.env.example`). Auth defaults (`dev-token`/`dev-secret`) make local
testing work with no `.env`; real deployments set `ENGINE_API_TOKEN` / `ENGINE_HMAC_SECRET`.

## Gate G3 — end-to-end test (stub generator, no GPU)
Three terminals (or background), sharing the same secret:
```bash
# 1) mock LMS webhook receiver (verifies the engine's HMAC, prints events)
ENGINE_HMAC_SECRET=dev-secret python scripts/mock_lms.py

# 2) the engine, with the idle callback pointed at the mock for the test
ENGINE_API_TOKEN=dev-token ENGINE_HMAC_SECRET=dev-secret \
  ORCHESTRATOR_WEBHOOK_URL=http://127.0.0.1:9000/webhooks/story-video \
  STUB_SCENE_SECONDS=0.1 python -m uvicorn app.main:app --port 8000

# 3) submit a signed sample job (generic placeholder data)
python scripts/submit_test_job.py demo-job-0001
curl -s http://127.0.0.1:8000/jobs/demo-job-0001   # watch status -> done
curl -s http://127.0.0.1:8000/status               # busy <-> idle, cumulative_gpu_seconds
```
Expected: `POST /jobs` → 202; progress `queued→rendering→done`; the mock prints
`scene_completed`×N → `job_completed` → `idle` (all `sig=OK`).

**Verified results (local, 2026-05-31):** all of the above plus idempotent re-submit → 200,
bad token/HMAC → 401, timing-gap payload → 400.

## Notes
- The engine reads `ORCHESTRATOR_WEBHOOK_URL` for the global `idle` event; per-job events go to the
  job's `callback.url`. (During the local test, override `ORCHESTRATOR_WEBHOOK_URL` to the mock, or
  the engine will try the real configured URL.)
- Crash-resume: completed scenes are checkpointed under `WORK_DIR/{job_id}/`; re-dispatching the same
  `job_id` resumes from the first unfinished scene (FR-9).
- `requirements.txt` already includes the runtime deps (fastapi, uvicorn, pydantic, pydantic-settings,
  httpx). The mock + submit scripts are stdlib-only.
