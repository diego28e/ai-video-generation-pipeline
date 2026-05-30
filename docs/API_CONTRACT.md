# API Contract — Engine ⇄ Orchestrator (Nest.js)

**Status:** Draft v1 (Phase 0). This is the interface boundary. The Nest.js LMS implements the
client side; this engine implements the server side. Versioned via the `X-Contract-Version` header.

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

```jsonc
{
  "job_id": "lms-story-8471",            // idempotency key; engine dedupes on this
  "story_id": "8471",
  "output_spec": {
    "resolution": "1024x576",            // engine may clamp to the model's native size
    "container": "mp4"
  },
  "global_style": "cinematic 35mm film, moody teal-orange grade, shallow depth of field, volumetric light",

  // NEW: character bible — the basis for identity consistency
  "characters": [
    {
      "character_id": "alice",
      "appearance_prompt": "young woman, short auburn hair, green wool coat, freckles",
      "reference_image_url": "https://.../alice_ref.png"  // optional but strongly recommended
    }
  ],

  "scenes": [
    {
      "scene_sequence": 1,
      "characters_present": ["alice"],            // which characters must stay consistent here
      "image_generation_prompt": "wide shot, a dark rainy cyberpunk street corner, neon reflections",
      "negative_prompt": "blurry, deformed hands, text, watermark",
      "camera_motion": "slow push in",            // REPLACES free-text video_motion_prompt
      "motion_strength": 0.5,                      // REPLACES motion_bucket_id; 0..1, mapped per-model
      "duration_seconds": 3.0,                     // REPLACES fixed 25-frame/8fps
      "seed": null                                 // optional; engine generates+records if null
    }
  ],

  "callback": {
    "webhook_url": "https://lms.example.com/genai/callbacks",
    "secret_ref": "managed-by-engine-env"          // shared secret identifier, not the secret itself
  },
  "delivery": {
    "s3_bucket": "lms-genai-videos",
    "s3_prefix": "stories/8471/"
  }
}
```

### Responses
- `202 Accepted` → `{ "job_id": "lms-story-8471", "status": "queued", "queue_position": 2 }`
- `200 OK` (idempotent re-submit of a known `job_id`) → current status, no re-queue.
- `400` invalid payload · `401` auth failure · `409` conflicting `job_id` with different body.

---

## `GET /status` — engine health & capacity (Nest.js polls this to pace work)

```jsonc
{
  "state": "idle",                  // "idle" | "busy"
  "current_job": null,              // or { "job_id": "...", "scene": 12, "scenes_total": 96 }
  "queue_depth": 0,
  "gpu": { "name": "NVIDIA L4", "vram_total_mb": 24564, "vram_used_mb": 812 },
  "cumulative_gpu_seconds": 18243,  // toward the ~70h (252000s) budget
  "uptime_seconds": 4012,
  "contract_version": "1"
}
```

---

## `GET /jobs/{job_id}` — per-job progress

```jsonc
{
  "job_id": "lms-story-8471",
  "status": "rendering",            // queued | rendering | uploading | done | failed
  "scenes_done": 40,
  "scenes_total": 96,
  "eta_seconds": 5400,
  "gpu_seconds_used": 7200,
  "error": null
}
```

---

## Webhooks (engine → Nest.js)

All POSTed to `callback.webhook_url`, HMAC-signed (`X-Signature`).

### Per-scene (optional, for progress UX)
```jsonc
{ "type": "scene.completed", "job_id": "...", "scene_sequence": 12, "scenes_total": 96 }
```

### Job completed
```jsonc
{
  "type": "job.completed",
  "job_id": "lms-story-8471",
  "status": "done",
  "video_url": "s3://lms-genai-videos/stories/8471/final.mp4",
  "scene_clip_urls": [ "s3://.../scene_001.mp4" ],   // optional
  "gpu_seconds_used": 12880,
  "seeds": { "1": 12345, "2": 67890 }                // for reproducibility
}
```

### Job failed
```jsonc
{ "type": "job.failed", "job_id": "...", "status": "failed", "error": "OOM at scene 81", "scenes_done": 80 }
```

### Idle (queue drained) — enables "email me to shut down"
```jsonc
{ "type": "engine.idle", "queue_depth": 0, "cumulative_gpu_seconds": 18243, "idle_since": "2026-05-30T16:40:00Z" }
```
> Nest.js reacts to this by emailing Diego to power off the VM (or by triggering an automated stop).

---

## Notes for the Nest.js (orchestrator) side — your responsibilities

1. **Pacing:** poll `GET /status`; only send the next job when appropriate (the engine serializes anyway, but pacing keeps the queue shallow and recovery cheap).
2. **Busy awareness:** treat `state == "busy"` or a non-empty `current_job` as "engine occupied."
3. **Idle handling:** on `engine.idle`, send Diego the shutdown email / trigger stop.
4. **Idempotency:** reuse the same `job_id` on retries so the engine dedupes.
5. **Reference images:** host character reference images somewhere the engine can fetch (S3 with a readable URL is fine), or we define an upload endpoint — **open decision**.
