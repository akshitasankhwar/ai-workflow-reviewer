"""Evaluate IR conditions and decision lists on a concrete ticket."""
from __future__ import annotations

from typing import Any

from ..contracts.ir import (
    ERROR_ROUTE, NO_ROUTE, And, Compare, Cond, Const, DecisionList, Eq, In, Missing, Not, Or,
)


class EvalError(Exception):
    """The artifact would fail at runtime on this ticket (e.g. KeyError / TypeError)."""


def _lookup(ticket: dict[str, Any], node) -> tuple[bool, Any]:
    value = ticket.get(node.field)
    if value is None:
        default = getattr(node, "default", None)
        if default is not None:
            return True, default
        if node.on_missing == "error":
            raise EvalError(f"{node.field} is missing")
        return False, None
    return True, value


def holds(cond: Cond, ticket: dict[str, Any]) -> bool:
    if isinstance(cond, Const):
        return cond.value
    if isinstance(cond, Missing):
        if ticket.get(cond.field) is None:
            if cond.on_missing == "error":
                raise EvalError(f"{cond.field} is missing")
            return True
        return False
    if isinstance(cond, Compare):
        present, v = _lookup(ticket, cond)
        if not present:
            return False
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise EvalError(f"{cond.field} is not numeric")
        return {"<": v < cond.value, "<=": v <= cond.value,
                ">": v > cond.value, ">=": v >= cond.value}[cond.op]
    if isinstance(cond, Eq):
        present, v = _lookup(ticket, cond)
        return present and v == cond.value
    if isinstance(cond, In):
        present, v = _lookup(ticket, cond)
        return present and v in cond.values
    if isinstance(cond, And):
        return all(holds(a, ticket) for a in cond.args)
    if isinstance(cond, Or):
        return any(holds(a, ticket) for a in cond.args)
    if isinstance(cond, Not):
        return not holds(cond.arg, ticket)
    raise TypeError(f"unknown condition {cond!r}")


def decide(dl: DecisionList, ticket: dict[str, Any]) -> tuple[str, int | None]:
    """Return (route, index of the deciding rule or None for the default)."""
    try:
        for i, rule in enumerate(dl.rules):
            if holds(rule.condition, ticket):
                return rule.route, i
    except EvalError:
        return ERROR_ROUTE, None
    return (dl.default_route if dl.default_route is not None else NO_ROUTE), None
