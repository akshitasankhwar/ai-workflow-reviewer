"""Builds the reviewer prompt from reviewer_v1.md. Artifact text is line-numbered and fenced as
DATA; embedded instructions are declared non-authoritative. Oversized prompts are refused,
never truncated.
"""
from __future__ import annotations

from pathlib import Path

from ..contracts.ir import render

PROMPT_DIR = Path(__file__).parent


class PromptTooLarge(Exception):
    pass


def template(version: str) -> str:
    return (PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")


def build_prompt(analysis, checks, version: str, max_chars: int) -> tuple[str, dict]:
    """Return (prompt, context). context is what the fake client may use; it is never sent."""
    b = analysis.bundle
    reqs = analysis.resolved.requirements if analysis.resolved else []
    rules = "\n".join(f"- {q.id}: {q.text}" + (f"  [when {render(q.condition)} -> {q.route}]"
                                               if q.condition is not None else f"  [-> {q.route}]")
                      for q in reqs) or "(none could be derived)"
    res = "\n".join(f"- {c.name}: {c.status} ({c.detail})" for c in checks)
    parts = []
    sample = None
    for kind, raw in sorted(b.raw.items()):
        text = getattr(raw, "text", None)
        if text is None:
            continue
        lines = text.splitlines()
        numbered = "\n".join(f"{i:>4}| {ln}" for i, ln in enumerate(lines, 1))
        parts.append(f"[{kind} version={raw.version}]\n<<<DATA\n{numbered}\nDATA>>>")
        if kind == "requirements" and sample is None:
            for i, ln in enumerate(lines, 1):
                if ln.strip().startswith("- [") and ln.strip():
                    sample = {"artifact": kind, "line": i, "excerpt": ln.strip()}
                    break
    prompt = (template(version).replace("{effective_rules}", rules)
              .replace("{check_results}", res).replace("{artifacts}", "\n\n".join(parts)))
    if len(prompt) > max_chars:
        raise PromptTooLarge(f"prompt is {len(prompt)} chars, over the {max_chars} limit; "
                             "not sent and not truncated")
    ctx = {"rule_refs": [q.id for q in reqs], "sample_evidence": sample}
    return prompt, ctx
