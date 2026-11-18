# Engineering note — AI-assisted workflow reviewer (Stages 3–4)

## 1. What the system does

Given a bundle (`requirements.md`, `spec.json`, `workflow.json`, optional `code/router.py`,
`approvals.json`, `manifest.json`), the reviewer returns `PASS`, `CHANGES_REQUIRED` or
`INCOMPLETE` with findings tied to a requirement (`rule_ref`), an artifact location and,
where possible, a concrete counterexample ticket.

Pipeline (`src/reviewer/pipeline.py`):

```
load -> compile each artifact to one decision-list IR -> resolve approvals
     -> effective requirements -> deterministic checks -> optional model review
     -> validator -> decision -> report (JSON, schemas/report.schema.json)
```

- **Deterministic core decides.** Spec, workflow and code are compiled into the same
  decision-list IR and compared against the effective requirements by enumerating a boundary
  grid (`semantics/equivalence.py`). Every mismatch yields a counterexample ticket.
- **The model only adds findings and can never produce PASS.** Its output is validated
  (`model/validator.py`): unknown rule refs, invented locations or malformed JSON are rejected;
  after `max_retries` the model check is `error` and the review is `INCOMPLETE`.
- **No silent drops.** Anything the compilers cannot handle becomes a coverage gap, and any
  gap, skipped or crashed required check forces `INCOMPLETE` (`decision.py`).
- Code in bundles is parsed (AST), never executed by the reviewer.

## 2. Evaluation setup

| Item | Where |
|---|---|
| Dev bundles (19) | `bundles/dev/b01…b19` |
| Frozen holdout (6) | `bundles/holdout/h01…h06`, hashes in `eval/freeze.json` |
| Labels (outside inputs) | `eval/labels/<split>/<id>.json` — read only by `eval/run_eval.py` |
| Independent oracle | `eval/oracle/routing_oracle.py` (shares no code with `src/`) |
| Checkpoint snapshot | `eval/checkpoint/reviewer` (taken 2026-11-18 19:22 IST) |
| Results | `eval/results/<run>/<split>/{per_case.csv,metrics.json}`, `eval/results/compare_*.json` |

Case mix (dev / holdout): valid 4/1, defective 10/3 (approval ignored, boundary, precedence,
missing requirement, wrong branch, unit, code disagrees, unapproved change, multi-rule,
prompt injection), incomplete 5/2 (approval conflict, model timeout, invented ref, missing
artifact, unsupported construct, truncated spec, truncated model output). Most defective
bundles are one-edit mutations of a valid one (`pair_of` in the label).

**Oracle.** R1–R3/R9 are re-written by hand as a plain if/else. The effective R3 threshold is
not computed by the oracle; it is written into each label (`oracle_r3_minutes`), so approval
handling is checked against a value fixed per case, not against the reviewer's own resolver. The oracle is used (a) to sanity-check labels by running the bundle code on a grid
(0 label problems on both splits) and (b) to check that each counterexample's
`expected_route` is correct.

**Holdout discipline.** The holdout was generated and frozen once; `run_eval` refuses to score
it if any bundle, label or `config/default.json` hash changed. It was not used while fixing
bugs (both real fixes below were found on dev).

**One command (CPU-only, offline):** `python scripts/run_all.py` runs the tests, all three
runs on both splits, and the comparisons. Model client = fake (scripted per label).

## 3. Results (fake model client)

| Run / split | Status acc. | False pass | False block | Missed defect | Incomplete correct |
|---|---|---|---|---|---|
| final / dev | 19/19 | 0/15 | 0/4 | 0/10 | 5/5 |
| final / holdout | 6/6 | 0/5 | 0/1 | 0/3 | 2/2 |
| checkpoint / dev | 19/19 | 0/15 | 0/4 | 0/10 | 5/5 |
| checkpoint / holdout | 6/6 | 0/5 | 0/1 | 0/3 | 2/2 |

False pass = labelled `CHANGES_REQUIRED` or `INCOMPLETE` but called `PASS`; false block =
labelled `PASS` but called `CHANGES_REQUIRED`.

Incomplete by type (final): dev — approval_conflict 1, model_failure 2, missing_artifact 1,
unsupported_construct 1; holdout — malformed_artifact 1, model_failure 1.

**Finding quality** (blocking = major/critical findings):

| Metric | ckpt dev | final dev | ckpt holdout | final holdout |
|---|---|---|---|---|
| Defect rules named by `rule_ref` | 9/13 | 11/13 | 2/3 | 3/3 |
| Unsupported blocking findings (rule not in label) | 4/15 | 0/15 | 6/10 | 2/10 |
| Blocking findings on valid/incomplete bundles | 0 | 0 | 0 | 0 |
| Counterexamples correct per oracle | 14/14 | 14/14 | 10/10 | 10/10 |

