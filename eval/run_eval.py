"""Runs the reviewer on every bundle in a split and scores it against eval/labels/<split>/*.json.

    python eval/run_eval.py --split holdout --run final
    python eval/run_eval.py --split holdout --run checkpoint --code eval/checkpoint
    python eval/run_eval.py --split holdout --run ablation --ignore-approvals

`--code` selects which reviewer package is imported (final = src, checkpoint = frozen snapshot),
so the same script, inputs and settings are used for both. Writes
eval/results/<run>/<split>/{per_case.csv, metrics.json}. The cache is always off so call counts
are real. Labels are read only here, never by the reviewer.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.metrics import summarise  # noqa: E402
from eval.oracle.routing_oracle import check_label, oracle_route  # noqa: E402

BLOCKING = ("major", "critical")


def score_case(rep, label: dict, seconds: float) -> dict:
    blocking = [f for f in rep.findings if f.severity in BLOCKING]
    refs = sorted({f.rule_ref for f in blocking if f.rule_ref})
    defect = set(label["defect_rules"])
    r3 = label["oracle_r3_minutes"]
    cx = [f.counterexample for f in blocking if f.counterexample is not None]
    cx_valid = sum(oracle_route(c.ticket, r3) == c.expected_route for c in cx) if r3 is not None else 0
    # rules the counterexamples actually exercise (expected side), e.g. "R2" or "R1, R2"
    cx_rules = {r.strip() for c in cx for r in (c.expected_rule or "").split(",") if r.strip()}
    u = rep.model_usage
    return {
        "bundle_id": label["bundle_id"], "case_type": label["case_type"],
        "expected": label["expected_status"], "actual": rep.status,
        "correct": rep.status == label["expected_status"],
        "defect_rules": " ".join(sorted(defect)), "blocking_refs": " ".join(refs),
        "blocking_findings": len(blocking),
        "unsupported_findings": sum(1 for f in blocking if f.rule_ref not in defect),
        "defect_rules_hit": len(defect & set(refs)),
        "defect_rules_hit_via_cx": len(defect & (set(refs) | cx_rules)),
        "counterexamples": len(cx), "counterexamples_valid": cx_valid,
        "locations": " | ".join(f"{f.artifact}:{f.location}" for f in blocking),
        "incomplete_reasons": " | ".join(rep.incomplete_reasons + [
            c.name + ":" + c.status for c in rep.checks if c.status in ("skipped", "error")]),
        "model_calls": u.calls if u else 0, "model_retries": u.retries if u else 0,
        "response_source": u.response_source if u else "none",
        "seconds": round(seconds, 4),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "holdout"], required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--code", default="src", help="dir holding the reviewer package")
    ap.add_argument("--model", default="fake", choices=["none", "fake", "ollama"])
    ap.add_argument("--ignore-approvals", action="store_true")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(ROOT / args.code))
    from reviewer.config import load_config
    from reviewer.pipeline import review

    if args.split == "holdout":
        from scripts.freeze_holdout import verify
        problems = verify()
        if problems:
            print("holdout is not frozen or has changed:\n  " + "\n  ".join(problems))
            return 2

    overrides = {"cache": {"enabled": False}}
    if args.ignore_approvals:
        overrides["ablation"] = {"ignore_approvals": True}
    config = load_config(ROOT / "config" / "default.json", overrides)

    rows, label_problems = [], []
    for lp in sorted((ROOT / "eval" / "labels" / args.split).glob("*.json")):
        label = json.loads(lp.read_text(encoding="utf-8"))
        bundle = ROOT / "bundles" / args.split / label["bundle_id"]
        problem = check_label(bundle, label)
        if problem:
            label_problems.append(f"{label['bundle_id']}: {problem}")
        t0 = time.perf_counter()
        rep = review(bundle, config, model=args.model,
                     fake_script=label["fake_script"] if args.model == "fake" else None)
        rows.append(score_case(rep, label, time.perf_counter() - t0))

    out = ROOT / "eval" / "results" / args.run / args.split
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "per_case.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    metrics = summarise(rows)
    metrics.update(run=args.run, split=args.split, code=args.code, model_client=args.model,
                   ignore_approvals=args.ignore_approvals, label_problems=label_problems)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(f"[{args.run}/{args.split}] {metrics['status_accuracy']}  "
          f"false_pass={metrics['false_passes']}  false_block={metrics['false_blocks']}  "
          f"label_problems={len(label_problems)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
