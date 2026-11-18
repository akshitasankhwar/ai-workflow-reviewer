"""Final status logic (pure function over check results + findings):
  CHANGES_REQUIRED  if any evidenced blocker exists (unreviewed scope still disclosed)
  INCOMPLETE        else if any required check failed / was ambiguous / not run / coverage gap
  PASS              only if every effective requirement was fully reviewed and no blocker.
A failed or crashed required check can never produce PASS.
"""
from __future__ import annotations

from typing import Iterable

from .contracts.common import CoverageItem, Issue
from .contracts.report import CheckResult, Finding, Status

BLOCKING_SEVERITIES = ("critical", "major")


def decide_status(checks: list[CheckResult], findings: list[Finding], coverage: list[CoverageItem],
                  incomplete_reasons: list[str], issues: list[Issue], has_effective: bool,
                  required: Iterable[str]) -> tuple[Status, list[str]]:
    """Return the status and the reasons behind it (shown in the report summary)."""
    blockers = [f for f in findings
                if f.severity in BLOCKING_SEVERITIES and f.origin == "deterministic" and f.evidence]
    if blockers:
        return "CHANGES_REQUIRED", [f"{len(blockers)} evidenced blocking finding(s)"]
    why: list[str] = []
    by_name = {c.name: c for c in checks}
    for name in required:
        c = by_name.get(name)
        if c is None:
            why.append(f"required check {name} did not run")
        elif c.status != "passed":
            why.append(f"required check {name} is {c.status}")
    gaps = [c for c in coverage if c.status in ("unsupported", "ambiguous")]
    if gaps:
        why.append(f"{len(gaps)} input item(s) could not be interpreted")
    why += incomplete_reasons
    why += [f"blocking issue: {i.code}" for i in issues if i.blocking]
    if not has_effective:
        why.append("no effective requirements could be derived")
    return ("INCOMPLETE", why) if why else ("PASS", ["every required check passed with full coverage"])
