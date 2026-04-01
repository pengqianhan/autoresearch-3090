# Task Plan

## Goal
Build a minimal automated Meta-Harness outer loop for optimizing `program.md` using the structured experience store and configurable proposer/evaluator commands.

## Phases
- [completed] Inspect current repo and decide the minimal automation architecture
- [completed] Implement scripts and directory structure for the automated loop
- [completed] Document how to run the loop and what remains environment-dependent

## Notes
- The loop optimizes `program.md`, not `train.py`.
- Raw traces live under `experience/claude-session/`.
- Structured traces live under `experience/structured/`.
- Runtime artifacts are written under `meta_harness/runs/` and `meta_harness/workspaces/`.

## Errors Encountered
- `claude -p` did not return quickly in this PTY-less validation path, so the loop was implemented as a configurable external-command orchestrator instead of assuming Claude CLI behavior is already fully validated in this environment.
