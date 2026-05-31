#!/usr/bin/env python3
"""Phase 4 verification — generate identity-locked keyframes for a story's scenes.

Two modes:
  1) Full contract:  --job samples/the_weight.json   (a v1.1 job payload; validated)
       Resolves each scene's reference from characters[] via characters_present.
  2) Quick smoke:    --reference <url-or-path>        (3 demo scenes, like bench_identity)

Outputs to outputs/keyframes/<id>/scene_NN.png and prints seed/time/VRAM per scene.

Run on the VM (inside the venv):
  .venv/bin/python scripts/gen_keyframes.py --job samples/the_weight.json
  .venv/bin/python scripts/gen_keyframes.py --reference https://.../characters/the-boy.png \
      --style "Painterly storybook illustration, warm muted palette, 1950s small-town"
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)   # for _env_guard
sys.path.insert(0, _ROOT)   # for `app`

from _env_guard import ensure_project_venv  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate identity-locked keyframes (Stage A)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--job", help="path to a v1.1 job JSON")
    src.add_argument("--reference", help="quick mode: a single character reference (url/path)")
    p.add_argument("--subject", default="a young boy", help="quick mode subject token")
    p.add_argument("--style", default="cinematic 35mm film, moody lighting", help="quick mode global_style")
    p.add_argument("--adapter", choices=["base", "plus"], default="base")
    p.add_argument("--scale", type=float, default=0.7)
    p.add_argument("--steps", type=int, default=30)
    p.add_argument("--out-dir", default=os.path.join("outputs", "keyframes"))
    return p.parse_args()


def _scene_reference(job, scene) -> str | None:
    """First present character (defined, with a reference) drives identity for the scene."""
    by_id = {c.id: c for c in job.characters}
    for cid in scene.characters_present:
        c = by_id.get(cid)
        if c and c.primary_reference():
            return c.primary_reference()
    return None


def main() -> None:
    ensure_project_venv()
    args = parse_args()
    from app.generators.keyframe import KeyframeGenerator

    gen = KeyframeGenerator(adapter=args.adapter, scale=args.scale, steps=args.steps)

    # Build a uniform list of (filename, prompt, global_style, negative, reference_url, seed).
    work: list[tuple] = []
    if args.job:
        from app.models import JobRequest

        with open(args.job, encoding="utf-8") as f:
            job = JobRequest.model_validate_json(f.read())
        out_id = job.job_id
        for s in job.ordered_scenes():
            work.append((
                f"scene_{s.sequence:02d}.png", s.keyframe_prompt, job.global_style,
                s.negative_prompt, _scene_reference(job, s), s.seed,
            ))
    else:
        out_id = "quick"
        scenes = [
            f"{args.subject} standing on an empty city street at midnight, wet asphalt, wide shot",
            f"{args.subject} walking through a dark park at night, seen from behind",
            f"{args.subject} inside a dim red-lit stairwell of an old building",
        ]
        for i, prompt in enumerate(scenes, start=1):
            work.append((f"scene_{i:02d}.png", prompt, args.style, None, args.reference, 1000 + i))

    out_dir = os.path.join(args.out_dir, out_id)
    print(f"==> Generating {len(work)} keyframes -> {out_dir}")
    results = []
    for filename, prompt, style, negative, ref, seed in work:
        meta = gen.generate(
            prompt=prompt, out_path=os.path.join(out_dir, filename),
            global_style=style, negative_prompt=negative, reference_url=ref, seed=seed,
        )
        tag = "id-locked" if meta["had_reference"] else "no-character"
        print(f"  {filename}: {meta['seconds']:>5.1f}s  seed={meta['seed']}  {meta['peak_vram_gib']:.1f}GiB  [{tag}]")
        results.append(meta)

    total = sum(r["seconds"] for r in results)
    print(f"\n[OK] {len(results)} keyframes in {total:.1f}s ({total/len(results):.1f}s avg). Eyeball {out_dir}.")
    print("     Identity drifting? raise --scale (0.85) or --adapter plus. Scene ignored? lower --scale.")


if __name__ == "__main__":
    main()
