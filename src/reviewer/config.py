"""Loads config/default.json: limits (max input bytes, max enumerated tickets),
model settings (timeout, max retries, call budget), seed, ablation switches.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "default.json"

_FALLBACK: dict[str, Any] = {
    "seed": 1234,
    "limits": {"max_artifact_bytes": 200_000, "max_enumerated_tickets": 50_000},
    "model": {"client": "fake", "prompt_version": "reviewer_v1", "temperature": 0.0,
              "max_tokens": 2048, "timeout_seconds": 30, "max_retries": 2,
              "max_calls_per_review": 4},
    "cache": {"enabled": True, "dir": ".cache"},
    "ablation": {"disable": []},
}


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_PATH
    cfg = copy.deepcopy(_FALLBACK)
    if p.exists():
        cfg = _merge(cfg, json.loads(p.read_text(encoding="utf-8")))
    elif path:
        raise FileNotFoundError(f"config file {p} not found")
    return _merge(cfg, overrides or {})
