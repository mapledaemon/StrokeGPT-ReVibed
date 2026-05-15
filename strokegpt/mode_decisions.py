"""LLM mode-decision coercion, request plumbing, and intensity helpers.

This module owns the shape and parsing of mode decisions returned by the
local model. It is deliberately separated from ``background_modes`` so the
orchestration loops there can focus on scheduling, pacing, and scripted
playback while the decision layer stays pure and testable in isolation.
"""

import math
import threading
from dataclasses import dataclass

from .mode_contracts import ModeCallbacks
from .motion import MotionTarget


MODE_DECISION_ACTIONS = {"continue", "hold_then_resume", "pull_back", "switch_to_milk", "stop"}
DEFAULT_AUTOSPEAK_SECONDS = 45.0
MIN_AUTOSPEAK_SECONDS = 0.0
MAX_AUTOSPEAK_SECONDS = 300.0


@dataclass(frozen=True)
class ModeDecision:
    action: str = "continue"
    duration_seconds: float | None = None
    intensity: int | None = None
    autospeak_seconds: float | None = None
    chat: str = ""
    source: str = "fallback"


def _coerce_mode_decision(raw, *, mode, event):
    return _coerce_mode_decision_with_autospeak_range(raw, mode=mode, event=event)


def _autospeak_range(min_seconds=None, max_seconds=None):
    try:
        low = float(min_seconds)
    except (TypeError, ValueError):
        low = MIN_AUTOSPEAK_SECONDS
    try:
        high = float(max_seconds)
    except (TypeError, ValueError):
        high = MAX_AUTOSPEAK_SECONDS
    low = max(MIN_AUTOSPEAK_SECONDS, min(MAX_AUTOSPEAK_SECONDS, low))
    high = max(MIN_AUTOSPEAK_SECONDS, min(MAX_AUTOSPEAK_SECONDS, high))
    return min(low, high), max(low, high)


def _coerce_mode_decision_with_autospeak_range(
    raw,
    *,
    mode,
    event,
    autospeak_min_seconds=None,
    autospeak_max_seconds=None,
):
    autospeak_min_seconds, autospeak_max_seconds = _autospeak_range(
        autospeak_min_seconds,
        autospeak_max_seconds,
    )
    if not isinstance(raw, dict):
        return ModeDecision()
    if not any(
        key in raw
        for key in (
            "action",
            "duration_seconds",
            "duration",
            "seconds",
            "intensity",
            "autospeak_seconds",
            "autospeak_interval_seconds",
            "next_autospeak_seconds",
            "speak_again_seconds",
            "chat",
            "message",
        )
    ):
        return ModeDecision()

    action = str(raw.get("action") or "").strip().lower().replace("-", "_").replace(" ", "_")
    action_aliases = {
        "": "continue",
        "resume": "hold_then_resume",
        "hold": "hold_then_resume",
        "hold_resume": "hold_then_resume",
        "hold_then_continue": "hold_then_resume",
        "milk": "switch_to_milk",
        "switch_milk": "switch_to_milk",
        "finish": "switch_to_milk",
        "end": "stop",
    }
    action = action_aliases.get(action, action)
    if action not in MODE_DECISION_ACTIONS:
        action = "continue"
    if mode == "milking" and action == "switch_to_milk":
        action = "continue"
    if event == "start" and mode == "milking" and action in {"pull_back", "hold_then_resume"}:
        action = "continue"
    if event == "start" and mode in {"edging", "milking", "freestyle"} and action == "stop":
        # Modes must not be ended by their own start decision; the
        # prompt forbids it but a small local model can still emit `stop` here.
        action = "continue"

    duration = None
    for key in ("duration_seconds", "duration", "seconds"):
        try:
            duration = float(raw.get(key))
            break
        except (TypeError, ValueError):
            duration = None
    if duration is not None:
        duration = max(10.0, min(180.0, duration))

    intensity = None
    try:
        intensity = int(round(float(raw.get("intensity"))))
    except (TypeError, ValueError):
        intensity = None
    if intensity is not None:
        intensity = max(0, min(100, intensity))

    autospeak_seconds = None
    for key in (
        "autospeak_seconds",
        "autospeak_interval_seconds",
        "next_autospeak_seconds",
        "speak_again_seconds",
    ):
        try:
            autospeak_seconds = float(raw.get(key))
            break
        except (TypeError, ValueError):
            autospeak_seconds = None
    if autospeak_seconds is not None:
        autospeak_seconds = max(
            autospeak_min_seconds,
            min(autospeak_max_seconds, autospeak_seconds),
        )

    chat = str(raw.get("chat") or raw.get("message") or "").strip()
    if chat.lower().startswith("llm connection error"):
        chat = ""
    if len(chat) > 240:
        chat = chat[:237].rstrip() + "..."

    return ModeDecision(
        action=action,
        duration_seconds=duration,
        intensity=intensity,
        autospeak_seconds=autospeak_seconds,
        chat=chat,
        source="llm",
    )


