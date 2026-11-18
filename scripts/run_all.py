"""THE one command (CPU-only, offline, fake model client):

    python scripts/run_all.py

1. unit + integration + regression tests
2. freeze the holdout if not frozen yet (afterwards run_eval refuses a changed holdout)
3. final code on dev and holdout
4. checkpoint snapshot (eval/checkpoint) on dev and holdout, same script and settings
5. ablation: approvals ignored, on dev and holdout
6. case-by-case comparisons
Each step runs in its own process so the two reviewer packages never mix.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}


def run(*args: str, env=ENV) -> None:
    print("\n$ python " + " ".join(args), flush=True)
    r = subprocess.run([PY, *args], cwd=ROOT, env=env)
    if r.returncode:
        sys.exit(f"step failed ({r.returncode}): {' '.join(args)}")


def main() -> None:
    run("-m", "pytest", "-q", "tests")
    if not (ROOT / "eval" / "freeze.json").exists():
        run("scripts/freeze_holdout.py")
    no_src = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    for split in ("dev", "holdout"):
        run("eval/run_eval.py", "--split", split, "--run", "final")
        run("eval/run_eval.py", "--split", split, "--run", "checkpoint",
            "--code", "eval/checkpoint", env=no_src)
        run("eval/run_eval.py", "--split", split, "--run", "ablation", "--ignore-approvals")
        run("eval/compare.py", "--a", "checkpoint", "--b", "final", "--split", split)
        run("eval/compare.py", "--a", "final", "--b", "ablation", "--split", split)
    print("\nall reports in eval/results/")


if __name__ == "__main__":
    main()
