#!/usr/bin/env python3
"""
Phase 1 / Gate G1 (part 1) — GPU verification.

Confirms the venv's torch sees the L4, reports VRAM, and runs a real CUDA
computation. Exits non-zero on any failure so it can gate CI / setup scripts.

Run on the VM:  python scripts/verify_gpu.py
"""
from __future__ import annotations

import sys
import time


def fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"\n[FAIL] {msg}")
    sys.exit(1)


def main() -> None:
    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        fail(f"could not import torch: {exc!r}")

    print("=== Torch / CUDA ===")
    print(f"torch version      : {torch.__version__}")
    print(f"compiled CUDA      : {torch.version.cuda}")
    print(f"cudnn version      : {torch.backends.cudnn.version()}")

    if not torch.cuda.is_available():
        fail("torch.cuda.is_available() == False (no usable GPU in this venv)")

    count = torch.cuda.device_count()
    print(f"cuda devices       : {count}")
    if count < 1:
        fail("no CUDA devices reported")

    dev = torch.device("cuda:0")
    name = torch.cuda.get_device_name(0)
    cap = torch.cuda.get_device_capability(0)
    props = torch.cuda.get_device_properties(0)
    total_gb = props.total_memory / (1024**3)

    print("\n=== Device 0 ===")
    print(f"name               : {name}")
    print(f"compute capability : {cap[0]}.{cap[1]}")
    print(f"total VRAM         : {total_gb:.1f} GiB")

    # Sanity: warn if this isn't the expected ~24GB L4 (informational, not fatal).
    if total_gb < 20:
        print(f"[warn] VRAM {total_gb:.1f} GiB is below the expected ~24 GiB (L4).")

    # --- Real GPU compute: fp16 matmul, the precision the pipeline will use. ---
    print("\n=== CUDA compute (fp16 matmul) ===")
    try:
        torch.cuda.synchronize()
        a = torch.randn((4096, 4096), device=dev, dtype=torch.float16)
        b = torch.randn((4096, 4096), device=dev, dtype=torch.float16)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(10):
            c = a @ b
        torch.cuda.synchronize()
        dt = (time.perf_counter() - t0) / 10
        peak = torch.cuda.max_memory_allocated(dev) / (1024**2)
        print(f"4096x4096 fp16 matmul: {dt*1000:.2f} ms/iter   (peak alloc {peak:.0f} MiB)")
        assert torch.isfinite(c).all(), "matmul produced non-finite values"
    except Exception as exc:  # noqa: BLE001
        fail(f"CUDA compute failed: {exc!r}")

    print("\n[OK] GPU verification passed.")


if __name__ == "__main__":
    main()
