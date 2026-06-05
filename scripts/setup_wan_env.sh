#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Direction v2 / Phase A — Python environment for the WAN stack (RUN ON THE A100 VM).
# Creates / reuses the isolated venv (.venv), installs torch from the CUDA wheel
# index, the base requirements, then the Wan overrides (requirements-wan.txt).
# NO sudo, NO system-package writes (mirrors setup_env.sh).
#
# Prereqs (see docs/CINEMATIC_PIPELINE.md §7):
#   - A100 VM provisioned, NVIDIA driver + CUDA verified (scripts/verify_gpu.py).
#   - HF_TOKEN exported (or `hf auth login`) AND the Wan model licenses accepted
#     on Hugging Face, or the gated weights won't download.
# -----------------------------------------------------------------------------
set -euo pipefail

# A100 (Ampere) supports bf16, which Wan needs. cu121 matches the verified torch
# stack; bump TORCH/CUDA_INDEX only if G1' fails on the A100.
TORCH_VERSION="2.5.1"
TORCHVISION_VERSION="0.20.1"
CUDA_INDEX="https://download.pytorch.org/whl/cu121"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
echo "==> Project: $PROJECT_DIR"

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "!! python3.12 not found. Install it first (install_system_deps.sh)."
  exit 1
fi
python3.12 --version

if [ ! -d ".venv" ]; then
  echo "==> Creating venv at .venv"
  python3.12 -m venv .venv
else
  echo "==> Reusing existing .venv"
fi

VENV_PY="$PROJECT_DIR/.venv/bin/python"
# shellcheck disable=SC1091
source .venv/bin/activate

ACTUAL="$("$VENV_PY" -c 'import sys; print(sys.prefix)')"
if [ "$ACTUAL" != "$PROJECT_DIR/.venv" ]; then
  echo "!! venv sanity check failed: sys.prefix=$ACTUAL (expected $PROJECT_DIR/.venv)"
  exit 1
fi
echo "==> Using interpreter: $VENV_PY"

echo "==> Upgrading pip toolchain"
"$VENV_PY" -m pip install --upgrade pip wheel setuptools

echo "==> Installing torch ${TORCH_VERSION} (+cu121) from ${CUDA_INDEX}"
"$VENV_PY" -m pip install \
  "torch==${TORCH_VERSION}" "torchvision==${TORCHVISION_VERSION}" \
  --index-url "${CUDA_INDEX}"

echo "==> Installing base requirements"
"$VENV_PY" -m pip install -r requirements.txt

echo "==> Installing Wan overrides (bumps diffusers/transformers for Wan 2.2 + FLF2V)"
"$VENV_PY" -m pip install -r requirements-wan.txt

echo
echo "==> Environment ready. Verifying GPU..."
"$VENV_PY" scripts/verify_gpu.py

echo
echo "==> Authenticate to Hugging Face if you haven't (gated Wan weights):"
echo "      export HF_TOKEN=<token>        # or: hf auth login"
echo "==> Then prove the Wan path end-to-end (G1', light 5B model first):"
echo "      $VENV_PY scripts/verify_wan.py"
echo "==> Then benchmark the real target (Wan 2.2 I2V 14B) on real beats (G2'):"
echo "      $VENV_PY scripts/bench_wan.py --job samples/the_weight.json"
echo
echo "==> If G1' passes, freeze the lockfile for reproducibility:"
echo "      $VENV_PY -m pip freeze > requirements.lock.txt"
