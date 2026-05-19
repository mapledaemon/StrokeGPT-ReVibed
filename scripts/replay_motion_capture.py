#!/usr/bin/env python
"""Summarize and replay exported StrokeGPT motion transport captures.

The Diagnostics tab can export a capture JSON object after a motion test run.
This script reads that file without importing the Flask app or touching the
device, then prints the transport summary and an ordered event timeline that
can be attached to bug reports or compared between branches.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _capture_from_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError("Capture file must contain a JSON object.")
    capture = document.get("capture") if isinstance(document.get("capture"), dict) else document
    if not isinstance(capture, dict):
        raise ValueError("Capture JSON did not contain a capture object.")
    return capture


def load_capture(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return _capture_from_document(json.load(handle))


def _hsp_point_value(point: Any, key: str) -> float | None:
    if not isinstance(point, dict):
        return None
    return _as_float(point.get(key))


def hsp_points_for_stats(body: Any) -> list[dict[str, float]]:
    if not isinstance(body, dict):
        return []
    raw_points = body.get("points")
    if isinstance(raw_points, list):
        candidates = raw_points
    else:
        candidates = list(body.get("points_preview") or [])
        candidates.extend(body.get("points_tail_preview") or [])

    points: list[dict[str, float]] = []
    seen: set[tuple[float, float]] = set()
    for point in candidates:
        t_value = _hsp_point_value(point, "t")
        x_value = _hsp_point_value(point, "x")
        if t_value is None or x_value is None:
            continue
        key = (t_value, x_value)
        if key in seen:
            continue
        seen.add(key)
        points.append({"t": t_value, "x": x_value})
    points.sort(key=lambda item: item["t"])
    return points


def hsp_add_command_stats(command_history: list[Any]) -> list[dict[str, Any]]:
    stats: list[dict[str, Any]] = []
    for index, command in enumerate(command_history):
        if not isinstance(command, dict) or command.get("path") != "hsp/add":
            continue
        body = command.get("body") if isinstance(command.get("body"), dict) else {}
        points = hsp_points_for_stats(body)
        point_count = body.get("points")
        if isinstance(point_count, list):
            point_count = len(point_count)
        point_count = _as_int(point_count)
        if point_count is None:
            point_count = len(points)

        entry: dict[str, Any] = {
            "command_index": index,
            "ok": command.get("ok"),
            "status_code": command.get("status_code"),
            "elapsed_ms": command.get("elapsed_ms"),
            "point_count": point_count,
            "preview_point_count": len(points),
            "preview_partial": bool(point_count and len(points) < point_count),
            "flush": bool(body.get("flush")),
            "tail_point_stream_index": body.get("tail_point_stream_index"),
        }
        if points:
            intervals = [right["t"] - left["t"] for left, right in zip(points, points[1:])]
            deltas = [abs(right["x"] - left["x"]) for left, right in zip(points, points[1:])]
            entry.update(
                {
                    "first_point_time_ms": int(round(points[0]["t"])),
                    "last_preview_point_time_ms": int(round(points[-1]["t"])),
                    "first_x": round(points[0]["x"], 3),
                    "last_preview_x": round(points[-1]["x"], 3),
                }
            )
            if intervals:
                entry["preview_max_gap_ms"] = round(max(intervals), 1)
                entry["preview_mean_gap_ms"] = round(sum(intervals) / len(intervals), 1)
            if deltas:
                entry["preview_max_delta"] = round(max(deltas), 3)
        response = command.get("response") if isinstance(command.get("response"), dict) else {}
        hsp_state = response.get("hsp_state") if isinstance(response, dict) else None
        if isinstance(hsp_state, dict):
            entry["hsp_state"] = {
                key: hsp_state.get(key)
                for key in (
                    "current_time_ms",
                    "current_point",
                    "points",
                    "tail_point_stream_index",
                    "tail_point_stream_index_threshold",
                    "play_state",
                )
                if key in hsp_state
            }
        stats.append(entry)
    return stats


def summarize_capture(capture: dict[str, Any]) -> dict[str, Any]:
    motion_trace = [row for row in capture.get("motion_trace") or [] if isinstance(row, dict)]
    command_history = [row for row in capture.get("handy_command_history") or [] if isinstance(row, dict)]
    diagnostics = capture.get("after") if isinstance(capture.get("after"), dict) else {}

    path_counts: dict[str, int] = {}
    for command in command_history:
        path = str(command.get("path") or "")
        path_counts[path] = path_counts.get(path, 0) + 1

    hsp_add_stats = hsp_add_command_stats(command_history)
    hsp_add_preview_gaps = [
        stat["preview_max_gap_ms"]
        for stat in hsp_add_stats
        if isinstance(stat.get("preview_max_gap_ms"), (int, float))
    ]
    hsp_add_preview_deltas = [
        stat["preview_max_delta"]
        for stat in hsp_add_stats
        if isinstance(stat.get("preview_max_delta"), (int, float))
    ]
    replacement_counts: dict[str, int] = {}
    for row in motion_trace:
        kind = row.get("hsp_replacement_kind")
        if kind:
            key = str(kind)
            replacement_counts[key] = replacement_counts.get(key, 0) + 1

    return {
        "trace_rows": len(motion_trace),
        "command_rows": len(command_history),
        "path_counts": path_counts,
        "hsp_commands": sum(count for path, count in path_counts.items() if path.startswith("hsp/")),
        "hdsp_commands": sum(count for path, count in path_counts.items() if path.startswith("hdsp/")),
        "hamp_or_mode_commands": sum(
            count
            for path, count in path_counts.items()
            if path.startswith("hamp/") or path in {"slide", "mode", "mode2"}
        ),
        "failed_commands": sum(1 for command in command_history if command.get("ok") is False),
        "continuous_schemas": sorted(
            {
                str(row.get("continuous_schema"))
                for row in motion_trace
                if row.get("continuous_schema")
            }
        ),
        "hsp_add_batches": len(hsp_add_stats),
        "hsp_add_max_preview_gap_ms": max(hsp_add_preview_gaps) if hsp_add_preview_gaps else None,
        "hsp_add_max_preview_delta": max(hsp_add_preview_deltas) if hsp_add_preview_deltas else None,
        "hsp_replacement_counts": replacement_counts,
        "hsp_duplicate_suppressed_points": sum(
            int(row.get("hsp_duplicate_suppressed_points") or 0)
            for row in motion_trace
            if isinstance(row.get("hsp_duplicate_suppressed_points"), int)
        ),
        "api_v3_enabled": bool(diagnostics.get("api_v3_enabled")),
        "api_v3_key_configured": bool(diagnostics.get("api_v3_key_configured")),
        "api_v3_auth_failed": bool(diagnostics.get("api_v3_auth_failed")),
        "api_v3_unavailable_reason": diagnostics.get("api_v3_unavailable_reason") or "",
    }


def build_timeline(capture: dict[str, Any]) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    for index, row in enumerate(capture.get("motion_trace") or []):
        if not isinstance(row, dict):
            continue
        timeline.append(
            {
                "index": len(timeline),
                "kind": "trace",
                "source_index": index,
                "schema": row.get("continuous_schema") or "",
                "source": row.get("source") or "",
                "label": row.get("label") or "",
                "hsp_batch": row.get("hsp_batch") or "",
                "hsp_stream_index": row.get("hsp_stream_index"),
                "hsp_replacement_kind": row.get("hsp_replacement_kind") or "",
                "hsp_buffer_remaining_ms": row.get("hsp_buffer_remaining_ms"),
                "handy_path": row.get("handy_path") or "",
                "handy_ok": row.get("handy_ok"),
            }
        )
    for index, command in enumerate(capture.get("handy_command_history") or []):
        if not isinstance(command, dict):
            continue
        body = command.get("body") if isinstance(command.get("body"), dict) else {}
        points = hsp_points_for_stats(body)
        timeline.append(
            {
                "index": len(timeline),
                "kind": "command",
                "source_index": index,
                "path": command.get("path") or "",
                "ok": command.get("ok"),
                "status_code": command.get("status_code"),
                "elapsed_ms": command.get("elapsed_ms"),
                "hsp_point_count": len(points) if points else None,
                "hsp_first_point_time_ms": int(round(points[0]["t"])) if points else None,
                "hsp_last_preview_point_time_ms": int(round(points[-1]["t"])) if points else None,
            }
        )
    return timeline


def print_text_report(capture: dict[str, Any], summary: dict[str, Any], timeline: list[dict[str, Any]]) -> None:
    run = capture.get("run") if isinstance(capture.get("run"), dict) else {}
    print("Motion Capture Replay")
    print(f"backend={run.get('backend', '-')} firmware={run.get('firmware', '-')} active_mode={run.get('active_mode', '-')}")
    print(
        "trace_rows={trace_rows} command_rows={command_rows} hsp={hsp_commands} hdsp={hdsp_commands} hamp_or_mode={hamp_or_mode_commands} failed={failed_commands}".format(
            **summary
        )
    )
    if summary["path_counts"]:
        print("paths=" + ", ".join(f"{path}:{count}" for path, count in sorted(summary["path_counts"].items())))
    if summary["hsp_replacement_counts"]:
        print(
            "hsp_replacements="
            + ", ".join(f"{kind}:{count}" for kind, count in sorted(summary["hsp_replacement_counts"].items()))
        )
    if summary["hsp_add_max_preview_gap_ms"] is not None:
        print(f"hsp_add_max_preview_gap_ms={summary['hsp_add_max_preview_gap_ms']}")
    if summary["hsp_duplicate_suppressed_points"]:
        print(f"hsp_duplicate_suppressed_points={summary['hsp_duplicate_suppressed_points']}")
    print("timeline:")
    for event in timeline:
        if event["kind"] == "command":
            detail = f"#{event['source_index']} command {event['path']} ok={event.get('ok')}"
            if event.get("elapsed_ms") is not None:
                detail += f" elapsed={event['elapsed_ms']}ms"
            if event.get("hsp_point_count"):
                detail += (
                    f" points={event['hsp_point_count']}"
                    f" t={event['hsp_first_point_time_ms']}..{event['hsp_last_preview_point_time_ms']}ms"
                )
        else:
            detail = f"#{event['source_index']} trace {event.get('schema') or '-'} source={event.get('source') or '-'}"
            if event.get("hsp_batch"):
                detail += f" batch={event['hsp_batch']}"
            if event.get("hsp_replacement_kind"):
                detail += f" replacement={event['hsp_replacement_kind']}"
            if event.get("handy_path"):
                detail += f" handy={event['handy_path']} ok={event.get('handy_ok')}"
        print(f"  {detail}")


def replay_with_sleep(timeline: list[dict[str, Any]], scale: float) -> None:
    scale = max(0.0, float(scale or 0.0))
    if scale <= 0:
        return
    previous_elapsed = 0.0
    for event in timeline:
        elapsed = _as_float(event.get("elapsed_ms")) or 0.0
        delay = max(0.0, elapsed - previous_elapsed) / 1000.0 * scale
        if delay:
            time.sleep(delay)
        previous_elapsed = elapsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_json", help="Path to a Diagnostics motion transport capture JSON file.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable summary and timeline JSON.")
    parser.add_argument(
        "--sleep-scale",
        type=float,
        default=0.0,
        help="Optionally sleep between timeline events using command elapsed_ms deltas. 0 disables sleeping.",
    )
    args = parser.parse_args(argv)

    try:
        capture = load_capture(args.capture_json)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Could not read motion capture: {exc}", file=sys.stderr)
        return 2

    summary = summarize_capture(capture)
    timeline = build_timeline(capture)
    if args.sleep_scale:
        replay_with_sleep(timeline, args.sleep_scale)

    if args.json:
        json.dump(
            {
                "summary": summary,
                "hsp_add_stats": hsp_add_command_stats(capture.get("handy_command_history") or []),
                "timeline": timeline,
            },
            sys.stdout,
            indent=2,
        )
        print()
    else:
        print_text_report(capture, summary, timeline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
