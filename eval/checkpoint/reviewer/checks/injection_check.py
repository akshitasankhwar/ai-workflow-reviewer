"""Flags instruction-like text in prose or comments ('ignore', 'approved by', 'say PASS').
Informational only: it can never change approvals or the decision.
"""
from __future__ import annotations

import re

from ..contracts.common import Location
from ..contracts.report import CheckResult, Finding
from .base import placeholder

NAME = "injection"
PATTERN = re.compile(
    r"ignore\s+(all|previous|prior|the\s+above)|approved\s+by|say\s+pass|mark\s+(this\s+)?as\s+pass"
    r"|report\s+pass|status\s*[:=]\s*pass|you\s+are\s+(an?\s+)?(ai|assistant|model|reviewer)"
    r"|disregard",
    re.IGNORECASE)


def run(ctx) -> tuple[CheckResult, list[Finding]]:
    findings: list[Finding] = []
    scanned = 0
    for kind, raw in sorted(ctx.bundle.raw.items()):
        if kind == "approvals" or not getattr(raw, "text", None):
            continue      # approvals are structured data and are validated by the resolver
        scanned += 1
        for no, line in enumerate(raw.text.splitlines(), 1):
            m = PATTERN.search(line)
            if not m:
                continue
            loc = Location(artifact=kind, version=raw.version, pointer=f"L{no}", line=no,
                           excerpt=line.strip()[:200])
            findings.append(placeholder(
                NAME, "info", None, loc, [loc],
                f"instruction-like text {m.group(0)!r} in {kind}; treated as data and ignored",
                "remove instructions aimed at the reviewer from the artifact"))
    return CheckResult(name=NAME, status="passed", method="structural",
                       detail=f"{scanned} artifact(s) scanned, {len(findings)} suspicious line(s); "
                              "informational only"), findings