**Cost** (final, fake client, cache off): dev 0.39 s total, max 0.08 s per bundle,
20 model calls, 2 retries; holdout 0.23 s, 8 calls, 2 retries.

### Checkpoint vs final

Same script, inputs and settings; only the imported package differs (`--code eval/checkpoint`).
Status is identical: the change between checkpoint and final is in **attribution**, not in
the verdict. Case-level diff (`compare_checkpoint_vs_final_*.json`):

- dev `b10_def_unit`: blocking ref `R9 → R3`.
- holdout `h05_def_wrong_revision`: `R9 → R3` (unsupported findings 3 → 0).
- holdout `h03_def_inverted_missing`: `R1 R2 R3 R9 → R1 R2 R3`.

Remaining weakness: on h03 (spec routes a *present* category to manual review) the final
still emits 2 blocking findings citing R2/R3 besides the true R1 defect — the mismatch
tickets are attributed to the rule the actual route came from, so one defect is reported
three times. Verdict is right; the finding list is noisier than a human reviewer's.
2 of 13 dev defect rules are still not named (multi-rule / precedence bundles where the
second rule is masked by the first).

## 4. Debugging examples

**Debug 3 — real, found by this Stage 4 eval** (`tests/regression/test_debug_03_attribution.py`).
*Failing output* (b10, code uses `seconds(25)` instead of `minutes(25)`):
`code_equivalence major rule_ref=R9 "expected normal_queue, got escalation"`.
*Diagnosis:* `_finding` in `checks/base.py` took `rule_ref` from the **expected** side of the
counterexample. When the expected route is the default R9, the default rule was blamed
instead of the rule whose branch fired wrongly. *Fix:* if the expected rule is the default,
attribute to the actual (firing) rule; otherwise keep the expected rule. *Regression test:*
both directions (too-early escalation → R3; missed escalation → R3). This fix is the exact
difference between the checkpoint and final.

**Debugs 1 and 2** (`test_debug_01.py`, `test_debug_02.py`) were written during Stages 1–2.
I cannot reconstruct their original failing output from history (the repo has no commits), so
I do not claim them as Stage 4 discoveries. What they protect: (1) `not (wait_time < 25)` is
true for a ticket with no `wait_time` and must not be treated as `wait_time >= 25`;
(2) a required check that raises must be reported as `error` and force `INCOMPLETE` — that
test injects the crash on purpose (labelled fault injection via `monkeypatch`).

## 5. Ablation — ignore approvals

`--ignore-approvals` makes the pipeline use the raw requirements instead of the
approval-resolved ones (one line in `pipeline.py`, config `ablation.ignore_approvals`).

| | final dev | ablation dev | final holdout | ablation holdout |
|---|---|---|---|---|
| Status accuracy | 19/19 | 10/19 | 6/6 | 3/6 |
| False blocks | 0/4 | 4/4 | 0/1 | 1/1 |
| False passes | 0/15 | 0/15 | 0/5 | 0/5 |
| Expected incompletes found | 5/5 | 0/5 | 2/2 | 0/2 |
| Counterexamples correct per oracle | 14/14 | 10/59 | 10/10 | 10/23 |

All valid bundles implement the approved 25-minute R3 threshold, so without approvals every
one is blocked on R3; incompletes also turn into blocks because the R3 mismatch is found
before the gap matters. b05 (spec ignores the approval) is still blocked, but for the wrong
reason — its counterexample is now wrong per the oracle (1 → 0 valid). Conclusion: approval
resolution is load-bearing; without it the reviewer is safe (no false passes) but useless
(blocks everything).

## 6. Real model run (kept separate)

`python eval/run_eval.py --split dev --run real_ollama --model ollama` was run; Ollama was
**not reachable** on this machine (no server on `localhost:11434`). Result
(`eval/results/real_ollama/dev`): 15/19, 0 false passes, 0 false blocks; the 4 valid bundles
became `INCOMPLETE` with `model_review:error`, 0 successful model calls, 37 s total spent on
timeouts. This shows the fail-safe path works with a real client but gives **no evidence about
real model quality** — that remains unmeasured.

## 7. Limitations and what I'd do next

- One workflow family (ticket routing, 4 rules); bundles are synthetic, from
  `scripts/make_bundles.py`. The holdout is small (6) and written by the same author as dev,
  so it tests generalisation to new edits, not to new authors.
- The fake client is scripted per label, so model-related metrics measure the validator and
  failure handling, not model judgement.
- Next: de-duplicate findings that share a root cause (h03), run a real local model and
  report it beside the fake run, and add a second workflow family.
