# Meta-Harness Automation

This directory contains a minimal automated outer loop for searching over [`program.md`](/home/phan635/AI_researcher/autoresearch-pq/program.md).

## What It Does

The loop treats `program.md` as the harness to optimize.

For each iteration it:

1. selects the current best candidate
2. asks a proposer agent to edit a new `candidate_program.md`
3. evaluates that candidate in an isolated workspace
4. extracts a score from `results.tsv` and `run.log`
5. stores all artifacts under `meta_harness/runs/`

## Main Script

- [`scripts/run_meta_harness.py`](/home/phan635/AI_researcher/autoresearch-pq/scripts/run_meta_harness.py)

## Config

Start from:

- [`meta_harness/config.example.json`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/config.example.json)

Copy it to `meta_harness/config.json` and adapt:

- proposer command
- evaluator command
- time budget
- trace copy behavior

## Run

```bash
python scripts/run_meta_harness.py --config meta_harness/config.json
```

## Important Limits

- The proposer/evaluator commands are external; this script orchestrates them but does not guarantee local Claude CLI auth/runtime behavior.
- The default score extractor is specific to this repo: it reads `results.tsv` and `run.log` from the evaluation workspace.
- This is a minimal Meta-Harness loop, not a reproduction of the Stanford artifact's full internal system.
