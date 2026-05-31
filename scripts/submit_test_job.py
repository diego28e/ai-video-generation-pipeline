#!/usr/bin/env python3
"""Submit a signed sample v1.1 job to the engine for Gate G3.

Uses only the stdlib. Generic placeholder data (no real endpoints).
Env (defaults match the engine's dev defaults):
  ENGINE_API_TOKEN, ENGINE_HMAC_SECRET, ENGINE_URL, MOCK_CALLBACK

Run:  python scripts/submit_test_job.py [job_id]
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request

TOKEN = os.environ.get("ENGINE_API_TOKEN", "dev-token")
SECRET = os.environ.get("ENGINE_HMAC_SECRET", "dev-secret")
ENGINE = os.environ.get("ENGINE_URL", "http://127.0.0.1:8000").rstrip("/")
CALLBACK = os.environ.get("MOCK_CALLBACK", "http://127.0.0.1:9000/webhooks/story-video")


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def build_payload(job_id: str) -> dict:
    return {
        "schema_version": "1.1",
        "job_id": job_id,
        "story": {"story_id": "demo", "slug": "demo-story", "title": "Demo", "language": "en", "cefr_level": "B1"},
        "audio": {"url": "https://example.com/demo/audio.mp3", "duration_seconds": 30.0},
        "output": {
            "bucket": "your-content-bucket",
            "key_prefix": "your-prefix/stories/demo-story/video",
            "aspect_ratio": "16:9", "container": "mp4", "video_codec": "h264",
        },
        "global_style": "painterly storybook illustration",
        "characters": [
            {"id": "hero", "name": "Hero", "subject_type": "person",
             "reference_images": [{"url": "https://example.com/demo/hero.png", "is_primary": True}]},
        ],
        "scenes": [
            {"sequence": 1, "start_seconds": 0.0, "end_seconds": 10.0,
             "keyframe_prompt": "a quiet street at night", "characters_present": [],
             "camera_motion": "push_in", "motion_strength": 0.25},
            {"sequence": 2, "start_seconds": 10.0, "end_seconds": 20.0,
             "keyframe_prompt": "the hero walks down the path", "characters_present": ["hero"],
             "camera_motion": "pan_left", "motion_strength": 0.4},
            {"sequence": 3, "start_seconds": 20.0, "end_seconds": 30.0,
             "keyframe_prompt": "a dim stairwell", "characters_present": ["hero"],
             "camera_motion": "static", "motion_strength": 0.2},
        ],
        "callback": {"url": CALLBACK, "events": ["scene_completed", "job_completed", "job_failed", "idle"]},
    }


def main() -> None:
    job_id = sys.argv[1] if len(sys.argv) > 1 else "demo-job-0001"
    body = json.dumps(build_payload(job_id)).encode("utf-8")
    req = urllib.request.Request(
        f"{ENGINE}/jobs", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}", "X-Signature": sign(body)},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"POST /jobs -> {resp.status} {resp.read().decode()}")
    except urllib.error.HTTPError as exc:
        print(f"POST /jobs -> HTTP {exc.code} {exc.read().decode()}")


if __name__ == "__main__":
    main()
