"""Diffs two eval runs case by case (same bundles, same labels, same settings).

    python eval/compare.py --a checkpoint --b final --split holdout     # checkpoint vs final
    python eval/compare.py --a final --b ablation --split dev           # ablation effect

Writes eval/results/compare_<a>_vs_<b>_<split>.json.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "results"
FIELDS = ("actual", "blocking_refs", "counterexamples_valid", "unsupported_findings")
HEADLINE = ("status_accuracy", "false_passes", "false_blocks", "missed_defects")


def load(run: str, split: str) -> tuple[dict, dict]:
    d = RESULTS / run / split
    with open(d / "per_case.csv", encoding="utf-8") as f:
        rows = {r["bundle_id"]: r for r in csv.DictReader(f)}
    return rows, json.loads((d / "metrics.json").read_text(encoding="utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--split", required=True)
    args = ap.parse_args(argv)
    ra, ma = load(args.a, args.split)
    rb, mb = load(args.b, args.split)
    changed = []
    for bid in sorted(ra):
        diff = {k: [ra[bid][k], rb[bid][k]] for k in FIELDS if ra[bid][k] != rb[bid][k]}
        if diff:
            changed.append({"bundle_id": bid, "case_type": ra[bid]["case_type"],
                            "expected": ra[bid]["expected"], **diff})
    out = {"a": args.a, "b": args.b, "split": args.split,
           "metrics": {k: [ma[k], mb[k]] for k in HEADLINE},
           "finding_quality": {k: [ma["finding_quality"][k], mb["finding_quality"][k]]
                               for k in ma["finding_quality"]},
           "changed_cases": changed}
    p = RESULTS / f"compare_{args.a}_vs_{args.b}_{args.split}.json"
    p.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"{args.a} vs {args.b} ({args.split}): {len(changed)} case(s) differ -> {p.name}")
    for c in changed:
        print("   ", c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
