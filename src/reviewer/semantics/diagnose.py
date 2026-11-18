"""Explains a mismatch: changed threshold, inclusive/exclusive boundary, unit error,
wrong precedence (order swap), wrong destination, missing branch, omitted rule.
Used to write the finding's message and correction.

The diagnosis is a best-effort explanation of a counterexample that equivalence already
proved; it never decides whether a mismatch exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..contracts.ir import (
    ERROR_ROUTE, NO_ROUTE, Compare, DecisionList, Eq, In, IRRule, render, walk,
)
from .equivalence import MismatchGroup
from .evaluator import EvalError, holds

RefsAt = Callable[["int | None"], list[str]]   # rule index (None = default) -> requirement ids


@dataclass(frozen=True)
class Diagnosis:
    kind: str        # missing_branch | runtime_error | omitted_rule | wrong_precedence |
                     # wrong_destination | unit_error | changed_threshold | boundary | condition_differs
    message: str
    correction: str


def label(dl: DecisionList, idx: int | None) -> str:
    """Human name of a deciding rule in its own artifact."""
    if idx is None:
        return "the default route"
    rule = dl.rules[idx]
    loc = rule.location
    if loc.artifact == "spec":
        return f"spec rule {rule.ref}"
    if loc.artifact == "workflow":
        node = loc.pointer[5:] if loc.pointer.startswith("node:") else loc.pointer
        return f"workflow path to node {node}"
    if loc.artifact == "code":
        return f"code return at line {loc.line}" if loc.line else f"code return {loc.pointer}"
    return f"requirement {rule.ref}" if rule.ref else f"rule {idx}"


def _safe_holds(rule: IRRule, ticket: dict[str, Any]) -> bool:
    try:
        return holds(rule.condition, ticket)
    except EvalError:
        return False


def _compares(rules: list[IRRule]) -> dict[str, set[tuple[str, float]]]:
    out: dict[str, set[tuple[str, float]]] = {}
    for r in rules:
        for n in walk(r.condition):
            if isinstance(n, Compare):
                out.setdefault(n.field, set()).add((n.op, float(n.value)))
    return out


def _equalities(rules: list[IRRule]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for r in rules:
        for n in walk(r.condition):
            if isinstance(n, Eq):
                out.add((n.field, repr(n.value)))
            elif isinstance(n, In):
                out.update((n.field, repr(v)) for v in n.values)
    return out


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def _threshold(rid: str, exp: dict, act: dict, where: str) -> Diagnosis | None:
    for fname in sorted(set(exp) & set(act)):
        e, a = exp[fname], act[fname]
        if e == a:
            continue
        # Pair the closest thresholds (bounds of a single requirement are usually one per field).
        (eop, ev) = sorted(e)[0]
        (aop, av) = min(sorted(a), key=lambda x: (abs(x[1] - ev), x[0] != eop))
        if ev == av and eop != aop:
            return Diagnosis(
                "boundary",
                f"{rid}: {where} uses {fname} {aop} {_fmt(av)} but the requirement says "
                f"{fname} {eop} {_fmt(ev)} (inclusive/exclusive boundary differs)",
                f"use {fname} {eop} {_fmt(ev)} in {where}")
        if ev and av and (abs(av / ev - 60) < 1e-6 or abs(ev / av - 60) < 1e-6):
            return Diagnosis(
                "unit_error",
                f"{rid}: {where} compares {fname} against {_fmt(av)} where the requirement means "
                f"{_fmt(ev)} (a factor of 60: hours/minutes confused)",
                f"express the {fname} threshold as {_fmt(ev)} in the field's unit in {where}")
        if ev != av:
            return Diagnosis(
                "changed_threshold",
                f"{rid}: {where} uses {fname} {aop} {_fmt(av)} but the effective requirement "
                f"is {fname} {eop} {_fmt(ev)}",
                f"change the {fname} threshold in {where} to {eop} {_fmt(ev)}")
    return None


def diagnose(g: MismatchGroup, expected: DecisionList, actual: DecisionList,
             exp_refs_at: RefsAt, act_refs_at: RefsAt, what: str) -> Diagnosis:
    t = g.ticket
    act_label = label(actual, g.actual_idx)
    rid = g.expected_refs[0] if g.expected_refs else (g.actual_refs[0] if g.actual_refs else None)
    rtext = rid or "the effective requirements"

    if g.actual_route == NO_ROUTE:
        return Diagnosis("missing_branch",
                         f"{what} gives no route for this ticket; {rtext} requires {g.expected_route}",
                         f"add a branch in the {what} that routes these tickets to {g.expected_route}")
    if g.actual_route == ERROR_ROUTE:
        return Diagnosis("runtime_error",
                         f"{what} fails on this ticket (a field it reads is missing or not numeric); "
                         f"{rtext} requires {g.expected_route}",
                         f"handle missing values in the {what} so these tickets reach {g.expected_route}")
    if rid is None:
        return Diagnosis("condition_differs",
                         f"{act_label} routes to {g.actual_route}; expected {g.expected_route}",
                         f"align {act_label} with the effective requirements")

    n = len(actual.rules)
    citing = [i for i in range(n) if rid in act_refs_at(i)]
    default_cites = rid in act_refs_at(None)
    if g.expected_refs and not citing and not default_cites:
        return Diagnosis("omitted_rule",
                         f"{rid} ({g.expected_route}) has no counterpart in the {what}: no rule cites "
                         f"it and these tickets fall through to {act_label} ({g.actual_route})",
                         f"add a rule to the {what} implementing {rid} -> {g.expected_route}")

    if g.expected_refs and rid in act_refs_at(g.actual_idx):
        return Diagnosis("wrong_destination",
                         f"{act_label} cites {rid} and matches this ticket, but routes to "
                         f"{g.actual_route}; {rid} requires {g.expected_route} (reference is correct, "
                         f"behaviour is wrong)",
                         f"route {act_label} to {g.expected_route}")

    winners = [i for i in citing if _safe_holds(actual.rules[i], t)]
    if g.expected_refs and winners and g.actual_idx is not None and g.actual_idx < min(winners):
        w = min(winners)
        other = ", ".join(act_refs_at(g.actual_idx)) or "an uncited rule"
        return Diagnosis("wrong_precedence",
                         f"{label(actual, w)} ({rid}) matches this ticket but {act_label} ({other}) is "
                         f"checked first and wins; the effective requirements give {rid} priority",
                         f"evaluate {label(actual, w)} before {act_label} in the {what}")

    # Threshold-level comparison, first for the expected requirement, then for the one that fired.
    for r in list(g.expected_refs) + [x for x in g.actual_refs if x not in g.expected_refs]:
        exp_rules = [x for x in expected.rules if x.ref == r]
        act_idx = [i for i in range(n) if r in act_refs_at(i)]
        if not exp_rules or not act_idx:
            continue
        where = label(actual, act_idx[0])
        d = _threshold(r, _compares(exp_rules), _compares([actual.rules[i] for i in act_idx]), where)
        if d:
            return d
        if _equalities(exp_rules) != _equalities([actual.rules[i] for i in act_idx]):
            return Diagnosis("condition_differs",
                             f"{r}: {where} tests different values than the requirement "
                             f"({' / '.join(render(x.condition) for x in exp_rules)})",
                             f"make {where} test exactly the values required by {r}")

    return Diagnosis("condition_differs",
                     f"{act_label} routes this ticket to {g.actual_route}; {rtext} requires "
                     f"{g.expected_route}",
                     f"align the {what} conditions with {rtext}")
