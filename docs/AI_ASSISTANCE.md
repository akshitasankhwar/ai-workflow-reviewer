# AI-assistance note

**Tool used:** Claude (Claude Code, an agentic coding assistant), for all four stages.

**What the assistant did**
- Proposed the architecture (deterministic core with one decision-list IR for spec, workflow
  and code; approvals resolved before checking; model limited to adding validated findings;
  "no silent drops" rule).
- Wrote all of the code, tests, bundles, labels, the oracle, the evaluation scripts, the
  README and both notes, across Stages 1–4.
- Ran the tests and evaluations and copied the numbers in `docs/ENGINEERING_NOTE.md` from
  `eval/results/`.
- Found the R9→R3 attribution bug while reading per-case results for b10, fixed it and
  wrote its regression test.

**What I did**
- Reviewed and approved the proposed architecture before it was built.
- Set the scope: build only what the assignment asks for and keep the project light.
- Read the outputs and decided when each stage was finished.

I did not write code or labels myself, so the labels are a second, independent encoding of
the rules by the same assistant, not a human-written ground truth.

**Honesty points**
- Debug examples 1 and 2 come from earlier stages. Their original failing output cannot be
  recovered (the repository has no commits), so the note does not invent it. Debug 2 uses a
  deliberately injected crash and is labelled as fault injection.
- The real-model (Ollama) run is reported separately and plainly as "server not available".
  All headline numbers use the scripted fake client.

**Main risk of AI help:** the reviewer, the bundles, the labels and the oracle were all
written by the same assistant, so they can share blind spots. Two things limit this, though
neither removes it: the oracle is a separate, hand-written if/else that shares no code with
`src/`, and every label was checked against that oracle on a grid of tickets.
