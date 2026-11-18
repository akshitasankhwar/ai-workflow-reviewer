"""Aggregates per-case rows into the Stage 4 metrics. Every rate is reported as "k/n".

false pass  = a case labelled CHANGES_REQUIRED or INCOMPLETE that the reviewer called PASS
false block = a case labelled PASS that the reviewer called CHANGES_REQUIRED
"""
from __future__ import annotations

from collections import Counter


def frac(k: int, n: int) -> str:
    return f"{k}/{n}"


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    defective = [r for r in rows if r["expected"] == "CHANGES_REQUIRED"]
    valid = [r for r in rows if r["expected"] == "PASS"]
    not_pass = [r for r in rows if r["expected"] != "PASS"]
    incompletes = [r for r in rows if r["actual"] == "INCOMPLETE"]
    rules_total = sum(len(r["defect_rules"].split()) for r in defective)
    blocking = sum(r["blocking_findings"] for r in defective)
    return {
        "cases": n,
        "status_accuracy": frac(sum(r["correct"] for r in rows), n),
        "false_passes": frac(sum(r["actual"] == "PASS" for r in not_pass), len(not_pass)),
        "false_blocks": frac(sum(r["actual"] == "CHANGES_REQUIRED" for r in valid), len(valid)),
        "missed_defects": frac(sum(r["actual"] != "CHANGES_REQUIRED" for r in defective),
                               len(defective)),
        "incomplete_by_case_type": dict(Counter(r["case_type"] for r in incompletes)),
        "incomplete_expected_vs_actual": frac(
            sum(r["expected"] == "INCOMPLETE" and r["actual"] == "INCOMPLETE" for r in rows),
            sum(r["expected"] == "INCOMPLETE" for r in rows)),
        "finding_quality": {
            "defect_rules_named_by_rule_ref": frac(sum(r["defect_rules_hit"] for r in defective),
                                                   rules_total),
            "defect_rules_covered_incl_counterexamples": frac(
                sum(r["defect_rules_hit_via_cx"] for r in defective), rules_total),
            "blocking_findings_on_defective": blocking,
            "unsupported_blocking_findings": frac(
                sum(r["unsupported_findings"] for r in defective), blocking),
            "blocking_findings_on_valid_or_incomplete": sum(
                r["blocking_findings"] for r in rows if r["expected"] != "CHANGES_REQUIRED"),
            "counterexamples_valid_by_oracle": frac(sum(r["counterexamples_valid"] for r in rows),
                                                    sum(r["counterexamples"] for r in rows)),
        },
        "cost": {
            "total_seconds": round(sum(r["seconds"] for r in rows), 3),
            "max_seconds": max((r["seconds"] for r in rows), default=0),
            "model_calls": sum(r["model_calls"] for r in rows),
            "model_retries": sum(r["model_retries"] for r in rows),
            "response_source": dict(Counter(r["response_source"] for r in rows)),
        },
    }
