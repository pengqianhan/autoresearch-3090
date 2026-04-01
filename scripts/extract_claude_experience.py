#!/usr/bin/env python3
"""Extract structured experience records from Claude JSONL traces."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any


TRAIN_CMD_RE = re.compile(r"\buv run train\.py\b")
COMMIT_RE = re.compile(r"\bgit commit\b")
RESET_RE = re.compile(r"\bgit reset\b")
RESULTS_RE = re.compile(r"\bresults\.tsv\b")
VAL_RE = re.compile(r"val_bpb:\s*([0-9.]+)")
VRAM_RE = re.compile(r"peak_vram_mb:\s*([0-9.]+)")
COMMIT_HASH_RE = re.compile(r"\[([A-Za-z0-9_./-]+)\s+([0-9a-f]{7,})\]")
EXP_MSG_RE = re.compile(r"exp\d+:\s*(.+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-root",
        default="experience/claude-session",
        help="Claude session directory containing main/subagents/tool-results.",
    )
    parser.add_argument(
        "--output-root",
        default="experience/structured",
        help="Directory to write structured outputs into.",
    )
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    events = []
    with path.open() as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            obj["_source_file"] = str(path)
            obj["_line_no"] = line_no
            events.append(obj)
    return events


def sanitize_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"raw_type": type(result).__name__, "raw_preview": compact_text(str(result), 200)}
    out: dict[str, Any] = {}
    for key in ("stdout", "stderr", "interrupted", "isImage", "noOutputExpected"):
        if key in result:
            out[key] = result[key]
    if "file" in result and isinstance(result["file"], dict):
        file_info = result["file"]
        out["file"] = {
            "filePath": file_info.get("filePath"),
            "numLines": file_info.get("numLines"),
            "startLine": file_info.get("startLine"),
            "totalLines": file_info.get("totalLines"),
        }
    if "type" in result:
        out["type"] = result["type"]
    return out


def compact_text(value: str | None, limit: int = 240) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def tool_result_text(obj: dict[str, Any]) -> str:
    result = obj.get("toolUseResult", {})
    if not isinstance(result, dict):
        return ""
    if isinstance(result.get("stdout"), str) and result["stdout"]:
        return result["stdout"]
    msg = obj.get("message", {})
    content = msg.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                text = item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


@dataclass
class StructuredEvent:
    event_id: str
    timestamp: str | None
    trace_file: str
    line_no: int
    event_type: str
    role: str | None = None
    tool_name: str | None = None
    tool_use_id: str | None = None
    parent_uuid: str | None = None
    uuid: str | None = None
    cwd: str | None = None
    git_branch: str | None = None
    command: str | None = None
    description: str | None = None
    text: str | None = None
    result: dict[str, Any] | None = None


@dataclass
class ExperimentRecord:
    experiment_index: int
    train_tool_use_id: str
    train_command: str | None = None
    train_description: str | None = None
    train_timestamp: str | None = None
    train_branch: str | None = None
    train_cwd: str | None = None
    preceding_commit_tool_use_id: str | None = None
    commit_command: str | None = None
    commit_description: str | None = None
    commit_hash: str | None = None
    commit_message: str | None = None
    grep_tool_use_id: str | None = None
    grep_command: str | None = None
    val_bpb: float | None = None
    peak_vram_mb: float | None = None
    results_updates: list[str] = field(default_factory=list)
    reset_commands: list[str] = field(default_factory=list)
    linked_edit_descriptions: list[str] = field(default_factory=list)
    linked_edit_files: list[str] = field(default_factory=list)


def build_structured_events(events: list[dict[str, Any]]) -> tuple[list[StructuredEvent], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    structured: list[StructuredEvent] = []
    tool_uses: dict[str, dict[str, Any]] = {}
    tool_results_by_use_id: dict[str, dict[str, Any]] = {}

    for obj in events:
        timestamp = obj.get("timestamp")
        trace_file = obj["_source_file"]
        line_no = obj["_line_no"]
        role = obj.get("message", {}).get("role") if isinstance(obj.get("message"), dict) else None
        base = {
            "event_id": f"{Path(trace_file).name}:{line_no}",
            "timestamp": timestamp,
            "trace_file": trace_file,
            "line_no": line_no,
            "role": role,
            "parent_uuid": obj.get("parentUuid"),
            "uuid": obj.get("uuid"),
            "cwd": obj.get("cwd"),
            "git_branch": obj.get("gitBranch"),
        }

        if obj.get("type") == "assistant":
            msg = obj.get("message", {})
            content = msg.get("content")
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get("type")
                    if item_type == "tool_use":
                        tool_use_id = item.get("id")
                        command = item.get("input", {}).get("command")
                        description = item.get("input", {}).get("description")
                        event = StructuredEvent(
                            **base,
                            event_type="assistant_tool_use",
                            tool_name=item.get("name"),
                            tool_use_id=tool_use_id,
                            command=command,
                            description=description,
                            text=compact_text(command or description or ""),
                        )
                        structured.append(event)
                        if tool_use_id:
                            tool_uses[tool_use_id] = {
                                "event": event,
                                "raw": item,
                            }
                    elif item_type == "text":
                        text = item.get("text")
                        if text:
                            structured.append(
                                StructuredEvent(**base, event_type="assistant_text", text=compact_text(text, 500))
                            )
                    elif item_type == "thinking":
                        structured.append(StructuredEvent(**base, event_type="assistant_thinking"))
            elif isinstance(content, str):
                structured.append(StructuredEvent(**base, event_type="assistant_text", text=compact_text(content, 500)))

        elif obj.get("type") == "user":
            msg = obj.get("message", {})
            content = msg.get("content")
            if isinstance(content, str):
                structured.append(StructuredEvent(**base, event_type="user_text", text=compact_text(content, 500)))
            elif isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "tool_result":
                        tool_use_id = item.get("tool_use_id")
                        event = StructuredEvent(
                            **base,
                            event_type="tool_result",
                            tool_use_id=tool_use_id,
                            text=compact_text(tool_result_text(obj), 500),
                            result=sanitize_tool_result(obj.get("toolUseResult", {})),
                        )
                        structured.append(event)
                        if tool_use_id:
                            tool_results_by_use_id[tool_use_id] = {
                                "event": event,
                                "raw": obj,
                            }
                    elif item.get("type") == "text":
                        text = item.get("text")
                        if text:
                            structured.append(StructuredEvent(**base, event_type="user_text", text=compact_text(text, 500)))

    return structured, tool_uses, tool_results_by_use_id


def commit_message_from_output(stdout: str) -> str | None:
    match = EXP_MSG_RE.search(stdout)
    if match:
        return match.group(0).strip()
    first = stdout.strip().splitlines()
    if first:
        return first[0].strip()
    return None


def extract_experiments(
    ordered_events: list[StructuredEvent],
    tool_results_by_use_id: dict[str, dict[str, Any]],
) -> list[ExperimentRecord]:
    experiments: list[ExperimentRecord] = []
    recent_commit: StructuredEvent | None = None
    recent_edits: list[StructuredEvent] = []
    pending_results_updates: list[str] = []
    pending_resets: list[str] = []

    for event in ordered_events:
        if event.event_type == "assistant_tool_use":
            if event.tool_name in {"Edit", "Write"}:
                recent_edits.append(event)
                if len(recent_edits) > 20:
                    recent_edits = recent_edits[-20:]
            elif event.tool_name == "Bash":
                cmd = event.command or ""
                if COMMIT_RE.search(cmd):
                    recent_commit = event
                elif RESULTS_RE.search(cmd):
                    pending_results_updates.append(cmd)
                elif RESET_RE.search(cmd):
                    pending_resets.append(cmd)
                elif TRAIN_CMD_RE.search(cmd):
                    exp = ExperimentRecord(
                        experiment_index=len(experiments) + 1,
                        train_tool_use_id=event.tool_use_id or "",
                        train_command=cmd,
                        train_description=event.description,
                        train_timestamp=event.timestamp,
                        train_branch=event.git_branch,
                        train_cwd=event.cwd,
                        results_updates=list(pending_results_updates),
                        reset_commands=list(pending_resets),
                    )
                    if recent_commit is not None:
                        exp.preceding_commit_tool_use_id = recent_commit.tool_use_id
                        exp.commit_command = recent_commit.command
                        exp.commit_description = recent_commit.description
                        commit_result = tool_results_by_use_id.get(recent_commit.tool_use_id or "")
                        if commit_result is not None:
                            raw_obj = commit_result["raw"]
                            result_obj = raw_obj.get("toolUseResult", {}) if isinstance(raw_obj, dict) else {}
                            stdout = ""
                            if isinstance(result_obj, dict):
                                stdout = result_obj.get("stdout", "") or ""
                            if not stdout and isinstance(raw_obj, dict):
                                stdout = tool_result_text(raw_obj)
                            match = COMMIT_HASH_RE.search(stdout)
                            if match:
                                exp.commit_hash = match.group(2)[:7]
                                exp.commit_message = commit_message_from_output(stdout)
                    if recent_edits:
                        for edit in recent_edits[-8:]:
                            if edit.description:
                                exp.linked_edit_descriptions.append(edit.description)
                        for edit in recent_edits[-8:]:
                            raw = None
                            # Look up file path from paired tool result if available.
                            result = tool_results_by_use_id.get(edit.tool_use_id or "")
                            if result:
                                raw = result["raw"].get("toolUseResult", {})
                            if isinstance(raw, dict):
                                file_path = raw.get("filePath")
                                if file_path:
                                    exp.linked_edit_files.append(file_path)
                    experiments.append(exp)
                    pending_results_updates.clear()
                    pending_resets.clear()

        elif event.event_type == "tool_result" and experiments:
            current = experiments[-1]
            if event.tool_use_id == current.train_tool_use_id:
                # Nothing needed beyond confirming the run completed.
                pass
            if current.grep_tool_use_id is None:
                # The grep usually happens immediately after the run and yields metrics.
                pass

    # Second pass: link grep outputs and post-train result-oriented commands.
    for idx, event in enumerate(ordered_events):
        if event.event_type != "assistant_tool_use" or event.tool_name != "Bash":
            continue
        cmd = event.command or ""
        if not re.search(r'grep\s+".*val_bpb', cmd):
            continue
        # Attach to the nearest previous experiment without grep result.
        target = None
        for exp in reversed(experiments):
            if exp.grep_tool_use_id is None and exp.train_timestamp and event.timestamp and event.timestamp >= exp.train_timestamp:
                target = exp
                break
        if target is None:
            continue
        target.grep_tool_use_id = event.tool_use_id
        target.grep_command = cmd
        result = tool_results_by_use_id.get(event.tool_use_id or "")
        if result is None:
            continue
        raw_obj = result["raw"]
        result_obj = raw_obj.get("toolUseResult", {}) if isinstance(raw_obj, dict) else {}
        stdout = ""
        if isinstance(result_obj, dict):
            stdout = result_obj.get("stdout", "") or ""
        if not stdout and isinstance(raw_obj, dict):
            stdout = tool_result_text(raw_obj)
        val_match = VAL_RE.search(stdout)
        vram_match = VRAM_RE.search(stdout)
        if val_match:
            target.val_bpb = float(val_match.group(1))
        if vram_match:
            target.peak_vram_mb = float(vram_match.group(1))

    return experiments


def collect_file_reads(structured_events: list[StructuredEvent], tool_results_by_use_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    reads = []
    for event in structured_events:
        if event.event_type != "assistant_tool_use" or event.tool_name != "Read":
            continue
        result = tool_results_by_use_id.get(event.tool_use_id or "")
        file_path = None
        line_count = None
        if result is not None:
            tr = result["raw"].get("toolUseResult", {})
            file_info = tr.get("file", {}) if isinstance(tr, dict) else {}
            if isinstance(file_info, dict):
                file_path = file_info.get("filePath")
                line_count = file_info.get("numLines")
        reads.append(
            {
                "tool_use_id": event.tool_use_id,
                "timestamp": event.timestamp,
                "file_path": file_path,
                "line_count": line_count,
                "trace_file": event.trace_file,
                "line_no": event.line_no,
            }
        )
    return reads


def summarize_trace(name: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    type_counts = Counter()
    tool_counts = Counter()
    first_ts = None
    last_ts = None
    for obj in events:
        type_counts[obj.get("type")] += 1
        if first_ts is None:
            first_ts = obj.get("timestamp")
        last_ts = obj.get("timestamp")
        if obj.get("type") == "assistant":
            content = obj.get("message", {}).get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        tool_counts[item.get("name")] += 1
    return {
        "name": name,
        "num_events": len(events),
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "type_counts": dict(type_counts),
        "tool_use_counts": dict(tool_counts),
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            json.dump(row, f, ensure_ascii=False)
            f.write("\n")


def main() -> None:
    args = parse_args()
    input_root = Path(args.input_root)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    main_files = sorted((input_root / "main").glob("*.jsonl"))
    if not main_files:
        raise SystemExit(f"No main JSONL found under {input_root / 'main'}")
    main_path = main_files[0]
    main_events = load_jsonl(main_path)
    structured_events, tool_uses, tool_results_by_use_id = build_structured_events(main_events)
    experiments = extract_experiments(structured_events, tool_results_by_use_id)
    file_reads = collect_file_reads(structured_events, tool_results_by_use_id)

    subagent_summaries = []
    for fp in sorted((input_root / "subagents").glob("*.jsonl")):
        subagent_summaries.append(summarize_trace(fp.name, load_jsonl(fp)))

    manifest = {
        "input_root": str(input_root),
        "main_trace": str(main_path),
        "subagent_count": len(subagent_summaries),
        "tool_result_count": len(list((input_root / "tool-results").glob("*"))),
        "structured_event_count": len(structured_events),
        "experiment_count": len(experiments),
    }
    summary = {
        "manifest": manifest,
        "main_trace_summary": summarize_trace(main_path.name, main_events),
        "subagent_summaries": subagent_summaries,
        "top_read_files": Counter(
            row["file_path"] for row in file_reads if row.get("file_path")
        ).most_common(30),
    }

    write_json(output_root / "manifest.json", manifest)
    write_json(output_root / "summary.json", summary)
    write_json(output_root / "experiments.json", [asdict(exp) for exp in experiments])
    write_json(output_root / "file_reads.json", file_reads)
    write_jsonl(output_root / "events.jsonl", [asdict(event) for event in structured_events])


if __name__ == "__main__":
    main()
