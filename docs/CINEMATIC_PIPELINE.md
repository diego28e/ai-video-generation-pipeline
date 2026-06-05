# Cinematic Video Pipeline — Real Video Generation (Wan) + Continuity Director

**Status:** Direction v2 · **Owner:** Diego · **Last updated:** 2026-06-05

This document is the **source of truth for the new generation architecture**. It supersedes the
Phase 4–5 "SDXL keyframe → Ken Burns pan/zoom" approach. Read this before changing code; the
other docs (`REQUIREMENTS.md`, `API_CONTRACT.md`, `ROADMAP.md`, `BENCHMARK.md`) have been updated
to point here.

---

## 1. Why we changed direction (the diagnosis)

The shipped pipeline did **not generate video**. Per scene it rendered one **independent SDXL
still** (SDXL base + IP-Adapter), then applied a **Ken Burns pan/zoom** crop animation over that
still, then muxed audio. The only real video model (SVD-XT) was deliberately disabled (it warps
stylized art and is slow). Result: "images with zoom," and characters that drift because every
scene is a fresh, independent generation with no identity lock that actually holds (the IP-Adapter
identity check was never even validated — see `BENCHMARK.md`).

**New goal (unchanged intent, correct means):** real generative video, self-hosted, with
recurring characters that stay recognizable, and cinematic shot grammar (cuts *and* continuous
takes) — comparable in spirit to Veo/Runway but on our own GPU.

---

## 2. The core idea: three independent consistency axes

The old plan's mistake was treating clip-to-clip linking as one binary ("chain the last frame or
not"). Real cinema is mostly **cuts**, with continuity the exception — and blindly chaining the
last frame across a cut produces a visible *morph*, one of the worst-looking generative failures.

The fix: separate the three things that can carry between two clips. A film cut turns some on and
others off — they are **independent**:

1. **Character identity** — "is it the same boy?" Almost always ON, even across a hard cut.
2. **World / location / lighting / style** — "same room, same time of day, same art style?"
   ON within a scene, OFF across a scene change.
3. **Temporal motion continuity** — "does the action physically continue from the exact last
   frame?" ON only inside a continuous take.

"Completely new scene" does **not** mean unconstrained: the boy still looks like the boy (axis 1
stays on) while the room and the motion are brand new (axes 2 & 3 go off). Once the axes are
separated, "chain vs. new" dissolves into a routing decision over these three switches.

---

## 3. Transition taxonomy (the three modes)

Each scene is classified by its relationship to the previous scene:

| Mode | When | Identity | World/location | Temporal | Wan recipe |
|---|---|---|---|---|---|
| **CONTINUOUS** | same shot continuing / match-on-action | ✅ | ✅ | ✅ **chain** | feed prev clip's **last frame** → Wan **I2V** (or **FLF2V** toward a target end anchor) |
| **CUT_SAME_SCENE** | reverse angle, reaction, cutaway — same place/time, new framing | ✅ | ✅ **location anchor** | ❌ no pixel carryover | fresh anchor frame from **character refs + cached location anchor**, then Wan I2V |
| **HARD_CUT** | new location / time jump / new sequence | ✅ | ❌ (deliberately distinct) | ❌ | fresh anchor from **character refs + global_style only**, then Wan I2V |

**Why CUT_SAME_SCENE matters (the subtle middle ground):** the first time the planner sees a
location group, the engine renders **one establishing keyframe** for that location and **caches**
it. Every later shot in the same group is conditioned on that cached anchor *as a reference, not a
pixel continuation* — so it's recognizably the same room with the same light, but a genuine new
shot, not a morph. Hard cuts deliberately skip the location anchor (a cut to a new place *should*
look different).

**Unifying insight:** all three modes reduce to the same final operation —
*"produce a conditioning frame (or frames), then run Wan I2V/FLF2V."* They differ only in **where
the conditioning frame comes from**. That keeps the implementation clean.

---

## 4. The Continuity Director (how the system decides the mode)

A lightweight **planning pass runs before rendering** and assigns a mode to every scene. Decision
is made with **defense in depth**, three tiers:

### Tier 1 — Explicit signal from upstream (authoritative)
The "continue vs. cut" decision is fundamentally *narrative*; the LLM that parses the story into
scenes already has that context. So it is passed as **data**, not guessed at render time. Two new
optional scene fields (see `API_CONTRACT.md`):
- `scene_group_id` — scenes sharing it are the same physical place/time block (a "scene"/location).
- `shot_relation`: `"continue" | "cut"` — within the same group a `cut` becomes CUT_SAME_SCENE;
  across groups a `cut` is HARD_CUT; `continue` becomes CONTINUOUS.

This matches our philosophy: **the LMS owns the semantics; the engine illustrates.**

### Tier 2 — Heuristic fallback (when the signal is absent, or to sanity-check it)
The engine infers a continuity decision from data already in the payload, so it works even if
upstream doesn't populate the fields:
- **Time gap** `next.start − prev.end` — a long narration pause implies a cut; near-zero gap allows continuity.
- **Character-set delta** — `characters_present` changing implies a new shot.
- **Prompt/location similarity** — keyword/embedding similarity of `keyframe_prompt` +
  `narration_excerpt`; high + same characters + small gap → same scene; low → hard cut.

