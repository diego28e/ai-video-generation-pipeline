"""Stage A — identity-locked keyframe generation (SDXL + IP-Adapter).

This is the consistency lever: each scene's keyframe is conditioned on a character's
full-appearance reference image (validated in Phase 2 / bench_identity), with the job's
global_style applied for world/style consistency. Phase 5's CinematicGenerator calls this,
then animates the keyframe with SVD-XT and fills the scene's exact audio window.

GPU-only (SDXL fp16 on cuda, no offload — measured ~6x faster than offload and well within 22 GiB).
Imports of torch/diffusers are lazy so this module can be imported on a non-GPU box.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

log = logging.getLogger("engine.keyframe")

SDXL_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"
IP_ADAPTERS = {
    # adapter name -> (hf subfolder, weight filename). 'base' is the robust default.
    "base": ("sdxl_models", "ip-adapter_sdxl.bin"),
    "plus": ("sdxl_models", "ip-adapter-plus_sdxl_vit-h.safetensors"),
}
DEFAULT_NEGATIVE = (
    "blurry, deformed, disfigured, extra limbs, extra fingers, mutated hands, "
    "text, watermark, signature, low quality, jpeg artifacts"
)


class KeyframeGenerator:
    """Loads SDXL + IP-Adapter once (lazily) and renders identity-locked keyframes."""

    def __init__(
        self,
        adapter: str = "base",
        scale: float = 0.7,
        steps: int = 30,
        width: int = 1024,
        height: int = 576,
        model_id: str = SDXL_MODEL,
    ) -> None:
        if adapter not in IP_ADAPTERS:
            raise ValueError(f"unknown adapter {adapter!r}; choose from {list(IP_ADAPTERS)}")
        self.adapter = adapter
        self.scale = scale
        self.steps = steps
        self.width = width
        self.height = height
        self.model_id = model_id
        self._pipe = None
        self._blank = None
        self._ref_cache: dict[str, object] = {}

    def ensure_loaded(self) -> None:
        if self._pipe is not None:
            return
        import torch
        from diffusers import StableDiffusionXLPipeline
        from PIL import Image

        t0 = time.perf_counter()
        pipe = StableDiffusionXLPipeline.from_pretrained(
            self.model_id, torch_dtype=torch.float16, variant="fp16", use_safetensors=True
        )
        pipe.to("cuda")
        subfolder, weight_name = IP_ADAPTERS[self.adapter]
        pipe.load_ip_adapter("h94/IP-Adapter", subfolder=subfolder, weight_name=weight_name)
        pipe.set_ip_adapter_scale(self.scale)
        self._pipe = pipe
        self._blank = Image.new("RGB", (224, 224), (0, 0, 0))  # used (at scale 0) for no-character scenes
        log.info(
            "keyframe pipeline loaded in %.1fs (adapter=%s, scale=%.2f, %dx%d)",
            time.perf_counter() - t0, self.adapter, self.scale, self.width, self.height,
        )

    def _reference(self, url: str):
        if url not in self._ref_cache:
            from diffusers.utils import load_image

            self._ref_cache[url] = load_image(url)
        return self._ref_cache[url]

    def generate(
        self,
        *,
        prompt: str,
        out_path: str,
        global_style: str = "",
        negative_prompt: Optional[str] = None,
        reference_url: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> dict:
        """Render one keyframe. Returns metadata incl. the resolved seed (for reproducibility)."""
        self.ensure_loaded()
        import torch

        if seed is None:
            seed = int.from_bytes(os.urandom(4), "big")
        generator = torch.Generator(device="cuda").manual_seed(seed)

        full_prompt = f"{prompt}, {global_style}".strip().rstrip(",") if global_style else prompt
        negative = negative_prompt or DEFAULT_NEGATIVE

        if reference_url:
            ip_image = self._reference(reference_url)
            self._pipe.set_ip_adapter_scale(self.scale)
        else:
            # No character in this scene: neutralize identity, keep global style/text only.
            ip_image = self._blank
            self._pipe.set_ip_adapter_scale(0.0)

        torch.cuda.reset_peak_memory_stats()
        t0 = time.perf_counter()
        image = self._pipe(
            prompt=full_prompt,
            negative_prompt=negative,
            ip_adapter_image=ip_image,
            width=self.width,
            height=self.height,
            num_inference_steps=self.steps,
            generator=generator,
        ).images[0]
        seconds = time.perf_counter() - t0
        peak = torch.cuda.max_memory_allocated() / (1024**3)

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        image.save(out_path)
        return {
            "seed": seed,
            "path": out_path,
            "seconds": round(seconds, 2),
            "peak_vram_gib": round(peak, 2),
            "had_reference": bool(reference_url),
        }
