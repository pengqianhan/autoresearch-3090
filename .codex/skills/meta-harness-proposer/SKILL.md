---
name: meta-harness-proposer
description: Use this skill when Codex should act as the proposer in a Meta-Harness loop, reading historical traces and experiment records to improve a Claude Code-driven `program.md` that searches for better `train.py` changes under a fixed evaluation budget.
---

# Meta Harness Proposer

## Overview

This skill turns Codex into the proposer described by Lee et al.'s Meta-Harness setup: it inspects prior harness behavior, execution traces, and scores, then proposes a better harness by editing the candidate prompt/program file. In this repo, the optimization target is `program.md`, because it controls how Claude Code searches for improvements to `train.py`.

Use this skill when the task is any of the following:

- Propose a better `program.md` or `candidate_program.md` from prior Claude/Codex traces.
- Analyze `experience/structured/*.json` to decide how the harness should change.
- Operate as the proposer step inside `scripts/run_meta_harness.py`.
- Improve a prompt/program that drives model-assisted training optimization while keeping the underlying model fixed.

Do not use this skill for evaluator-only work, generic model training advice, or direct `train.py` optimization without changing the harness.

## Workflow

### 1. Identify the harness and the score path

In this repo, assume:

- The harness being optimized is `program.md` or a copied `candidate_program.md`.
- The base agent is fixed; improve the harness around it.
- The objective is to find better `train.py` changes under the existing evaluation budget.
- The best immediate evidence comes from `experience/structured/` rather than raw session logs.

Before editing, confirm which file is the writable candidate. Prefer editing only `candidate_program.md` when one exists.

### 2. Read the structured experience first

Read these files first when present:

- `experience/structured/summary.json`
- `experience/structured/experiments.json`
- `experience/structured/file_reads.json`
- `meta_harness.md`
- `meta_harness_runbook.md`
- the current `program.md` or `candidate_program.md`

Use raw trace files under `experience/claude-session/` only when the structured files are insufficient to explain a decision, failure mode, or successful pattern.

This follows the Meta-Harness principle from Lee et al.: preserve the full history, but inspect it selectively instead of forcing the proposer to consume one monolithic summary.

### 3. Extract proposal signals from history

When reviewing history, look for:

- Which local changes improved `val_bpb`
- Which experiments crashed or regressed
- Whether failures came from bundling multiple hypotheses together
- Whether the harness encouraged overly large edits, weak logging, or poor credit assignment
- Whether the harness already over-indexes on one search style and needs a controlled exploration branch

For this repo in particular, prefer these recurring heuristics unless the data clearly argues otherwise:

- Favor one primary hypothesis per iteration.
- Favor small, attributable edits over broad coupled rewrites.
- Require explicit reasoning about keep/discard/crash outcomes.
- Preserve enough experiment detail that later proposers can recover why a change worked.
- Bias toward local search near the current best setup, with occasional explicit larger jumps.

### 4. Edit the harness, not the model code

The proposer's job is to improve harness behavior. In this repo that usually means changing instructions in `candidate_program.md` such as:

- how many hypotheses can be tested per loop
- what evidence must be recorded after each experiment
- when to revert, keep, or branch
- how aggressively to search around the current best point
- what files to consult before making larger changes
- how to preserve experiment trace quality for future optimization

Do not make direct `train.py` changes unless the user explicitly asks for evaluator-side work. As proposer, your default write target is the harness file only.

### 5. Keep proposals attributable

Each proposal should be coherent and easy to evaluate. Prefer one of these patterns:

- tighten the search policy
- improve experiment logging requirements
- change how history should be consulted before editing
- add guardrails against confounded edits
- add an explicit exploration/exploitation schedule

Avoid mixing several unrelated policy shifts into one candidate unless the user explicitly wants a broader redesign.

### 6. Produce the right output

If acting inside an automated Meta-Harness run:

- edit only `candidate_program.md`
- keep the file valid markdown/plain text
- do not rename files
- do not run long evaluations unless the wrapper or user asked for that step

If acting interactively:

- summarize the main historical signals you used
- explain the intended causal effect of the harness change
- note any residual uncertainty caused by missing or noisy traces

## Checklist

Before finishing, verify:

- You improved the harness file, not the training code.
- The proposal is grounded in `experience/structured/` evidence.
- The change can be evaluated in one outer-loop iteration.
- The rationale is attributable to a small number of concrete observed failure or success patterns.

## Repo Notes

This skill is tuned for the `autoresearch-pq` repository layout:

- Harness docs: `meta_harness.md`, `meta_harness_runbook.md`
- Outer loop: `scripts/run_meta_harness.py`
- Experience extraction: `scripts/extract_claude_experience.py`
- Raw trace store: `experience/claude-session/`
- Structured trace store: `experience/structured/`

If those paths differ in another repo, adapt the same workflow to the equivalent harness file, experience store, and evaluation loop.
