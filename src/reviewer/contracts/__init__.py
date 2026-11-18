"""Pydantic models = the documented input/output contracts. Exported to /schemas as JSON Schema.
"""
from __future__ import annotations

import json
from pathlib import Path


def contracts() -> dict:
    from .artifacts import ApprovalsFile, Manifest, Requirement, Spec, Workflow
    from .ir import DecisionList
    from .report import Report
    return {
        "manifest": Manifest,
        "spec": Spec,
        "workflow": Workflow,
        "approvals": ApprovalsFile,
        "requirement": Requirement,
        "decision_list": DecisionList,
        "report": Report,
    }


def export(out_dir: str | Path = "schemas") -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in contracts().items():
        schema = model.model_json_schema()
        schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
        p = out / f"{name}.schema.json"
        p.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(p)
    return written
