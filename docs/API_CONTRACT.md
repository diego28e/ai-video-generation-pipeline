# API Contract — Engine ⇄ Orchestrator (Nest.js)

**Status:** Draft **v1.1** (Phase 2). This is the interface boundary. The Nest.js LMS implements the
client side; this engine implements the server side. Versioned via `schema_version` in the body.

The original FRD's scene JSON has been **extended for identity consistency** and **generalized
away from SVD-specific fields**. Differences are noted inline.

---

## Auth

- Inbound (Nest.js → engine): `Authorization: Bearer <ENGINE_API_TOKEN>` **and** an HMAC
  signature header `X-Signature: sha256=<hex>` over the raw body using a shared secret.
- Outbound (engine → Nest.js webhooks): same HMAC scheme so Nest.js can trust the callback.
- All endpoints require the bearer token; bodies are HMAC-verified.

---

## `POST /jobs` — submit a render job

Returns **202 Accepted** immediately.

### Request body

This is the canonical **v1.1** payload (LMS team's structure + required fixes), using the real
`the-weight` asset paths.

```jsonc
{
  "schema_version": "1.1",
  "job_id": "f7c1e0a2-...-90",                 // idempotency key; reuse the SAME id on retry

  "story": {
    "story_id": "...",
    "slug": "the-weight",                      // used in asset/output paths
    "title": "The Weight",
    "language": "en",
    "cefr_level": "B1"                          // metadata; ignored by the engine
  },

  // Audio is the MASTER CLOCK. Engine muxes it in and forces final video length == duration_seconds.
  // Engine does NOT generate or re-time audio. Lives directly in the story directory.
  "audio": {
    "url": "https://d35ivcpjrjjgk.cloudfront.net/lesson-content/Stories-podcast/the-weight/The_weight.mp3",
    "duration_seconds": 299.42                  // authoritative total length (from ElevenLabs)
  },

  // Delivery target.  s3_key = key_prefix + "/" + filename
  //                   video_url = {CLOUDFRONT_BASE_URL} + "/" + s3_key
  "output": {
    "bucket": "ocw-lesson-content",
    "key_prefix": "lesson-content/Stories-podcast/the-weight/video",
    "aspect_ratio": "16:9",
    "container": "mp4",
    "video_codec": "h264"
  },

  "global_style": "Painterly storybook illustration, warm muted palette, 1950s small-town.",

  // Character bible — the basis for identity consistency. The engine conditions keyframes on the
  // primary reference image via IP-Adapter. It uses the final character png (NOT the seed pics).
  "characters": [
    {
      "id": "the-boy",
      "name": "The Boy",
      "subject_type": "person",                 // person|object|animal — picks the identity technique
      "description": "An ~8-year-old boy carrying heavy bags home at night.",
      "appearance_prompt": "An 8-year-old boy, slight build, short dark hair, oversized grey coat...",
      "reference_images": [
        { "url": "https://d35ivcpjrjjgk.cloudfront.net/lesson-content/Stories-podcast/the-weight/characters/the-boy.png", "is_primary": true }
      ]
    }
  ],

  "scenes": [
    {
      "sequence": 1,
      "start_seconds": 0.0,                      // window on the audio master clock
      "end_seconds": 12.4,                       // engine fills this EXACT duration
      "narration_excerpt": "I finished work late that night...",  // optional; for logs/context
      "keyframe_prompt": "Wide establishing shot of an empty city street past midnight...",
      "negative_prompt": "blurry, deformed, text, watermark",     // optional
      "characters_present": [],                  // IDs MUST exist in characters[]; use [] when no character is shown
      "camera_motion": "push_in",                // applied at the Ken Burns fill stage — see "camera_motion" below
      "motion_strength": 0.25,                   // 0..1 -> SVD motion_bucket_id (~round(1 + s*254))
      "seed": null                               // optional; engine generates + records if null
    }
  ],

  "callback": {
    "url": "https://lms-api.onecultureworld.com/webhooks/story-video",
    "events": ["scene_completed", "job_completed", "job_failed", "idle"]
  }
}
```

Auth is via headers (see **Auth** above), not in the body.

### Asset layout (authoritative)

Everything for a story lives under `lesson-content/Stories-podcast/{slug}/` (CloudFront base
`https://d35ivcpjrjjgk.cloudfront.net`):

```
lesson-content/Stories-podcast/the-weight/
├── The_weight.mp3                                  # narration — the audio master clock
├── characters/
│   ├── the-boy.png                                 # character reference (engine USES this)
│   └── seeds/
│       └── narrator-seed-1780207690375.png         # original seed pics (engine does NOT use)
└── video/
    └── final.mp4                                   # engine output (key_prefix + filename)
```

So `audio.url`, `characters[].reference_images[].url`, and the output `video_url` are all just
`{CLOUDFRONT_BASE_URL}/{key}` for the appropriate key under that story directory.

### `camera_motion` — keep it (we use it, just not via SVD)

**Decision: keep the field.** SVD-XT itself cannot do directed camera moves (it only has a global
`motion_strength`). The engine instead applies `camera_motion` at the **duration-fill / Ken Burns
stage**: after the short SVD clip, we pan/zoom across the keyframe to fill the scene's exact
`start..end` window, in the requested direction. Supported values:

| value | effect during fill |
|-------|--------------------|
| `static` | hold (subtle drift only) |
| `pan_left` / `pan_right` | horizontal pan across the frame |
| `tilt_up` / `tilt_down` | vertical pan |
| `push_in` / `pull_out` | slow zoom in / out |

`motion_strength` is separate: it drives the **SVD animation** amount (0..1 → `motion_bucket_id`).
Unknown `camera_motion` values fall back to `static`.

> **Timing (v1.1, updated):** scenes are **narration anchors** — `start_seconds`/`end_seconds`
> are when the phrase is spoken. **Silent gaps between phrases are allowed** (real narration has
> pauses); the engine derives a continuous *visual* window per scene as
> `[scene.start → next_scene.start)`, fills the lead-in from 0, and extends the last scene to
> `audio.duration_seconds`. Rules the engine enforces (else `400`): `start_seconds` strictly
> increasing, no **overlap** (`end ≤ next.start`), first start `≥ 0`, last start `< audio.duration`.
> (Earlier drafts required gapless coverage — that was too strict for real narration and is relaxed.)

### Responses
- `202 Accepted` → `{ "job_id": "lms-story-8471", "status": "queued", "queue_position": 2 }`
- `200 OK` (idempotent re-submit of a known `job_id`) → current status, no re-queue.
- `400` invalid payload · `401` auth failure · `409` conflicting `job_id` with different body.

---

## `GET /status` — engine health & capacity (Nest.js polls this to pace work)

```jsonc
{
  "state": "idle",                  // "idle" | "busy"
  "current_job": null,              // or { "job_id": "...", "sequence": 12, "scenes_total": 35 }
  "queue_depth": 0,
  "gpu": { "name": "NVIDIA L4", "vram_total_mb": 24564, "vram_used_mb": 812 },
  "cumulative_gpu_seconds": 18243,  // toward the ~30h (108000s) budget
  "uptime_seconds": 4012,
  "schema_version": "1.1"
}
```

---

## `GET /jobs/{job_id}` — per-job progress

```jsonc
{
  "job_id": "lms-story-8471",
  "status": "rendering",            // queued | rendering | uploading | done | failed
  "scenes_done": 20,
  "scenes_total": 35,
  "eta_seconds": 5400,
  "gpu_seconds_used": 7200,
  "error": null
}
```

---

## Webhooks (engine → Nest.js)

All POSTed to `callback.url` (`https://lms-api.onecultureworld.com/webhooks/story-video`),
HMAC-signed (`X-Signature`). The `type` matches the tokens in `callback.events`.

### `scene_completed` (optional, for progress UX)
```jsonc
{ "type": "scene_completed", "job_id": "f7c1e0a2-...-90", "sequence": 12, "scenes_total": 35 }
```

### `job_completed`
```jsonc
{
  "type": "job_completed",
  "job_id": "f7c1e0a2-...-90",
  "status": "done",
  "video_url": "https://d35ivcpjrjjgk.cloudfront.net/lesson-content/Stories-podcast/the-weight/video/final.mp4",
  "s3_key": "lesson-content/Stories-podcast/the-weight/video/final.mp4",
  "bucket": "ocw-lesson-content",
  "duration_seconds": 299.42,                         // == audio length
  "gpu_seconds_used": 12880,
  "seeds": { "1": 12345, "2": 67890 }                // for reproducibility
}
```

### `job_failed`
```jsonc
{ "type": "job_failed", "job_id": "...", "status": "failed", "error": "OOM at scene 31", "scenes_done": 30 }
```

### `idle` (queue drained) — enables "email me to shut down"
```jsonc
{ "type": "idle", "queue_depth": 0, "cumulative_gpu_seconds": 18243, "idle_since": "2026-05-30T16:40:00Z" }
```
> Nest.js reacts to this by emailing Diego to power off the VM (or by triggering an automated stop).

---

## Notes for the Nest.js (orchestrator) side — your responsibilities

1. **Pacing:** poll `GET /status`; only send the next job when appropriate (the engine serializes anyway, but pacing keeps the queue shallow and recovery cheap).
2. **Busy awareness:** treat `state == "busy"` or a non-empty `current_job` as "engine occupied."
3. **Idle handling:** on the `idle` event, send Diego the shutdown email / trigger stop.
4. **Idempotency:** reuse the same `job_id` on retries so the engine dedupes.
5. **Reference images:** resolved — characters are hosted under
   `.../the-weight/characters/<id>.png` (the engine fetches by URL; the `characters/seeds/` pics
   are not used by the engine).
6. **Audio + timing:** you own the ElevenLabs word-timestamp → scene alignment. Send a fetchable
   `audio.url`, the authoritative `audio.duration_seconds`, and per-scene
   `start_seconds`/`end_seconds` that satisfy the timing invariant above. The engine consumes
   audio and timings; it does not generate or re-align them.

---

# Reconciliation with the LMS team's proposal (v1.1)

The LMS team proposed a payload that matches this contract's backbone. **Accepted as the base**,
with the following required adjustments before we finalize v1.1. Adopt their nested structure
(`story` / `audio` / `output` / `characters` / `scenes` / `callback{url,events}`,
`schema_version`, `narration_excerpt`, `subject_type`, `reference_images[]{url,is_primary}`).

## Must-fix
1. **`camera_motion` cannot be done by SVD-XT.** SVD-XT only takes a general `motion_strength`
   (→ `motion_bucket_id`); it cannot do directed moves like `pan_left`. We honor `camera_motion`
   at the **duration-fill (Ken Burns) stage** — we pan/zoom the keyframe to fill the scene window.
   Keep the field, but understand it drives the fill, not the video model. Suggested enum:
   `pan_left|pan_right|push_in|pull_out|static|tilt_up|tilt_down`.
2. **`characters_present` must only contain IDs defined in `characters[]`.** The sample lists
   `"the-narrator"`, who isn't defined and (being first-person/unseen) usually has no reference.
   Rule: the engine **rejects (400)** unknown IDs. For unseen narrator scenes, send `[]`.
3. **Auth is missing.** Not in the body — via headers: inbound `Authorization: Bearer <token>` +
   `X-Signature: sha256=<hmac of raw body>`; outbound webhooks signed the same way. Required since
   both endpoints are on the public internet.
4. **`callback.url` — resolved.** Confirmed value:
   `https://lms-api.onecultureworld.com/webhooks/story-video` (the earlier sample had a pasted
   markdown link spanning two domains). One clean absolute URL.

## Confirm
5. **Timing (relaxed in v1.1):** scenes are narration anchors; **gaps/pauses are OK**, overlaps are
   not. Starts strictly increase; the engine derives continuous visual windows and fills gaps. Your
   LLM can emit phrase-aligned scenes directly (like the 98-scene "the-weight" mapping) — no need to
   pad to gapless. See the Timing note above.
6. **Key/URL mapping (now confirmed):** `s3_key = output.key_prefix + "/" + filename`;
   `video_url = {CLOUDFRONT_BASE_URL}/{s3_key}`. e.g. final →
   `https://d35ivcpjrjjgk.cloudfront.net/lesson-content/Stories-podcast/the-weight/video/final.mp4`.
7. **`motion_strength` mapping:** 0..1 float → `motion_bucket_id` (≈ `round(1 + strength*254)`),
   default 0.5 ≈ 127.

## Nice (optional)
- `narration_excerpt` — keep; useful for logs and (later) prompt enrichment. Engine doesn't require it.
- `subject_type` (person/object/animal) — keep; lets us pick the identity technique per character.
- `cefr_level` / `language` — harmless metadata; ignored by the engine.
