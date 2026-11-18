"""Serialises ReviewReport to JSON (stable key order) and a short human summary.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from ..contracts.report import Report


def report_to_json(rep: Report) -> dict[str, Any]:
    return rep.model_dump(mode="json")


def human_summary(rep: Report) -> str:
    sev = Counter(f.severity for f in rep.findings)
    lines = [f"{rep.bundle_id}: {rep.status} - {rep.summary}",
             "findings: " + (", ".join(f"{k}={sev[k]}" for k in ("critical", "major", "minor", "info")
                                       if sev[k]) or "none")]
    lines += [f"  {c.name:<22} {c.status:<8} {c.method:<11} {c.detail}" for c in rep.checks]
    if rep.unreviewed_scope:
        lines.append("unreviewed: " + "; ".join(rep.unreviewed_scope))
    return "\n".join(lines)
