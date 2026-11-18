"""Shared building blocks: evidence locations, coverage entries, ingest issues."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

ArtifactKind = Literal["manifest", "requirements", "spec", "workflow", "code", "approvals"]


class Strict(BaseModel):
    """Immutable model that rejects unknown keys."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Location(Strict):
    """Where a piece of evidence lives: artifact, its version, and a pointer inside it.

    `pointer` is a line ("L12") for text artifacts, a JSON pointer ("/rules/2") for
    JSON artifacts, or a node id ("node:n3") for workflow nodes.
    """

    artifact: ArtifactKind
    version: str
    pointer: str
    line: int | None = None
    excerpt: str | None = None


class CoverageItem(Strict):
    """One piece of input content and whether the reviewer could interpret it."""

    location: Location
    status: Literal["supported", "unsupported", "ambiguous", "ignored"]
    reason: str


class Issue(Strict):
    """A problem found while ingesting an artifact (not yet a review finding)."""

    code: str
    message: str
    location: Location | None = None
    blocking: bool = False