### Tier 3 — Safe default + guardrail
- **Default to a cut when uncertain.** Critical asymmetry: a clean cut where you could have chained
  is barely noticeable; a forced chain across a real cut is catastrophic (visible melt).
- Even when `continue` is requested, the engine **validates** it (same characters, small time gap)
  and **downgrades to a cut + logs** if it doesn't hold. Fail safe toward cutting.

---

## 5. The model stack

- **Video model: Wan 2.2 (14B)** — open quality leader for human subjects (face/skin/hair). Use
  I2V for shots, **FLF2V** (first-last-frame) where we want to interpolate toward a target end
  anchor. (Evaluate the newer Wan 2.7 **R2V / reference-to-video** at the benchmark gate — it is
  built specifically for cross-shot character consistency and may simplify the identity stage.)
- **Identity / face-ID (axis 1):** video-native reference conditioning — **Phantom** or **VACE**
  (one/few reference images preserve identity & wardrobe across shots), or **ConsisID** (face
  adapter). This replaces the weak SDXL IP-Adapter and is locked *in the video model*, not bolted
  onto a still. The exact choice is decided from rendered footage at the benchmark gate.
- **Anchor-frame generation (axes 1+2):** a still generator produces the conditioning frame for
  CUT_SAME_SCENE / HARD_CUT modes (character refs + optional location anchor + `global_style`).
  Could be Wan's own first-frame path or a strong T2I with the face-ID adapter — decided at G2.
- **Assembly:** unchanged — concat scene clips, fetch + mux the supplied ElevenLabs audio, force
  final length == `audio.duration_seconds` (existing `assemble.py` survives).

What is **retired:** `kenburns.py` (pan/zoom fill), the SVD-XT A/B path (`bench_svd.py`), and the
SDXL+IP-Adapter `keyframe.py` as the identity mechanism.

---

## 6. GPU requirements — the L4 must be replaced

The current **L4 (24 GB)** *fits* Wan 14B in VRAM (fp8 ≈ 20 GB; GGUF less) but is far too
**compute-weak** for production: Wan 14B at 720p benchmarks around ~18 s **per frame** on a much
stronger RTX 4090, so an ~80-frame clip is tens of minutes — and the L4 is slower still. This is a
throughput wall, not a VRAM wall.

The old "~30 GPU-hour budget / 5.6 h for 3 videos" math is **void** — it was computed for
SDXL+Ken Burns. Cost is re-baselined on the new GPU at the benchmark gate (Phase B).

**Recommended GCP options (single GPU, serialized jobs):**

| GCP machine type | GPU | VRAM | Notes |
|---|---|---|---|
| `a2-highgpu-1g` | 1× A100 | 40 GB | **Recommended sweet spot** — fp8 14B with headroom |
| `a2-ultragpu-1g` | 1× A100 | 80 GB | More headroom for 720p+ and R2V; pick if quota available |
| `a3-highgpu-1g` | 1× H100 | 80 GB | Fastest wall-clock; highest cost |
| `g2-standard-*` | 1× L4 | 24 GB | **Current — insufficient for Wan 14B at scale** |

> L40S (48 GB) is a great fit but is not a standard GCP SKU; it's the pick if you ever move this to
> a cloud that offers it (e.g. AWS `g6e`). On GCP, A100 is the practical upgrade.

---

## 7. What you (Diego) need to do — prerequisites checklist

These are **human-only steps** that must happen before/while we change code. Do them in order; #1
and #2 have lead time, so start them first.

### ☐ 1. Decide + provision the new GPU VM  *(has lead time — start now)*
- **Pick the tier** from §6. Default recommendation: **`a2-highgpu-1g` (1× A100 40 GB)**. Choose
  `a2-ultragpu-1g` (A100 80 GB) if you want 720p headroom and easy R2V.
- **Request GPU quota** (this can take hours–days to approve):
  GCP Console → **IAM & Admin → Quotas & System Limits** → filter for the GPU
  (e.g. *"NVIDIA A100 GPUs"* / *"NVIDIA A100 80GB GPUs"*) in your target **region** → **Edit Quota**
  → request at least **1**. Approval is required before the VM will boot.
- **Pick a region/zone** where that GPU is actually available (availability varies by zone).
- Keep the VM **off by default** (cost: A100 ≈ several $/hr); we only power it on for renders.

### ☐ 2. Hugging Face access for the Wan models  *(gated — start now)*
- Create/confirm a **Hugging Face account** and generate a **read access token**
  (HF → Settings → Access Tokens).
- **Accept the license** on the Wan model pages you'll use (the Wan 2.2 / 2.1 model repos on HF —
  I'll give you the exact repo IDs when we set up the env). Gated models won't download until the
  license is accepted by your account.
- Have the token ready to put in the VM's `.env` as `HF_TOKEN` (never commit it).

