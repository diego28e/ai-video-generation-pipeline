"""
Shared guard: refuse to run unless we're inside the project's .venv.

This is the verification-first safeguard that prevents accidentally running
against system/user Python (which led to a --break-system-packages install).
Every runnable script in scripts/ calls ensure_project_venv() first.

Escape hatch (only if you truly know what you're doing): ALLOW_NON_VENV=1
"""
from __future__ import annotations

import os
import sys


def ensure_project_venv() -> None:
    if os.environ.get("ALLOW_NON_VENV") == "1":
        print("[warn] ALLOW_NON_VENV=1 — skipping venv check.")
        return

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    expected = os.path.join(repo_root, ".venv")

    in_a_venv = sys.base_prefix != sys.prefix
    in_project_venv = in_a_venv and os.path.abspath(sys.prefix) == os.path.abspath(expected)

    if in_project_venv:
        return

    script = os.path.relpath(sys.argv[0], repo_root) if sys.argv and sys.argv[0] else "scripts/<script>.py"
    print("\n[FAIL] Not running inside the project venv — refusing to continue.")
    print("  This guard exists so we never pollute system Python again.")
    print(f"  current interpreter : {sys.executable}")
    print(f"  sys.prefix          : {sys.prefix}")
    print(f"  expected venv        : {expected}")
    if not os.path.isdir(expected):
        print("\n  The venv does not exist yet. Create it first:")
        print("    bash scripts/setup_env.sh")
    print("\n  Then run this script using the venv's python EXPLICITLY (no activation needed):")
    print(f"    {os.path.join(expected, 'bin', 'python')} {script} {' '.join(sys.argv[1:])}".rstrip())
    print("  Or activate the venv first:  source .venv/bin/activate")
    sys.exit(1)
