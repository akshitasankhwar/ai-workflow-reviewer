"""Independent oracle for the ticket-routing family. Shares NO code with src/reviewer.

The requirements (R1, R2, R3, R9) are hand-written below as a plain if/else. The effective R3
threshold after approvals is not computed here: it comes from the hand-decided label
(`oracle_r3_minutes`), so approval resolution is checked against a human decision.

Used for two things only:
  1. label sanity: run each bundle's code/router.py (eval tooling may execute it; the reviewer
     never does) on a boundary grid and check it agrees with the oracle exactly when the label
     says the code is correct;
  2. counterexample validity: a blocking finding's `expected_route` must be what the oracle says.
"""
from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any, Callable

CATEGORIES = [None, "billing"]
PRIORITIES = ["urgent", "normal"]
WAITS = [None, 0, 0.5, 24.99, 25, 25.01, 29.99, 30, 30.01, 35, 120]   # minutes


def oracle_route(ticket: dict[str, Any], r3_minutes: float) -> str:
    if ticket.get("category") is None:
        return "manual_review"                       # R1
    if ticket.get("priority") == "urgent":
        return "priority_queue"                      # R2
    wait = ticket.get("wait_time")
    if wait is not None and wait >= r3_minutes:
        return "escalation"                          # R3
    return "normal_queue"                            # R9


def grid() -> list[dict[str, Any]]:
    out = []
    for c, p, w in itertools.product(CATEGORIES, PRIORITIES, WAITS):
        t: dict[str, Any] = {"priority": p}
        if c is not None:
            t["category"] = c
        if w is not None:
            t["wait_time"] = w
        out.append(t)
    return out


def load_code(bundle: Path) -> Callable[[dict], str] | None:
    p = bundle / "code" / "router.py"
    if not p.is_file():
        return None
    env: dict[str, Any] = {"minutes": lambda x: x, "seconds": lambda x: x / 60}
    try:
        exec(compile(p.read_text(encoding="utf-8"), str(p), "exec"), env)  # noqa: S102 - own test data
    except Exception:  # noqa: BLE001
        return None
    return env.get("route")


def code_disagreements(bundle: Path, r3_minutes: float) -> int | None:
    fn = load_code(bundle)
    if fn is None:
        return None
    bad = 0
    for t in grid():
        try:
            got = fn(dict(t))
        except Exception:  # noqa: BLE001
            got = "<error>"
        bad += got != oracle_route(t, r3_minutes)
    return bad


def check_label(bundle: Path, label: dict[str, Any]) -> str | None:
    """Return a problem string if the label contradicts the oracle, else None."""
    r3 = label["oracle_r3_minutes"]
    if r3 is None:
        return None                                  # undecidable on purpose (approval conflict)
    bad = code_disagreements(bundle, r3)
    if bad is None:
        return None                                  # code missing / not runnable: nothing to check
    if label["expected_status"] == "PASS" and bad:
        return f"labelled PASS but code differs from the oracle on {bad} tickets"
    if label["expected_status"] == "CHANGES_REQUIRED" and label["case_type"] in (
            "unit", "code_disagrees", "multi_rule", "injection", "unapproved_change") and not bad:
        return "labelled as a code defect but code agrees with the oracle"
    return None
