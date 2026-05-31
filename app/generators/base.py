"""Generator interface — the swappable boundary (NFR-6).

Phase 3 ships a no-GPU StubGenerator. Phase 4 (SDXL + IP-Adapter keyframes) and
Phase 5 (SVD-XT animation + Ken Burns fill + ffmpeg mux) implement the same protocol,
so the engine/queue code never changes when we swap the real generator in.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import JobRequest, Scene


@runtime_checkable
class Generator(Protocol):
    name: str

    async def render_scene(self, job: JobRequest, scene: Scene, work_dir: str) -> float:
        """Render one scene (keyframe -> clip -> duration-fill) into work_dir.
        Returns GPU-seconds consumed (for budget accounting)."""
        ...

    async def assemble(self, job: JobRequest, work_dir: str) -> str:
        """Concatenate scene clips, mux the supplied audio, force exact length.
        Returns the local path to the final .mp4."""
        ...
