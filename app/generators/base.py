"""Generator interface — the swappable boundary (NFR-6).

A generator turns a whole job into a final .mp4. Job-level (not per-scene) so it can
manage model residency and report per-scene progress + GPU accounting via a callback.

Implementations:
  - StubGenerator   (no GPU, Phase 3) — sleeps + placeholder files.
  - CinematicGenerator (Phase 5) — SDXL+IP-Adapter keyframe -> Ken Burns fill -> ffmpeg mux.
"""
from __future__ import annotations

from typing import Awaitable, Callable, Protocol, runtime_checkable

from ..models import JobRequest

# Called as each scene's final clip becomes ready: (sequence, gpu_seconds_for_that_scene).
OnSceneCompleted = Callable[[int, float], Awaitable[None]]


@runtime_checkable
class Generator(Protocol):
    name: str

    async def render_job(
        self, job: JobRequest, work_dir: str, on_scene_completed: OnSceneCompleted
    ) -> str:
        """Render the whole job; return the local path to the final muxed .mp4.
        Must call on_scene_completed(sequence, gpu_seconds) as each scene's clip finishes,
        and may skip scenes already checkpointed under work_dir (crash-resume, FR-9)."""
        ...
