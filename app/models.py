"""Pydantic models for the v1.1 contract (see docs/API_CONTRACT.md)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, model_validator

# Tolerance (seconds) for the timing invariant — accommodates float rounding from
# the LMS's word-timestamp alignment.
TIMING_TOLERANCE_S = 0.5


class RefImage(BaseModel):
    url: str
    is_primary: bool = False


class Character(BaseModel):
    id: str
    name: Optional[str] = None
    subject_type: Optional[str] = "person"
    description: Optional[str] = None
    appearance_prompt: Optional[str] = None
    reference_images: list[RefImage] = []

    def primary_reference(self) -> Optional[str]:
        for r in self.reference_images:
            if r.is_primary:
                return r.url
        return self.reference_images[0].url if self.reference_images else None


class Scene(BaseModel):
    sequence: int
    start_seconds: float
    end_seconds: float
    narration_excerpt: Optional[str] = None
    keyframe_prompt: str
    negative_prompt: Optional[str] = None
    characters_present: list[str] = []
    camera_motion: str = "static"
    motion_strength: float = 0.5
    seed: Optional[int] = None

    @property
    def duration(self) -> float:
        return self.end_seconds - self.start_seconds

    @model_validator(mode="after")
    def _check_window(self) -> "Scene":
        if self.end_seconds <= self.start_seconds:
            raise ValueError(f"scene {self.sequence}: end_seconds must be > start_seconds")
        if not (0.0 <= self.motion_strength <= 1.0):
            raise ValueError(f"scene {self.sequence}: motion_strength must be within 0..1")
        return self


class Audio(BaseModel):
    url: str
    duration_seconds: float


class Output(BaseModel):
    bucket: str
    key_prefix: str
    aspect_ratio: str = "16:9"
    container: str = "mp4"
    video_codec: str = "h264"


class Story(BaseModel):
    story_id: Optional[str] = None
    slug: str
    title: Optional[str] = None
    language: Optional[str] = None
    cefr_level: Optional[str] = None


class Callback(BaseModel):
    url: str
    events: list[str] = ["scene_completed", "job_completed", "job_failed", "idle"]


class JobRequest(BaseModel):
    schema_version: str = "1.1"
    job_id: str
    story: Story
    audio: Audio
    output: Output
    global_style: str = ""
    characters: list[Character] = []
    scenes: list[Scene]
    callback: Callback

    def ordered_scenes(self) -> list[Scene]:
        return sorted(self.scenes, key=lambda s: s.sequence)

    @model_validator(mode="after")
    def _validate_job(self) -> "JobRequest":
        scenes = self.ordered_scenes()
        if not scenes:
            raise ValueError("scenes must be non-empty")

        # Timing invariant: contiguous, gapless, covering [0, audio.duration].
        if abs(scenes[0].start_seconds) > TIMING_TOLERANCE_S:
            raise ValueError("scenes[0].start_seconds must be 0")
        for prev, cur in zip(scenes, scenes[1:]):
            if abs(cur.start_seconds - prev.end_seconds) > TIMING_TOLERANCE_S:
                raise ValueError(
                    f"scene {cur.sequence} start ({cur.start_seconds}) must equal "
                    f"previous scene end ({prev.end_seconds}) — gap/overlap not allowed"
                )
        if abs(scenes[-1].end_seconds - self.audio.duration_seconds) > TIMING_TOLERANCE_S:
            raise ValueError(
                f"last scene end ({scenes[-1].end_seconds}) must equal "
                f"audio.duration_seconds ({self.audio.duration_seconds})"
            )

        # characters_present must reference defined characters.
        defined = {c.id for c in self.characters}
        for s in scenes:
            for cid in s.characters_present:
                if cid not in defined:
                    raise ValueError(
                        f"scene {s.sequence}: characters_present '{cid}' is not defined in characters[]"
                    )
        return self


# ---- Response models ----

class JobAccepted(BaseModel):
    job_id: str
    status: str
    queue_position: int
