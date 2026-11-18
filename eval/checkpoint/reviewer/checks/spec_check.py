"""Effective requirements vs specification (semantic equivalence + diagnosis).
"""
from __future__ import annotations

from .base import ReviewContext, mismatch_findings

NAME = "spec_equivalence"


def run(ctx: ReviewContext):
    return mismatch_findings(ctx, "spec", NAME)
