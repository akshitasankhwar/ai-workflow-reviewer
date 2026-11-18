"""Cache of validated model answers only.

Key = sha256(prompt + request config + client identity + REVIEWER_VERSION). The prompt holds
every artifact's text and version, approvals included, so any artifact or approval change gives
a new key. The deterministic checks and the final status are always recomputed, so a cached
entry can never become a stale PASS. Failed or rejected answers are never stored.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import REVIEWER_VERSION


def cache_key(prompt: str, request_config: dict[str, Any], client_id: str) -> str:
    blob = json.dumps({"prompt": prompt, "request": request_config, "client": client_id,
                       "reviewer": REVIEWER_VERSION}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


class ModelCache:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)

    def get(self, key: str) -> dict[str, Any] | None:
        p = self.dir / f"{key}.json"
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, key: str, data: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f"{key}.json").write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
