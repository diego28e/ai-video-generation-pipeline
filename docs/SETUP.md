# VM Setup Runbook — Phase 1 (Gate G1)

Run these on the **GCP VM** (Ubuntu 24.04, NVIDIA L4, driver 580). They cannot be
run on a non-GPU machine. Goal: a reproducible venv whose torch sees the GPU, plus a
one-image generation smoke test. **G1 passes when both verification scripts succeed.**

## Prerequisites
- VM is on, you're SSH'd in, and the repo is cloned/pulled into the working dir.
- `nvidia-smi` shows the L4 (the system deps script will check this).

## Steps

```bash
# From the project root on the VM:

# 1. System packages (sudo): ffmpeg, venv toolchain, build tools + GPU check
bash scripts/install_system_deps.sh

# 2. Create the venv and install torch(cu121) + requirements, then verify GPU
bash scripts/setup_env.sh

# 3. Activate the venv for any subsequent commands
source .venv/bin/activate

# 4. Capture the exact reproducible lockfile (do this ONLY after step 2 passed)
pip freeze > requirements.lock.txt

# 5. Full G1 keyframe smoke test (downloads SDXL ~7GB on first run)
python scripts/verify_keyframe.py
```

## G1 acceptance checklist
- [ ] `scripts/verify_gpu.py` prints `[OK] GPU verification passed.`
  - device name is **NVIDIA L4**, VRAM ~**24 GiB**, compiled CUDA **12.1**.
- [ ] `scripts/verify_keyframe.py` prints `[OK]` and writes `outputs/g1_keyframe.png`.
  - note the reported **render time** and **peak VRAM** — these feed the G2 budget math.
- [ ] `requirements.lock.txt` committed (the true reproducible artifact).

## Notes
- **No `--break-system-packages`.** Everything lives in `.venv`; system Python is untouched.
- If torch fails to see the GPU, do **not** patch around it — re-check driver/CUDA first and
  report back; the cu121 pins in `setup_env.sh` are the only thing to adjust.
- The first keyframe run is slow due to the model download; the *render time* (not total
  wall-clock) is the number that matters for budgeting.
- Bring the lockfile back into the repo so the next VM (or the future V100 box) reproduces
  the exact environment.
