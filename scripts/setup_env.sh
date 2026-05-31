#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Phase 1 — Python environment (RUN ON THE GCP VM, after install_system_deps.sh).
# Creates an isolated venv (.venv). NO sudo, NO system-package writes.
# This REPLACES the original plan's `--break-system-packages` (PEP 668 bypass).
#
# torch/torchvision are installed from the CUDA 12.1 wheel index, matching the
# verified VM stack (driver 580, cu121, torch.cuda.is_available() == True).
# -----------------------------------------------------------------------------
set -euo pipefail

# --- Pins for the CUDA build (kept here, not in requirements.txt, so the index
#     URL is explicit and unambiguous). These MATCH the torch already verified on
#     the VM (torch 2.5.1+cu121, driver 580). Adjust ONLY if G1 fails. ---
TORCH_VERSION="2.5.1"
TORCHVISION_VERSION="0.20.1"
CUDA_INDEX="https://download.pytorch.org/whl/cu121"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "==> Project: $PROJECT_DIR"

# --- Require Python 3.12 (the verified target is 3.12.3) ---
if ! command -v python3.12 >/dev/null 2>&1; then
  echo "!! python3.12 not found. Install it first (install_system_deps.sh)."
  exit 1
fi
python3.12 --version

# --- Create / reuse venv ---
if [ ! -d ".venv" ]; then
  echo "==> Creating venv at .venv"
  python3.12 -m venv .venv
else
  echo "==> Reusing existing .venv"
fi

# Use the venv interpreter EXPLICITLY (no reliance on PATH/activation) so we can
# never accidentally hit system Python again.
VENV_PY="$PROJECT_DIR/.venv/bin/python"

# shellcheck disable=SC1091
source .venv/bin/activate

# Verify we are actually inside the venv before installing anything.
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

echo "==> Installing project requirements"
"$VENV_PY" -m pip install -r requirements.txt

echo
echo "==> Environment ready. Verifying GPU..."
"$VENV_PY" scripts/verify_gpu.py

echo
echo "==> If GPU verification passed, freeze the lockfile for reproducibility:"
echo "      $VENV_PY -m pip freeze > requirements.lock.txt"
echo "==> Then run the full G1 keyframe check (downloads SDXL weights, ~7GB):"
echo "      $VENV_PY scripts/verify_keyframe.py"
