"""Each check returns CheckResult + findings. Registry lists required vs optional checks.
"""
from __future__ import annotations

from . import (code_check, coverage_check, injection_check, interaction_check, spec_check,
               workflow_check)
from .base import CheckFn, ReviewContext, run_check

REQUIRED: dict[str, CheckFn] = {
    spec_check.NAME: spec_check.run,
    workflow_check.NAME: workflow_check.run,
    code_check.NAME: code_check.run,
    coverage_check.NAME: coverage_check.run,
    interaction_check.NAME: interaction_check.run,
}
OPTIONAL: dict[str, CheckFn] = {injection_check.NAME: injection_check.run}

__all__ = ["REQUIRED", "OPTIONAL", "ReviewContext", "run_check"]
