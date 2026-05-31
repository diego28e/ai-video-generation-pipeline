# VM Setup Runbook (Phase 1 / Gate G1)

Run on the **GCP VM** (Ubuntu 24.04, NVIDIA L4, driver 580). Cannot run on a non-GPU box.

**Prerequisite:** get the code on the VM via GitHub — see [`WORKFLOW.md`](WORKFLOW.md). The
recommended location is `~/ai-video-generation-pipeline`. Run everything below from that directory.

> **Golden rule:** every Python command uses the venv interpreter **explicitly** —
> `.venv/bin/python ...` — so we never hit system Python by accident. The scripts also
> self-check and **refuse to run** outside the venv. Activation (`source .venv/bin/activate`)
> is optional and only a convenience.

---

## 0. (Once) clean up the accidental system install

Earlier, `diffusers/transformers/accelerate` got installed into user site-packages via
`--break-system-packages`. A venv ignores user site-packages, so this is not fatal — but remove
it to avoid confusion:

```bash
# Run with SYSTEM python on purpose here (this targets ~/.local, not the venv):
python3 -m pip uninstall -y diffusers transformers accelerate || true
```

Going forward, never use `--break-system-packages`. Everything lives in `.venv`.

---

## 1. System packages (sudo)

```bash
bash scripts/install_system_deps.sh
```
✓ You should see `nvidia-smi` print the **NVIDIA L4** and an `ffmpeg` version line.

## 2. Create the venv + install torch(cu121) + requirements

```bash
bash scripts/setup_env.sh
```
✓ It prints `==> Using interpreter: .../.venv/bin/python`, installs **torch 2.5.1+cu121**
(matching your verified stack), then runs the GPU check automatically.
✓ Ends with `[OK] GPU verification passed.`

If you ever want to re-run the GPU check by hand:
```bash
.venv/bin/python scripts/verify_gpu.py
```

## 3. Freeze the reproducible lockfile (only after step 2 passed)

```bash
.venv/bin/python -m pip freeze > requirements.lock.txt
```
This is the **true** reproducible artifact — commit it.

## 4. Full G1 keyframe smoke test (downloads SDXL ~7GB first run)

```bash
mkdir -p outputs   # safety: ensures the tee logfile target exists
.venv/bin/python scripts/verify_keyframe.py | tee outputs/g1_keyframe.txt
```
✓ Prints `[OK]`, writes `outputs/g1_keyframe.png`, and reports **render time** + **peak VRAM**.

---

## G1 acceptance checklist
- [ ] `verify_gpu.py` → `[OK]`, device **NVIDIA L4**, ~**22–24 GiB**, CUDA **12.1**.
- [ ] `verify_keyframe.py` → `[OK]`, image written, render time + VRAM recorded.
- [ ] `requirements.lock.txt` committed.

**G1 status (recorded):** ✅ PASSED — L4 / 22.0 GiB / CUDA 12.1; keyframe **15.6s**, peak **5.11 GiB**.

---

## Troubleshooting
- **Script says "Not running inside the project venv":** good — that's the guard. Use the exact
  `.venv/bin/python ...` command it prints, or run `bash scripts/setup_env.sh` if `.venv` is missing.
- **torch can't see the GPU in the venv:** do not work around it. Re-check `nvidia-smi`, then the
  cu121 pins in `scripts/setup_env.sh` are the only thing to adjust. Report back.
- **HF rate-limit / gated model warnings:** set a token — `huggingface-cli login` or
  `export HF_TOKEN=<token>`. Required for gated models (e.g. SVD-XT) in Phase 2.
