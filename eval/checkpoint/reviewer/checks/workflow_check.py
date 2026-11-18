"""Effective requirements vs reachable workflow paths and branch destinations; structural issues.

Every path from start to a route node is one rule (path conditions conjoined, in DFS
order: on_true before on_false), so the comparison covers exactly the reachable paths.
"""
from __future__ import annotations

from ._structural import with_structure
from .base import ReviewContext

NAME = "workflow_equivalence"


def run(ctx: ReviewContext):
    return with_structure(ctx, "workflow", NAME)
