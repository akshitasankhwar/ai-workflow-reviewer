"""Records sha256 of every holdout bundle file, the holdout labels and the config into
eval/freeze.json. run_eval refuses to score the holdout if any of them changed.

    python scripts/freeze_holdout.py          # freeze (only once, before the final run)
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "eval" / "freeze.json"
FROZEN_DIRS = [ROOT / "bundles" / "holdout", ROOT / "eval" / "labels" / "holdout"]
FROZEN_FILES = [ROOT / "config" / "default.json"]


def hashes() -> dict[str, str]:
    files = [p for d in FROZEN_DIRS for p in d.rglob("*") if p.is_file()] + FROZEN_FILES
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files)}


def verify() -> list[str]:
    if not FREEZE.exists():
        return ["eval/freeze.json missing (run scripts/freeze_holdout.py)"]
    old = json.loads(FREEZE.read_text(encoding="utf-8"))["files"]
    new = hashes()
    return ([f"changed: {k}" for k in old if k in new and old[k] != new[k]]
            + [f"removed: {k}" for k in old if k not in new]
            + [f"added: {k}" for k in new if k not in old])


def main() -> None:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        commit = None
    FREEZE.write_text(json.dumps({
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": commit or "none (repository has no commits yet)",
        "files": hashes()}, indent=2) + "\n", encoding="utf-8")
    print(f"froze {len(hashes())} files -> {FREEZE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
