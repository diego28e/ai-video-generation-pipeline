"""GPU status reporting. Degrades gracefully when torch/CUDA is absent (Phase 3, local)."""
from __future__ import annotations

from typing import Optional, TypedDict


class GpuInfo(TypedDict):
    name: Optional[str]
    vram_total_mb: Optional[int]
    vram_used_mb: Optional[int]


def gpu_status() -> GpuInfo:
    try:
        import torch

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            return {
                "name": torch.cuda.get_device_name(0),
                "vram_total_mb": int(total / (1024 * 1024)),
                "vram_used_mb": int((total - free) / (1024 * 1024)),
            }
    except Exception:
        pass
    return {"name": None, "vram_total_mb": None, "vram_used_mb": None}
