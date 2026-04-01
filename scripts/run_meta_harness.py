#!/usr/bin/env python3
"""Minimal automated Meta-Harness outer loop over program.md."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


VAL_RE = re.compile(r"val_bpb:\s*([0-9.]+)")
VRAM_RE = re.compile(r"peak_vram_mb:\s*([0-9.]+)")


@dataclass
class CandidateResult:
    iteration: int
    candidate_dir: str
    parent_iteration: int | None
    score: float | None
    peak_vram_mb: float | None
    status: str
    program_path: str
    workspace_dir: str
    trace_dir: str | None
    notes: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="meta_harness/config.json")
    parser.add_argument("--iterations", type=int, default=None)
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"seed_initialized": False, "candidates": []}
    with path.open() as f:
        return json.load(f)


def sanitize_project_dir(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", str(path.resolve()))


def copy_repo(src: Path, dst: Path, ignore_names: list[str]) -> None:
    ignore_set = set(ignore_names)

    def ignore(directory: str, names: list[str]) -> set[str]:
        rel = Path(directory).resolve().relative_to(src.resolve())
        ignored = set()
        for name in names:
            rel_name = str(rel / name) if str(rel) != "." else name
            if name in ignore_set or rel_name in ignore_set:
                ignored.add(name)
        return ignored

    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)


def build_env(extra: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(extra)
    return env


def render_command(template: str, mapping: dict[str, str]) -> str:
    try:
        return template.format(**mapping)
    except Exception:
        return template


def run_command(
    command: str,
    cwd: Path,
    env: dict[str, str],
    timeout_sec: int | None,
    stdout_path: Path,
    stderr_path: Path,
) -> tuple[int, bool]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("w") as stdout_f, stderr_path.open("w") as stderr_f:
        proc = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            shell=True,
            stdout=stdout_f,
            stderr=stderr_f,
            executable="/bin/sh",
        )
        timed_out = False
        try:
            proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        return proc.returncode, timed_out


def extract_score(workspace_dir: Path) -> tuple[float | None, float | None, str]:
    results_tsv = workspace_dir / "results.tsv"
    best_val = None
    status = "missing_results"
    if results_tsv.exists():
        lines = [line.rstrip("\n") for line in results_tsv.read_text().splitlines() if line.strip()]
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            try:
                val = float(parts[1])
            except ValueError:
                continue
            if val > 0 and (best_val is None or val < best_val):
                best_val = val
        status = "scored" if best_val is not None else "results_no_positive_score"

    peak_vram = None
    run_log = workspace_dir / "run.log"
    if run_log.exists():
        text = run_log.read_text(errors="ignore")
        val_matches = [float(m.group(1)) for m in VAL_RE.finditer(text)]
        vram_matches = [float(m.group(1)) for m in VRAM_RE.finditer(text)]
        if best_val is None and val_matches:
            best_val = min(val_matches)
            status = "scored_from_run_log"
        if vram_matches:
            peak_vram = max(vram_matches)

    return best_val, peak_vram, status


def latest_claude_trace(projects_dir: Path, workspace_dir: Path, started_at: float) -> Path | None:
    project_dir = projects_dir / sanitize_project_dir(workspace_dir)
    if not project_dir.exists():
        return None
    candidates = sorted(
        [p for p in project_dir.glob("*.jsonl") if p.stat().st_mtime >= started_at],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def copy_claude_trace(trace_path: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(trace_path, target_dir / trace_path.name)
    session_dir = trace_path.with_suffix("")
    if session_dir.exists():
        for rel in ("subagents", "tool-results"):
            src = session_dir / rel
            if src.exists():
                dst = target_dir / rel
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)


def select_best_candidate(state: dict[str, Any], seed_result: CandidateResult) -> CandidateResult:
    rows = [seed_result] + [CandidateResult(**row) for row in state.get("candidates", [])]
    scored = [row for row in rows if row.score is not None]
    if scored:
        return min(scored, key=lambda row: row.score)
    return rows[0]


def proposer_prompt(
    repo_root: Path,
    experience_dir: Path,
    parent_program: Path,
    candidate_program: Path,
    history_path: Path,
    iteration: int,
) -> str:
    return f"""You are optimizing the harness for the autoresearch repo.

