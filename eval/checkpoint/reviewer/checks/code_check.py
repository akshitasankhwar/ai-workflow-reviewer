"""Effective requirements vs linked code; catches script disagreement despite correct metadata.

The code is parsed (never executed) into a decision list from its if/elif/return chain.
A `# ref:` comment only names the requirement; the route actually returned is what is
compared, so a correct ref with a wrong destination is still a mismatch.
"""
from __future__ import annotations

from ._structural import with_structure
from .base import ReviewContext

NAME = "code_equivalence"


def run(ctx: ReviewContext):
    return with_structure(ctx, "code", NAME)