### ☐ 3. Disk space on the VM
- Wan 14B weights + work dir need room. Provision a **≥ 250 GB SSD persistent disk** (the current
  100 GB is tight once weights + per-job keyframes/clips accumulate).

### ☐ 4. Give me the real production job JSON  *(gitignored)*
- The committed `samples/the_weight.template.json` is **mock** (placeholder URLs). For a real
  benchmark/render I need the **production payload with live CloudFront URLs** (real `audio.url`,
  real `characters[].reference_images[].url`).
- Save it locally as **`samples/the_weight.json`** — that path is already gitignored, so it stays
  out of version control.

### ☐ 5. (Later, not blocking) AWS delivery creds
- For Phase D delivery (S3 upload + CloudFront URL) we'll need the scoped IAM key/secret in `.env`.
  Not needed for the benchmark — flag it now so it's not a surprise later.

> Once #1–#4 are done, I can build the upgraded environment and the Wan benchmark harness, render
> a few real beats in all three transition modes, and you judge from actual footage before we
> commit to the full generator rewrite.

---

## 8. How this maps to the phases

See `ROADMAP.md` for the re-phased plan. In short: **Phase A** (GPU + Wan env, new G1) →
**Phase B** (benchmark Wan I2V/FLF2V + identity + the three transition modes on real assets, new
G2 — locks the stack with footage + real cost) → **Phase C** (rewrite the generator: Continuity
Director + location-anchor cache + Wan recipes, behind the existing `Generator` protocol) →
**Phase D** (full `the-weight` render + identity gate G4, then S3/CloudFront delivery).

---

## 9. Phase A/B runbook (the scripts to run on the A100)

Built and syntax-checked locally; they run on the VM once prerequisites §7 are done.

```bash
# Phase A — environment (after install_system_deps.sh has Python 3.12 + ffmpeg)
bash scripts/setup_wan_env.sh                  # venv + torch(cu121) + base + requirements-wan.txt
export HF_TOKEN=<token>                         # or: hf auth login  (Wan weights are gated)

# Gate G1' — prove the Wan install end-to-end (small 1.3B model, fast/cheap)
.venv/bin/python scripts/verify_wan.py          # -> outputs/g1_wan.mp4
.venv/bin/python -m pip freeze > requirements.lock.txt   # freeze once green

# Gate G2' — benchmark the real target on REAL assets (drop the production JSON first)
.venv/bin/python scripts/bench_wan.py --job samples/the_weight.json          # I2V, 480p, offload
.venv/bin/python scripts/bench_wan.py --job samples/the_weight.json --resolution 720p
.venv/bin/python scripts/bench_wan.py --flf2v --image first.png --last-image last.png  # CONTINUOUS lever
```

`bench_wan.py` reports render time/clip, peak VRAM, and GPU-h/video — the numbers that lock the
stack and replace the void ~30 GPU-h budget. Files: [`requirements-wan.txt`](../requirements-wan.txt),
[`scripts/setup_wan_env.sh`](../scripts/setup_wan_env.sh),
[`scripts/verify_wan.py`](../scripts/verify_wan.py), [`scripts/bench_wan.py`](../scripts/bench_wan.py).

> Model IDs verified against the diffusers Wan docs (2026-06): I2V `Wan-AI/Wan2.2-I2V-A14B-Diffusers`,
> FLF2V `Wan-AI/Wan2.1-FLF2V-14B-720P-diffusers`, smoke `Wan-AI/Wan2.1-T2V-1.3B-Diffusers`. Wan 2.7
> R2V (reference-to-video) is the candidate to A/B for identity at G2' if it's available in diffusers
> by then.

### 9b. Stopgap: testing on the current 24 GB L4 (while A100 quota is pending)

The L4 can validate the **stack, motion quality, and pipeline logic** now — but **not** with the
14B. A single Wan 14B transformer in bf16 is ~28 GB (> the L4's 24 GB), and the 2.2 14B is a
two-expert MoE, so ordinary CPU-offload can't make it fit. Use the purpose-built low-VRAM model
instead: **Wan 2.2 TI2V-5B** (`Wan-AI/Wan2.2-TI2V-5B-Diffusers`), which runs on 24 GB with offload.

Levers for speed on a weak GPU: **smaller model + 480p + fewer frames + fewer steps.** Clip length
is fixed per call (~5 s); a "20 s" test = ~4 chained clips, so reduce clip *count*, not "length".

```bash
# Fast motion/stack test on the L4 (T2V via WanPipeline — already supported by verify_wan.py).
# If the 5B fails to load on diffusers 0.35.1, install diffusers from source (see requirements-wan.txt).
.venv/bin/python scripts/verify_wan.py \
    --model Wan-AI/Wan2.2-TI2V-5B-Diffusers \
    --height 480 --width 832 --num-frames 49 --fps 24 --steps 25 --flow-shift 3.0
```

Expect the L4 to be ~2–4× slower than a 4090 (5B @720p is ~9 min/5 s on a 4090; far faster at
480p / fewer frames). **What this does NOT cover:** real I2V identity hold and final 14B quality —
those stay gated on the A100 at G2'. Treat the L4 run as de-risking the code, not a quality verdict.
