#!/usr/bin/env python3
"""Convert a scene-mapping TSV into a validated v1.1 job JSON.

Stopgap for hand-authored scene tables (your LMS will emit v1.1 jobs directly in production).
Save your table as TSV with a header row containing at least: sequence, start, end, prompt
(a `narration` column is kept as narration_excerpt; optional `camera`/`characters` columns
override the keyword inference below).

Example:
  .venv/bin/python scripts/scenes_to_job.py --tsv the_weight.tsv \
    --slug the-weight --duration 299.42 \
    --audio-url https://<cdn>/.../The_weight.mp3 \
    --boy-ref https://<cdn>/.../characters/the-boy.png \
    --narrator-ref https://<cdn>/.../characters/narrator.png \
    --style "cinematic realistic CGI render, Unreal Engine, volumetric lighting, hyperrealistic, dramatic" \
    --out samples/the_weight.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _col(header: list[str], *names: str) -> int | None:
    low = [h.strip().lower() for h in header]
    for n in names:
        for i, h in enumerate(low):
            if n in h:
                return i
    return None


def infer_camera(prompt: str) -> str:
    p = prompt.lower()
    if any(k in p for k in ("pull out", "pulls out", "zoom out")):
        return "pull_out"
    if any(k in p for k in ("crane", "high-angle", "high angle", "looking down", "overhead", "top-down")):
        return "tilt_down"
    if any(k in p for k in ("low angle", "low-angle", "looking up", "tilt up", "tilts up")):
        return "tilt_up"
    if any(k in p for k in ("push", "zoom in", "zooms", "dolly in", "dollys in", "reveal",
                            "close-up", "close up", "macro", "extreme close")):
        return "push_in"
    if any(k in p for k in ("pan", "tracking", "track", "sweep")):
        return "pan_left"
    if any(k in p for k in ("static", "locks", "still")):
        return "static"
    return "push_in"


def infer_strength(prompt: str) -> float:
    p = prompt.lower()
    if any(k in p for k in ("jarring", "violently", "snap", "drop", "spin", "vortex",
                            "shockwave", "warp", "tumbling", "falling", "dizzy")):
        return 0.55
    if any(k in p for k in ("motionless", "completely still", "rigid", "frozen", "static")):
        return 0.15
    return 0.3


def infer_characters(prompt: str, have_boy: bool, have_narrator: bool) -> list[str]:
    p = prompt.lower()
    boy = have_boy and any(k in p for k in ("boy", "child", "kid"))
    adult = have_narrator and any(k in p for k in ("protagonist", "main character", "adult", "narrator", "character"))
    present = []
    if adult:
        present.append("narrator")
    if boy:
        present.append("the-boy")
    return present


def main() -> None:
    ap = argparse.ArgumentParser(description="Scene-mapping TSV -> v1.1 job JSON")
    ap.add_argument("--tsv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--duration", type=float, required=True, help="audio duration_seconds")
    ap.add_argument("--audio-url", required=True)
    ap.add_argument("--boy-ref", default="")
    ap.add_argument("--narrator-ref", default="")
    ap.add_argument("--style", default="cinematic realistic CGI render, volumetric lighting, hyperrealistic, dramatic")
    ap.add_argument("--callback", default="https://your-lms-domain.example.com/webhooks/story-video")
    ap.add_argument("--job-id", default=None)
    args = ap.parse_args()

    with open(args.tsv, encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    header, data = rows[0], rows[1:]
    c_seq = _col(header, "sequence", "scene #", "scene", "#")
    c_start = _col(header, "start")
    c_end = _col(header, "end")
    c_prompt = _col(header, "prompt", "visual", "keyframe")
    c_narr = _col(header, "narration", "anchor", "text")
    c_cam = _col(header, "camera")
    c_chars = _col(header, "characters")
    if None in (c_seq, c_start, c_end, c_prompt):
        raise SystemExit(f"TSV needs sequence/start/end/prompt columns; got header={header}")

    have_boy, have_narrator = bool(args.boy_ref), bool(args.narrator_ref)
    characters = []
    if have_narrator:
        characters.append({"id": "narrator", "name": "Narrator", "subject_type": "person",
                           "reference_images": [{"url": args.narrator_ref, "is_primary": True}]})
    if have_boy:
        characters.append({"id": "the-boy", "name": "The Boy", "subject_type": "person",
                           "reference_images": [{"url": args.boy_ref, "is_primary": True}]})

    scenes = []
    for r in data:
        if not r or not r[c_seq].strip():
            continue
        prompt = r[c_prompt].strip()
        present = (
            [x.strip() for x in r[c_chars].split(",") if x.strip()]
            if c_chars is not None and r[c_chars].strip()
            else infer_characters(prompt, have_boy, have_narrator)
        )
        scenes.append({
            "sequence": int(float(r[c_seq])),
            "start_seconds": float(r[c_start]),
            "end_seconds": float(r[c_end]),
            "narration_excerpt": r[c_narr].strip() if c_narr is not None else None,
            "keyframe_prompt": prompt,
            "characters_present": present,
            "camera_motion": r[c_cam].strip() if c_cam is not None and r[c_cam].strip() else infer_camera(prompt),
            "motion_strength": infer_strength(prompt),
        })

    job = {
        "schema_version": "1.1",
        "job_id": args.job_id or f"{args.slug}-local",
        "story": {"slug": args.slug, "title": args.title or args.slug},
        "audio": {"url": args.audio_url, "duration_seconds": args.duration},
        "output": {"bucket": "your-content-bucket", "key_prefix": f"your-prefix/stories/{args.slug}/video"},
        "global_style": args.style,
        "characters": characters,
        "scenes": scenes,
        "callback": {"url": args.callback, "events": ["scene_completed", "job_completed", "job_failed", "idle"]},
    }

    # Validate before writing so a bad table fails loudly here, not at submit time.
    from app.models import JobRequest

    JobRequest.model_validate(job)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)
    print(f"[OK] wrote {args.out}: {len(scenes)} scenes, {len(characters)} characters, validated.")


if __name__ == "__main__":
    main()
