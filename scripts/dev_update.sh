#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Dev loop helper — RUN ON THE VM, from the repo root.
# Pulls the latest code and syncs Python deps WITHOUT reinstalling torch every
# time (torch is the slow ~2.5GB install; we only touch it via setup_env.sh).
#
# Typical loop:  edit locally -> push -> on VM:  bash scripts/dev_update.sh
# -----------------------------------------------------------------------------
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "==> git pull (fast-forward only)"
git pull --ff-only

VENV_PY="$PROJECT_DIR/.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  echo "==> No venv yet — running full environment setup."
  bash scripts/setup_env.sh
  exit 0
fi

echo "==> Syncing requirements (torch left untouched)"
"$VENV_PY" -m pip install -r requirements.txt

echo "==> Up to date. Interpreter: $VENV_PY"
echo "    Run scripts with:  $VENV_PY scripts/<name>.py"
