"""Finite partition of the ticket space.
Collects every constant from both sides per field and builds representative values
(missing, each threshold t, t-epsilon, t+epsilon, below-all, above-all; each enum value + 'other').
Within the supported language this set hits every region where routes can differ ->
checking all combinations is EXHAUSTIVE, not sampled. Size is capped; overflow -> reported.
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field as dc_field
from typing import Any, Iterator

from ..contracts.ir import Compare, DecisionList, Eq, FieldDecl, In, Missing, walk

MISSING = object()          # sentinel: the key is absent from the ticket
OTHER = "__other__"         # an enum/string value no artifact mentions
EPS = 1e-3


@dataclass(frozen=True)
class Rep:
    """One representative value of a field and how 'natural' it is (lower = nicer)."""

    value: Any
    cost: int


@dataclass
class Domain:
    fields: dict[str, list[Rep]]
    size: int
    method: str                      # "exhaustive" | "sampled"
    seed: int
    limit: int
    notes: list[str] = dc_field(default_factory=list)

    def tickets(self) -> Iterator[tuple[dict[str, Any], int]]:
        """Yield (ticket, cost). Exhaustive product, or a seeded sample of `limit` combinations."""
        names = sorted(self.fields)
        reps = [self.fields[n] for n in names]
        if self.method == "exhaustive":
            combos: Iterator[tuple[Rep, ...]] = itertools.product(*reps)
        else:
            rng = random.Random(self.seed)
            combos = (tuple(rng.choice(r) for r in reps) for _ in range(self.limit))
        for combo in combos:
            t = {n: r.value for n, r in zip(names, combo) if r.value is not MISSING}
            yield t, sum(r.cost for r in combo)


def _constants(dls: list[DecisionList]) -> tuple[dict[str, set[float]], dict[str, set[Any]], set[str]]:
    nums: dict[str, set[float]] = {}
    vals: dict[str, set[Any]] = {}
    seen: set[str] = set()
    for dl in dls:
        for rule in dl.rules:
            for node in walk(rule.condition):
                if isinstance(node, Compare):
                    seen.add(node.field)
                    nums.setdefault(node.field, set()).add(float(node.value))
                    if node.default is not None:
                        nums[node.field].add(float(node.default))
                elif isinstance(node, (Eq, In)):
                    seen.add(node.field)
                    s = vals.setdefault(node.field, set())
                    s.update([node.value] if isinstance(node, Eq) else node.values)
                    if node.default is not None:
                        s.add(node.default)
                elif isinstance(node, Missing):
                    seen.add(node.field)
    return nums, vals, seen


def _num(x: float) -> float | int:
    return int(x) if float(x).is_integer() else round(x, 6)


def _numeric_reps(ts: set[float]) -> list[Rep]:
    if not ts:
        return [Rep(0, 0), Rep(MISSING, 1)]
    out: dict[float, Rep] = {}
    for t in sorted(ts):
        out.setdefault(t, Rep(_num(t), 0))
        out.setdefault(t - EPS, Rep(_num(t - EPS), 2))
        out.setdefault(t + EPS, Rep(_num(t + EPS), 2))
    lo, hi = min(ts), max(ts)
    out.setdefault(lo - 1, Rep(_num(lo - 1), 1))
    out.setdefault(hi + 1, Rep(_num(hi + 1), 1))
    return [out[k] for k in sorted(out)] + [Rep(MISSING, 1)]


def _key(v: Any) -> tuple[str, str]:
    return (type(v).__name__, repr(v))


def build_domain(decls: dict[str, FieldDecl], dls: list[DecisionList], config: dict[str, Any]) -> Domain:
    limit = int(config.get("limits", {}).get("max_enumerated_tickets", 50000))
    seed = int(config.get("seed", 1234))
    nums, vals, seen = _constants(dls)
    fields: dict[str, list[Rep]] = {}
    notes: list[str] = []
    for name in sorted(set(decls) | seen):
        d = decls.get(name)
        ftype = d.type if d else ("number" if name in nums else "string")
        if d is None:
            notes.append(f"field {name} is used by an artifact but not declared in the requirements")
        if ftype == "number":
            fields[name] = _numeric_reps(nums.get(name, set()))
        elif ftype == "bool":
            fields[name] = [Rep(True, 0), Rep(False, 0), Rep(MISSING, 1)]
        else:
            known = set(d.values if d else ()) | vals.get(name, set())
            fields[name] = ([Rep(v, 0) for v in sorted(known, key=_key)]
                            + [Rep(OTHER, 2), Rep(MISSING, 1)])
    size = 1
    for r in fields.values():
        size *= len(r)
    method = "exhaustive" if size <= limit else "sampled"
    if method == "sampled":
        notes.append(f"{size} partition cells exceed the limit {limit}; "
                     f"checked a seeded sample of {limit} (seed {seed})")
    return Domain(fields=fields, size=size, method=method, seed=seed, limit=limit, notes=notes)
