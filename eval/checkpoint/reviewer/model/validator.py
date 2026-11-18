"""Validates model output against the bundle. Nothing the model says is trusted until checked:
  - shape: coverage/assessments/findings with the expected keys and types
  - rule_ref must be an effective requirement id (else: invented ref, dropped)
  - artifact must exist in the bundle; evidence excerpt must appear on the cited line
  - conflicts: a rule both 'ok' and 'issue', or 'ok' while a major+ finding cites it
  - unknown top-level keys (e.g. "status", "approval") are ignored and noted - the model has
    no say over status or approvals.
Invalid parts are dropped AND reported; they never silently disappear.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..contracts.common import Location
from ..contracts.report import Finding

ALLOWED_KEYS = {"coverage", "assessments", "findings"}
SEVERITIES = {"critical", "major", "minor", "info"}
FINDING_KEYS = {"severity", "rule_ref", "artifact", "location", "evidence", "message", "correction"}


def shape_error(data: dict[str, Any]) -> str | None:
    """Format problems worth a retry. Returns None when the shape is usable."""
    for k in ("coverage", "assessments", "findings"):
        if not isinstance(data.get(k), list):
            return f"'{k}' missing or not a list"
    if not all(isinstance(r, str) for r in data["coverage"]):
        return "coverage must be a list of rule ids"
    for a in data["assessments"]:
        if not (isinstance(a, dict) and isinstance(a.get("rule_ref"), str)
                and a.get("verdict") in ("ok", "issue")):
            return f"bad assessment: {a!r}"[:200]
    for f in data["findings"]:
        if not isinstance(f, dict) or not FINDING_KEYS <= f.keys():
            return f"finding missing keys: {f!r}"[:200]
        if f["severity"] not in SEVERITIES or not isinstance(f["evidence"], list) or not f["evidence"]:
            return "finding has bad severity or no evidence"
    return None


@dataclass
class Validated:
    findings: list[Finding] = field(default_factory=list)
    covered: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)   # dropped claims, with reason
    conflicts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)      # ignored keys etc.

    @property
    def clean(self) -> bool:
        return not (self.missing or self.rejected or self.conflicts)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _evidence(tag: str, items: list, raw: dict[str, Any]) -> tuple[list[Location], str | None]:
    out: list[Location] = []
    for e in items:
        src = raw.get(e.get("artifact")) if isinstance(e, dict) else None
        line = e.get("line") if isinstance(e, dict) else None
        ex = e.get("excerpt") if isinstance(e, dict) else None
        if src is None or not isinstance(line, int) or not isinstance(ex, str) or not ex.strip():
            return [], f"{tag} evidence item malformed or cites a missing artifact: {e!r}"[:200]
        lines = src.text.splitlines()
        if not 1 <= line <= len(lines) or _norm(ex) not in _norm(lines[line - 1]):
            return [], f"{tag} evidence {e['artifact']}:L{line} does not contain {ex!r}"[:200]
        out.append(Location(artifact=e["artifact"], version=src.version, pointer=f"L{line}",
                            line=line, excerpt=ex.strip()))
    return out, None


def validate(data: dict[str, Any], rule_refs: list[str], raw: dict[str, Any]) -> Validated:
    v = Validated()
    refs = set(rule_refs)
    for k in sorted(set(data) - ALLOWED_KEYS):
        v.notes.append(f"ignored top-level key {k!r} (model has no authority over it)")
    for r in data["coverage"]:
        if r in refs:
            v.covered.append(r)
        else:
            v.rejected.append(f"coverage claims unknown rule {r!r}")
    v.covered = sorted(set(v.covered))
    v.missing = sorted(refs - set(v.covered))

    verdicts: dict[str, set[str]] = {}
    for a in data["assessments"]:
        if a["rule_ref"] not in refs:
            v.rejected.append(f"assessment for unknown rule {a['rule_ref']!r}")
            continue
        verdicts.setdefault(a["rule_ref"], set()).add(a["verdict"])

    for i, f in enumerate(data["findings"]):
        tag = f"finding[{i}]"
        if f["rule_ref"] not in refs:
            v.rejected.append(f"{tag} cites unknown rule {f['rule_ref']!r} (invented ref)")
            continue
        art = raw.get(f["artifact"])
        if art is None or getattr(art, "text", None) is None:
            v.rejected.append(f"{tag} cites artifact {f['artifact']!r} not in bundle")
            continue
        evidence, bad = _evidence(tag, f["evidence"], raw)
        if bad:
            v.rejected.append(bad)
            continue
        v.findings.append(Finding(
            id="", check="model_review", severity=f["severity"], rule_ref=f["rule_ref"],
            artifact=f["artifact"], version=art.version, location=str(f["location"]),
            evidence=evidence, message=str(f["message"]), correction=str(f["correction"]),
            origin="model"))

    for r, vs in sorted(verdicts.items()):
        if vs == {"ok", "issue"}:
            v.conflicts.append(f"{r} assessed both ok and issue")
        elif vs == {"ok"} and any(f.rule_ref == r and f.severity in ("critical", "major")
                                  for f in v.findings):
            v.conflicts.append(f"{r} assessed ok but a major finding cites it")
    return v
