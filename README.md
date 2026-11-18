# AI-assisted workflow reviewer

Checks that a workflow change is consistent end to end: the **requirements**, the **approved
changes** to them, the **spec**, the **workflow graph** and the **code** must all route every
ticket the same way. It returns `PASS`, `CHANGES_REQUIRED` or `INCOMPLETE`, with findings
that cite a requirement, a file location and a concrete counterexample ticket.

A deterministic core makes the decision. An optional model (fake or local Ollama) can only
add findings, which are validated; it can never turn a review into `PASS`.

## Setup (CPU only, offline)

```
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
pip install -e .                  # optional: installs the `reviewer` command
```

Python 3.11+. The only runtime dependency is pydantic.

## Run everything (one command)

```
python scripts/run_all.py
```

This runs the test suite, then on the dev and frozen holdout splits evaluates the final
version, the checkpoint and the ablation, and finally writes the comparisons. All reports go
to `eval/results/` (`per_case.csv`, `metrics.json`, `compare_*.json`).

## Review one bundle

```
python -m reviewer review bundles/dev/b10_def_unit --out report.json
python -m reviewer review bundles/dev/b01_valid_base --model fake
python -m reviewer analyze bundles/dev/b01_valid_base      # effective requirements, IR
```

(With `pip install -e .` you can type `reviewer` instead of `python -m reviewer`; without it,
set `PYTHONPATH=src`.) The exit code is 0 only when the status is `PASS`.

## Input: a bundle folder

| File | What it is |
|---|---|
| `requirements.md` | Numbered rules (`[R1]`, `[R2]`, …) and the ticket fields |
| `approvals.json` | Approved / rejected changes to rules (e.g. R3 threshold 30 → 25 min) |
| `spec.json` | Prioritised rules that claim to implement the requirements |
| `workflow.json` | Decision-node graph of the same logic |
| `code/router.py` | Python `route(ticket)`; parsed from its AST, **never executed** |
| `manifest.json` | Lists the artifacts, their versions and the code entry point |

The `minutes()` / `seconds()` helpers in bundle code are notation the reviewer understands;
the files are not meant to be importable, so the IDE type checker is turned off for `bundles/`.

## Output: a JSON report (`schemas/report.schema.json`)

- `status`: `PASS` | `CHANGES_REQUIRED` | `INCOMPLETE`
- `findings[]`: check, severity, `rule_ref`, artifact + location, evidence excerpts,
  suggested correction, counterexample ticket (expected vs actual route), origin
  (deterministic or model)
- `checks[]`: each check's state (passed / failed / error / skipped) and how much it covered
- coverage gaps and model usage (calls, retries, source)

`INCOMPLETE` means the reviewer could not check everything (missing or malformed artifact,
unsupported code, conflicting approvals, model failure) — it never guesses `PASS`.

## Layout

```
src/reviewer/      the reviewer (ingest, approvals, semantics, checks, model, decision, reporting)
bundles/dev        19 development bundles      bundles/holdout   6 frozen holdout bundles
eval/labels        expected results (kept outside the bundles)
eval/oracle        independent routing oracle (shares no code with src/)
eval/checkpoint    snapshot of the reviewer used for the checkpoint comparison
eval/run_eval.py   scores one run          eval/compare.py   diffs two runs
scripts/           make_bundles, freeze_holdout, run_all, export_schemas
tests/             unit, integration, regression
docs/              ENGINEERING_NOTE.md, AI_ASSISTANCE.md
```

## Other commands

```
python eval/run_eval.py --split dev --run final                         # one run
python eval/run_eval.py --split dev --run ablation --ignore-approvals   # ablation
python eval/run_eval.py --split dev --run real_ollama --model ollama    # needs `ollama serve` + qwen2.5:3b
python eval/compare.py --a checkpoint --b final --split holdout
python -m pytest -q
```

The holdout is hash-frozen in `eval/freeze.json`; `run_eval` refuses to score it if any
holdout bundle, holdout label or `config/default.json` has changed.
