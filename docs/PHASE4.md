# Phase 4 — Identity-locked keyframes (Stage A)

Productionizes what `bench_identity.py` proved: SDXL + IP-Adapter keyframes that keep a character
consistent across scenes, in the job's `global_style`. This is a **GPU step — run on the VM.**

- Module: `app/generators/keyframe.py` (`KeyframeGenerator`) — the engine will call this in Phase 5.
- Script: `scripts/gen_keyframes.py` — standalone verification.

## How identity is resolved per scene
- For each scene, the engine picks the **first `characters_present` id** that is defined in
  `characters[]` and has a reference image, and conditions the keyframe on its **primary** reference
  (IP-Adapter at `--scale`, default 0.7).
- Scenes with **no character** (e.g. establishing shots) generate from text + `global_style` only
  (IP-Adapter scale forced to 0). This story's narrator is first-person/unseen → those scenes use `[]`.
- Multi-character scenes (>1 present): v1 uses the first present character's reference and logs it;
  true multi-subject identity is a later enhancement. (`the-weight` is 0-or-1 character per scene.)
- The resolved **seed** is returned/recorded for reproducibility.

## Verify on the VM (inside the venv)

```bash
bash scripts/dev_update.sh   # pull latest

# Quick smoke (3 demo scenes, one reference) — fastest sanity check:
.venv/bin/python scripts/gen_keyframes.py \
  --reference https://<your-cdn>/.../characters/the-boy.png \
  --style "Painterly storybook illustration, warm muted palette, 1950s small-town"

# Full contract: copy the template, put in your REAL audio/character URLs (this copy is gitignored):
cp samples/the_weight.template.json samples/the_weight.json
#   edit samples/the_weight.json -> set characters[].reference_images[].url + audio.url
.venv/bin/python scripts/gen_keyframes.py --job samples/the_weight.json
```

Outputs land in `outputs/keyframes/<job_id or quick>/scene_NN.png` with a per-scene line
(`seconds`, `seed`, `peak VRAM`, `id-locked` vs `no-character`).

## What to report back
- Do scenes 2–6 (the boy) look like the **same** boy, in the **painterly** style?
- The per-keyframe **seconds** and **peak VRAM** (sanity vs the ~7.5 s / ~13 GiB we measured).
- If identity drifts in the painterly style: bump `--scale 0.85` or `--adapter plus`. If scenes look
  like the reference but ignore the prompt: lower `--scale` (e.g. 0.5).

## Notes
- IP-Adapter weights (`h94/IP-Adapter`) are **not gated** — no HF token needed.
- SDXL runs on `cuda` with **no offload** (≈6× faster than offload, ~13 GiB — fits the 22 GiB L4).
- Real job files belong in `samples/` (gitignored); only `*.template.json` is committed.
