#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Phase 1 — System dependencies (RUN ON THE GCP VM, Ubuntu 24.04).
# Requires sudo. Idempotent: safe to re-run.
#
# Installs ffmpeg (audio mux + encode), the venv toolchain, and build basics,
# then sanity-checks the NVIDIA driver. Does NOT touch system Python packages
# (no --break-system-packages); all Python deps go in a venv (setup_env.sh).
# -----------------------------------------------------------------------------
set -euo pipefail

echo "==> apt update"
sudo apt-get update -y

echo "==> Installing system packages"
sudo apt-get install -y \
  ffmpeg \
  python3.12-venv \
  python3-pip \
  python3-dev \
  build-essential \
  git \
  curl

echo
echo "==> Versions"
python3 --version
ffmpeg -version | head -n 1
git --version

echo
echo "==> NVIDIA driver / GPU check (expect driver 580, NVIDIA L4)"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi
else
  echo "!! nvidia-smi not found. The GPU driver is not visible — STOP and fix this"
  echo "!! before continuing (the rest of the pipeline needs CUDA)."
  exit 1
fi

echo
echo "==> System deps OK. Next: bash scripts/setup_env.sh"