def _request_mode_decision(
    callbacks: ModeCallbacks,
    mode,
    event,
    *,
    edge_count=0,
    current_target=None,
):
    provider = callbacks.get("mode_decision")
    if not provider:
        return ModeDecision()
    try:
        raw = provider(
            mode=mode,
            event=event,
            edge_count=edge_count,
            current_target=current_target,
        )
    except Exception as exc:
        print(f"Mode decision failed: {exc}")
        return ModeDecision()
    autospeak_min_seconds, autospeak_max_seconds = _autospeak_range_from_callbacks(callbacks)
    return _coerce_mode_decision_with_autospeak_range(
        raw,
        mode=mode,
        event=event,
        autospeak_min_seconds=autospeak_min_seconds,
        autospeak_max_seconds=autospeak_max_seconds,
    )


def _start_mode_decision_request(
    callbacks: ModeCallbacks,
    mode,
    event,
    *,
    edge_count=0,
    current_target=None,
):
    result = {"decision": ModeDecision(), "ready": False}

    def request():
        try:
            result["decision"] = _request_mode_decision(
                callbacks,
                mode,
                event,
                edge_count=edge_count,
                current_target=current_target,
            )
        finally:
            result["ready"] = True

    thread = threading.Thread(target=request, daemon=True)
    thread.start()
    return thread, result


def _poll_mode_decision_request(thread, result):
    if result.get("ready"):
        return result.get("decision") or ModeDecision()
    if thread.is_alive():
        return None
    result["ready"] = True
    return result.get("decision") or ModeDecision()


def _step_limit_for_duration(decision, min_time, max_time, default_steps):
    if decision.duration_seconds is None:
        return default_steps
    average_step_time = max(0.1, (float(min_time) + float(max_time)) / 2.0)
    return max(1, min(180, int(math.ceil(decision.duration_seconds / average_step_time))))


def _target_with_intensity(target, intensity):
    if intensity is None:
        return target
    speed_factor = 0.75 + (intensity / 100.0) * 0.5
    range_factor = 0.85 + (intensity / 100.0) * 0.3
    return MotionTarget(
        target.speed * speed_factor,
        target.depth,
        target.stroke_range * range_factor,
        target.label,
        target.motion_program,
    ).clamped()


def _send_mode_decision_message(send_message, decision):
    if decision.chat and decision.source == "llm":
        send_message(decision.chat)


def _autospeak_range_from_callbacks(callbacks: ModeCallbacks):
    provider = callbacks.get("autospeak_range")
    if not provider:
        return MIN_AUTOSPEAK_SECONDS, MAX_AUTOSPEAK_SECONDS
    try:
        min_seconds, max_seconds = provider()
    except Exception:
        return MIN_AUTOSPEAK_SECONDS, MAX_AUTOSPEAK_SECONDS
    return _autospeak_range(min_seconds, max_seconds)


def _autospeak_interval_from_decision(
    decision,
    current_interval=None,
    *,
    min_seconds=None,
    max_seconds=None,
):
    min_seconds, max_seconds = _autospeak_range(min_seconds, max_seconds)
    if decision.autospeak_seconds is None:
        interval = DEFAULT_AUTOSPEAK_SECONDS if current_interval is None else float(current_interval)
        return max(min_seconds, min(max_seconds, interval))
    return max(
        min_seconds,
        min(max_seconds, float(decision.autospeak_seconds)),
    )


def _send_autospeak_message(callbacks: ModeCallbacks, decision):
    if not decision.chat or decision.source != "llm":
        return False
    send_chat = callbacks.get("send_chat")
    if not send_chat:
        return False
    send_chat(decision.chat)
    return True