Goal:
- Improve program.md as a harness for Claude Code so that bounded evaluation runs achieve lower best val_bpb.

Rules:
- Edit only {candidate_program.name}.
- Keep the file coherent and executable as instructions for the agent.
- Prefer changes that improve experimental discipline, credit assignment, and use of prior results.
- Do not modify train.py or prepare.py here.

Context:
- Repo root: {repo_root}
- Structured experience dir: {experience_dir}
- Parent harness: {parent_program}
- Candidate to edit: {candidate_program}
- History summary: {history_path}
- Iteration: {iteration}

What to inspect before editing:
- experience/structured/summary.json
- experience/structured/experiments.json
- experience/structured/file_reads.json
- the parent harness

Deliverable:
- Write the improved harness into {candidate_program.name}.
- Keep it concise and focused on actual behavior changes.
"""


def initialize_seed(repo_root: Path, runs_dir: Path, seed_program: Path) -> CandidateResult:
    seed_dir = runs_dir / "seed"
    seed_dir.mkdir(parents=True, exist_ok=True)
    candidate_program = seed_dir / "candidate_program.md"
    shutil.copy2(seed_program, candidate_program)
    result = CandidateResult(
        iteration=0,
        candidate_dir=str(seed_dir),
        parent_iteration=None,
        score=None,
        peak_vram_mb=None,
        status="seed_only",
        program_path=str(candidate_program),
        workspace_dir="",
        trace_dir=None,
        notes="Seed harness copied from repo program.md",
    )
    write_json(seed_dir / "result.json", asdict(result))
    return result


def main() -> None:
    args = parse_args()
    repo_root = Path.cwd()
    config = load_config(Path(args.config))
    iterations = int(config.get("iterations", 1)) if args.iterations is None else args.iterations
    seed_program = (repo_root / config["seed_program"]).resolve()
    experience_dir = (repo_root / config["experience_dir"]).resolve()
    runs_dir = (repo_root / config["runs_dir"]).resolve()
    workspace_root = (repo_root / config["workspace_dir"]).resolve()
    state_path = runs_dir / "state.json"
    runs_dir.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)

    state = read_state(state_path)
    if not state.get("seed_initialized"):
        seed = initialize_seed(repo_root, runs_dir, seed_program)
        state["seed_initialized"] = True
        state["seed_result"] = asdict(seed)
        write_json(state_path, state)
    seed_result = CandidateResult(**state["seed_result"])

    for iteration in range(1, iterations + 1):
        parent = select_best_candidate(state, seed_result)
        iter_dir = runs_dir / f"iter_{iteration:03d}"
        iter_dir.mkdir(parents=True, exist_ok=True)
        candidate_program = iter_dir / "candidate_program.md"
        shutil.copy2(parent.program_path, candidate_program)

        history_path = iter_dir / "history.json"
        write_json(
            history_path,
            {
                "seed_result": asdict(seed_result),
                "existing_candidates": state.get("candidates", []),
                "selected_parent": asdict(parent),
            },
        )

        prompt_text = proposer_prompt(
            repo_root=repo_root,
            experience_dir=experience_dir,
            parent_program=Path(parent.program_path),
            candidate_program=candidate_program,
            history_path=history_path,
            iteration=iteration,
        )
        write_text(iter_dir / "proposer_prompt.txt", prompt_text)

        mapping = {
            "repo_root": str(repo_root),
            "candidate_dir": str(iter_dir),
            "candidate_program": str(candidate_program),
            "parent_program": str(parent.program_path),
            "experience_dir": str(experience_dir),
            "iteration_dir": str(iter_dir),
            "workspace_dir": str(workspace_root / f"iter_{iteration:03d}"),
        }

        proposer_cfg = config["proposer"]
        proposer_cwd = Path(mapping[proposer_cfg.get("cwd_mode", "candidate_dir")])
        proposer_cmd = render_command(proposer_cfg["command"], mapping)
        proposer_env = build_env(
            {
                "MH_REPO_ROOT": str(repo_root),
                "MH_CANDIDATE_DIR": str(iter_dir),
                "MH_CANDIDATE_PROGRAM": str(candidate_program),
                "MH_PARENT_PROGRAM": str(parent.program_path),
                "MH_EXPERIENCE_DIR": str(experience_dir),
                "MH_ITERATION_DIR": str(iter_dir),
            }
        )
        proposer_rc, proposer_timed_out = run_command(
            proposer_cmd,
            proposer_cwd,
            proposer_env,
            proposer_cfg.get("timeout_sec"),
            iter_dir / "proposer_stdout.txt",
            iter_dir / "proposer_stderr.txt",
        )
        if proposer_rc != 0 or proposer_timed_out or not candidate_program.exists():
            result = CandidateResult(
                iteration=iteration,
                candidate_dir=str(iter_dir),
                parent_iteration=parent.iteration,
                score=None,
                peak_vram_mb=None,
                status="proposer_failed",
                program_path=str(candidate_program),
                workspace_dir="",
                trace_dir=None,
                notes=f"proposer_rc={proposer_rc} proposer_timed_out={proposer_timed_out}",
            )
            state.setdefault("candidates", []).append(asdict(result))
            write_json(iter_dir / "result.json", asdict(result))
            write_json(state_path, state)
            continue

        workspace_dir = workspace_root / f"iter_{iteration:03d}"
        copy_repo(repo_root, workspace_dir, config.get("copy_ignore", []))
        shutil.copy2(candidate_program, workspace_dir / "program.md")

        evaluator_cfg = config["evaluator"]
        mapping["workspace_dir"] = str(workspace_dir)
        evaluator_cwd = Path(mapping[evaluator_cfg.get("cwd_mode", "workspace_dir")])
        evaluator_cmd = render_command(evaluator_cfg["command"], mapping)
        evaluator_env = build_env(
            {
                "MH_REPO_ROOT": str(repo_root),
                "MH_ITERATION_DIR": str(iter_dir),
                "MH_WORKSPACE_DIR": str(workspace_dir),
                "MH_USER_PROMPT": config["user_prompt"],
                "MH_CANDIDATE_PROGRAM": str(candidate_program),
            }
        )
        started_at = time.time()
        evaluator_rc, evaluator_timed_out = run_command(
            evaluator_cmd,
            evaluator_cwd,
            evaluator_env,
            int(config.get("evaluator_timeout_sec", 1800)),
            iter_dir / "evaluator_stdout.txt",
            iter_dir / "evaluator_stderr.txt",
        )

        trace_dir = None
        trace_cfg = config.get("trace_copy", {})
        if trace_cfg.get("enabled"):
            projects_dir = Path(trace_cfg["claude_projects_dir"]).expanduser()
            trace_path = latest_claude_trace(projects_dir, workspace_dir, started_at)
            if trace_path is not None:
                trace_dir = str(iter_dir / "claude_trace")
                copy_claude_trace(trace_path, Path(trace_dir))

        score, peak_vram_mb, score_status = extract_score(workspace_dir)
        status = "evaluated"
        if evaluator_timed_out:
            status = "evaluator_timeout"
        elif evaluator_rc != 0:
            status = "evaluator_failed"
        elif score is None:
            status = score_status

        result = CandidateResult(
            iteration=iteration,
            candidate_dir=str(iter_dir),
            parent_iteration=parent.iteration,
            score=score,
            peak_vram_mb=peak_vram_mb,
            status=status,
            program_path=str(candidate_program),
            workspace_dir=str(workspace_dir),
            trace_dir=trace_dir,
            notes=f"evaluator_rc={evaluator_rc} evaluator_timed_out={evaluator_timed_out}",
        )
        write_json(
            iter_dir / "evaluation_summary.json",
            {
                "score": score,
                "peak_vram_mb": peak_vram_mb,
                "status": status,
                "evaluator_rc": evaluator_rc,
                "evaluator_timed_out": evaluator_timed_out,
            },
        )
        write_json(iter_dir / "result.json", asdict(result))
        state.setdefault("candidates", []).append(asdict(result))
        write_json(state_path, state)

    best = select_best_candidate(state, seed_result)
    print(json.dumps({"best_candidate": asdict(best), "runs_dir": str(runs_dir)}, indent=2))


if __name__ == "__main__":
    main()
