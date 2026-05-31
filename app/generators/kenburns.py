"""Ken Burns duration-fill: turn a still keyframe into an exact-length clip via a slow
camera pan/zoom. CPU only — preserves the painterly style (the image is never regenerated)
and honors the scene's `camera_motion`. Encodes H.264 via imageio-ffmpeg.
"""
from __future__ import annotations

import logging

import imageio.v2 as imageio
import numpy as np
from PIL import Image

log = logging.getLogger("engine.kenburns")

Rect = tuple[float, float, float, float]  # (left, top, width, height) in source px


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _plan(width: int, height: int, motion: str, amt: float) -> tuple[Rect, Rect]:
    """Return (start_rect, end_rect) crop windows for the given camera motion."""
    full: Rect = (0.0, 0.0, float(width), float(height))
    zw, zh = width * (1 - amt), height * (1 - amt)
    centered: Rect = ((width - zw) / 2, (height - zh) / 2, zw, zh)

    if motion == "push_in":
        return full, centered
    if motion == "pull_out":
        return centered, full
    if motion in ("pan_left", "pan_right"):
        w = width * (1 - amt)
        right: Rect = (width - w, 0.0, w, float(height))
        left: Rect = (0.0, 0.0, w, float(height))
        return (right, left) if motion == "pan_left" else (left, right)
    if motion in ("tilt_up", "tilt_down"):
        h = height * (1 - amt)
        bottom: Rect = (0.0, height - h, float(width), h)
        top: Rect = (0.0, 0.0, float(width), h)
        return (bottom, top) if motion == "tilt_up" else (top, bottom)
    # static / unknown -> a gentle, almost-still drift so the frame isn't dead.
    gw, gh = width * (1 - amt * 0.4), height * (1 - amt * 0.4)
    gentle: Rect = ((width - gw) / 2, (height - gh) / 2, gw, gh)
    return full, gentle


def _lerp_rect(a: Rect, b: Rect, t: float) -> Rect:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(4))  # type: ignore[return-value]


def render_scene_clip(
    keyframe_path: str,
    out_path: str,
    duration: float,
    fps: int = 24,
    camera_motion: str = "static",
    motion_strength: float = 0.3,
) -> str:
    img = Image.open(keyframe_path).convert("RGB")
    width, height = img.size
    n_frames = max(int(round(duration * fps)), 1)
    amt = _clamp(0.10 + 0.22 * _clamp(motion_strength, 0.0, 1.0), 0.05, 0.35)
    start, end = _plan(width, height, camera_motion, amt)

    writer = imageio.get_writer(
        out_path, fps=fps, codec="libx264", quality=7, pixelformat="yuv420p", macro_block_size=16
    )
    try:
        for i in range(n_frames):
            t = i / (n_frames - 1) if n_frames > 1 else 0.0
            t = t * t * (3 - 2 * t)  # smoothstep ease
            left, top, w, h = _lerp_rect(start, end, t)
            frame = img.resize((width, height), Image.LANCZOS, box=(left, top, left + w, top + h))
            writer.append_data(np.asarray(frame))
    finally:
        writer.close()
    log.info("ken burns: %s (%.2fs, %d frames, %s)", out_path, duration, n_frames, camera_motion)
    return out_path
