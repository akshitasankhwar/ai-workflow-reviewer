"""Compares expected (effective requirements) vs actual (spec / workflow / code) over the partition.
Returns either EQUIVALENT (exhaustive proof within domain) or minimal counterexample tickets.

Two decision lists are equivalent when they give the same route on every ticket of the
domain. Mismatching tickets are grouped by (expected route, expected requirement ids,
actual route, actual requirement ids); each group keeps its simplest ticket (lowest cost,
then a stable textual order) so the counterexample is small and reproducible.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable

from ..contracts.ir import DecisionList
from .domain import Domain
from .evaluator import decide

RefsFn = Callable[[DecisionList, str, "int | None"], list[str]]


@dataclass
class MismatchGroup:
    ticket: dict[str, Any]
    cost: int
    count: int
    expected_route: str
    expected_idx: int | None
    expected_refs: tuple[str, ...]
    actual_route: str
    actual_idx: int | None
    actual_refs: tuple[str, ...]


@dataclass
class Comparison:
    method: str                  # "exhaustive" | "sampled"
    tickets: int
    groups: list[MismatchGroup] = dc_field(default_factory=list)
    notes: list[str] = dc_field(default_factory=list)

    @property
    def equivalent(self) -> bool:
        return not self.groups


def _order(ticket: dict[str, Any]) -> str:
    return json.dumps(ticket, sort_keys=True, default=str)


def compare(expected: DecisionList, actual: DecisionList, domain: Domain,
            exp_refs: RefsFn, act_refs: RefsFn) -> Comparison:
    groups: dict[tuple, MismatchGroup] = {}
    n = 0
    for ticket, cost in domain.tickets():
        n += 1
        er, ei = decide(expected, ticket)
        ar, ai = decide(actual, ticket)
        if er == ar:
            continue
        erefs = tuple(exp_refs(expected, er, ei))
        arefs = tuple(act_refs(actual, ar, ai))
        key = (er, erefs, ar, arefs)
        g = groups.get(key)
        if g is None:
            groups[key] = MismatchGroup(dict(ticket), cost, 1, er, ei, erefs, ar, ai, arefs)
            continue
        g.count += 1
        if (cost, _order(ticket)) < (g.cost, _order(g.ticket)):
            g.ticket, g.cost, g.expected_idx, g.actual_idx = dict(ticket), cost, ei, ai
    ordered = sorted(groups.values(), key=lambda g: (g.expected_refs, g.actual_refs,
                                                      g.expected_route, g.actual_route))
    return Comparison(method=domain.method, tickets=n, groups=ordered, notes=list(domain.notes))
