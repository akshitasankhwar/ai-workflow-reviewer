"""Overlapping conditions / exceptions: which rule wins for tickets matching several rules.

Over the same partition used for equivalence, every ticket is tested against every
effective requirement. Tickets matching several requirements show which one wins by
precedence (info); a requirement that matches tickets but never wins is shadowed (minor).
"""
from __future__ import annotations

from ..contracts.report import CheckResult, Counterexample, Finding
from ..semantics.evaluator import EvalError, decide, holds
from .base import ReviewContext, placeholder, requirement_location

NAME = "interaction"


def run(ctx: ReviewContext) -> tuple[CheckResult, list[Finding]]:
    dl = ctx.effective
    if dl is None:
        return CheckResult(name=NAME, status="skipped", method="none",
                           detail="not run: no effective requirements"), []
    refs = list(dict.fromkeys(r.ref for r in dl.rules if r.ref))
    overlaps: dict[tuple[str, ...], tuple[dict, int, str]] = {}
    matched: set[str] = set()
    won: set[str] = set()
    n = 0
    for ticket, cost in ctx.domain.tickets():
        n += 1
        hits: list[str] = []
        for r in dl.rules:
            try:
                if holds(r.condition, ticket) and r.ref and r.ref not in hits:
                    hits.append(r.ref)
            except EvalError:
                pass
        matched.update(hits)
        route, idx = decide(dl, ticket)
        if idx is not None and dl.rules[idx].ref:
            won.add(dl.rules[idx].ref)
        if len(hits) > 1:
            key = tuple(hits)
            if key not in overlaps or cost < overlaps[key][1]:
                overlaps[key] = (dict(ticket), cost, route)
    findings: list[Finding] = []
    for key, (ticket, _, route) in sorted(overlaps.items()):
        winner = key[0]
        loc = requirement_location(ctx, winner)
        if loc is None:
            continue
        findings.append(placeholder(
            NAME, "info", winner, loc,
            [x for x in (requirement_location(ctx, k) for k in key) if x is not None],
            f"{' and '.join(key)} all match this ticket; {winner} wins by precedence -> {route}",
            "no change needed if this precedence is intended",
            Counterexample(ticket=ticket, expected_route=route, actual_route=route,
                           expected_rule=winner, actual_rule=winner)))
    shadowed = 0
    for ref in refs:
        if ref in matched and ref not in won:
            loc = requirement_location(ctx, ref)
            if loc is not None:
                shadowed += 1
                findings.append(placeholder(
                    NAME, "minor", ref, loc, [loc],
                    f"{ref} is fully shadowed: every ticket it matches is taken by an earlier rule",
                    f"check whether {ref} should take precedence or be removed"))
    method = ctx.domain.method
    return CheckResult(name=NAME, status="passed", method=method,
                       detail=f"{method}: {n} tickets; {len(overlaps)} overlap pattern(s), "
                              f"{shadowed} shadowed requirement(s)"
                              + ("" if method == "exhaustive" else " (sample; not proven)"),
                       tickets_evaluated=n), findings
