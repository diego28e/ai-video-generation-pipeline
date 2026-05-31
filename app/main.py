"""FastAPI app for the Cinematic GenAI Video Engine (Phase 3 skeleton)."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from . import __version__
from .auth import authenticate
from .config import get_settings
from .generators.stub import StubGenerator
from .jobs import JobManager
from .models import JobRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("engine")

manager: JobManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global manager
    settings = get_settings()
    generator = StubGenerator(scene_seconds=settings.stub_scene_seconds)
    manager = JobManager(generator)
    manager.start()
    log.info("engine %s started (generator=%s, schema=%s)", __version__, generator.name, settings.schema_version)
    try:
        yield
    finally:
        await manager.stop()


app = FastAPI(title="Cinematic GenAI Video Engine", version=__version__, lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "version": __version__, "schema_version": get_settings().schema_version}


@app.get("/status")
async def status():
    assert manager is not None
    return manager.status()


@app.post("/jobs")
async def submit_job(request: Request):
    assert manager is not None
    body = await authenticate(request)  # 401 on bad token / signature

    try:
        req = JobRequest.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=json.loads(exc.json()))

    position, kind = await manager.submit(req)
    if kind == "conflict":
        raise HTTPException(status_code=409, detail="job_id already exists with a different body")

    rec = manager.record(req.job_id)
    code = 202 if kind == "new" else 200
    return JSONResponse(
        {"job_id": req.job_id, "status": rec["status"], "queue_position": position},
        status_code=code,
    )


@app.get("/jobs/{job_id}")
async def job_progress(job_id: str):
    assert manager is not None
    prog = manager.progress(job_id)
    if prog is None:
        raise HTTPException(status_code=404, detail="unknown job_id")
    return prog
