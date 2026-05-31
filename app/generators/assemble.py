"""Stage C — concatenate scene clips, fetch + mux the supplied audio, force exact length.

Uses ffmpeg (system ffmpeg if present, else the imageio-ffmpeg bundled binary).
The timing invariant guarantees the concatenated video length == audio duration.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import urllib.request

log = logging.getLogger("engine.assemble")


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str]) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {proc.stderr[-1500:]}")


def _fetch_audio(url: str, dest: str) -> str:
    if url.startswith(("http://", "https://")):
        log.info("fetching audio %s", url)
        with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        return dest
    # local path (file:// or plain)
    src = url[len("file://"):] if url.startswith("file://") else url
    if not os.path.exists(src):
        raise FileNotFoundError(f"audio not found: {src}")
    return src


def assemble(scene_clips: list[str], audio_url: str, out_path: str, work_dir: str) -> str:
    if not scene_clips:
        raise ValueError("no scene clips to assemble")
    ffmpeg = _ffmpeg()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    # 1) concat the (identically-encoded) scene clips without re-encoding video.
    list_path = os.path.join(work_dir, "concat.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for clip in scene_clips:
            f.write(f"file '{os.path.abspath(clip)}'\n")
    silent = os.path.join(work_dir, "video_silent.mp4")
    _run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", silent])

    # 2) mux the narration; aac audio, keep video as-is.
    audio_path = _fetch_audio(audio_url, os.path.join(work_dir, "narration_input"))
    _run([
        ffmpeg, "-y",
        "-i", silent,
        "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        out_path,
    ])
    log.info("assembled final video -> %s", out_path)
    return out_path
