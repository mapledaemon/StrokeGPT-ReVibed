"""Freestyle planner helpers.

Pulled out of ``background_modes`` so the adaptive pattern selection,
scoring, and edge-reaction chaining can evolve without growing the mode
orchestration module. The orchestration loop (``freestyle_mode_logic``)
stays in ``background_modes``; this module owns the scoring, candidate
shaping, and chain planning that loop delegates to.
"""

import inspect
import random
from dataclasses import dataclass, replace

from .mode_decisions import _target_with_intensity
from .motion import MotionTarget, _slugify_motion_pattern_id
from .motion_patterns import expand_motion_pattern
from .motion_scripts import MotionScriptPlanner


FREESTYLE_CHAIN_LENGTH = 4
FREESTYLE_EDGE_RESUME_CHAIN_LENGTH = 2
FREESTYLE_DECISION_GRACE_SECONDS = 0.05
FREESTYLE_CONTINUOUS_MIN_HOLD_SECONDS = 8.0
FREESTYLE_CONTINUOUS_MAX_HOLD_SECONDS = 24.0
FREESTYLE_CONTINUOUS_CYCLE_HOLD_MULTIPLIER = 1.15
FREESTYLE_CONTINUOUS_PATTERN_REPEAT_STEPS = 2


@dataclass(frozen=True)
class FreestyleChoice:
    pattern_id: str
    pattern_name: str
    record: object
    target: MotionTarget
    score: float
    mood: str
    reason: str
    debug_reason: str = ""


# Kept as a module-level alias so the local ``_slug_pattern_id`` name used
# throughout the freestyle helpers stays short while delegating to the
# canonical implementation in ``motion``.
_slug_pattern_id = _slugify_motion_pattern_id


def _semantic_target(motion_controller):
    getter = getattr(motion_controller, "semantic_target", None)
    return getter() if callable(getter) else motion_controller.current_target()


def _freestyle_milk_style_target(decision):
    intensity = decision.intensity
    if intensity is None:
        intensity = 62
    intensity = max(0, min(100, int(intensity)))

    return MotionTarget(
        42 + intensity * 0.36,
        56 + intensity * 0.10,
        58 + intensity * 0.30,
        label="milking",
    ).clamped()


def _freestyle_close_style_duration(decision, min_time, max_time):
    if decision.duration_seconds is not None:
        return decision.duration_seconds
    return max(8.0, min(30.0, ((float(min_time) + float(max_time)) / 2.0) * FREESTYLE_CHAIN_LENGTH))


def _allow_freestyle_edge(callbacks):
    value = callbacks.get("allow_llm_edge_in_freestyle", True)
    if callable(value):
        value = value()
    return bool(value)


def _freestyle_decision_with_permissions(decision, callbacks):
    if _allow_freestyle_edge(callbacks):
        return decision
    if decision.action in {"hold_then_resume", "pull_back", "continue"}:
        return replace(decision, action="switch_to_milk", chat="Switching to milk-style Freestyle.")
    return decision


def _timed_pattern_backend(motion_controller):
    return getattr(motion_controller, "backend", "") in {"continuous", "position"}


def _edge_reaction_steps(motion_controller, edge_count, intensity=None, rng=None):
    planner = MotionScriptPlanner(
        "edging",
        rng=rng,
        continuous_patterns=_timed_pattern_backend(motion_controller),
    )
    steps = [planner.next_step(_semantic_target(motion_controller), edge_count=edge_count)]
    while planner.steps:
        steps.append(planner.steps.popleft())

    adjusted_steps = []
    for step in steps:
        target = _target_with_intensity(step.target, intensity)
        adjusted_steps.append(type(step)(target, mood=step.mood, message=step.message, delay_factor=step.delay_factor))
    return adjusted_steps


def _freestyle_choice_frames(
    choices,
    current,
    rng,
    *,
    preserve_timing=False,
    base_step_seconds=0.25,
):
    frames = []
    for choice in choices:
        choice_frames = expand_motion_pattern(
            choice.record.to_motion_pattern(),
            current,
            choice.target,
            rng=rng,
            preserve_timing=preserve_timing,
            base_step_seconds=base_step_seconds,
        )
        if not choice_frames:
            continue
        frames.extend(choice_frames)
        current = choice_frames[-1].target
    return frames, current


def _apply_freestyle_edge_reaction(
    motion_controller,
    edge_count,
    intensity=None,
    rng=None,
    resume_candidates=(),
    recent_ids=(),
):
    edge_steps = _edge_reaction_steps(motion_controller, edge_count, intensity=intensity, rng=rng)
    current = edge_steps[-1].target if edge_steps else _semantic_target(motion_controller)
    resume_choices = _freestyle_choice_chain(
        resume_candidates,
        current,
        None,
        recent_ids,
        rng or random.Random(),
        length=FREESTYLE_EDGE_RESUME_CHAIN_LENGTH,
    )
    backend = getattr(motion_controller, "backend", "")
    if backend == "continuous":
        target = edge_steps[0].target if edge_steps else (resume_choices[0].target if resume_choices else None)
        if target is not None and hasattr(motion_controller, "apply_continuous_target"):
            return motion_controller.apply_continuous_target(
                target,
                source="freestyle edge reaction",
            ), edge_steps, resume_choices
        return False, edge_steps, resume_choices

    preserve_timing = backend == "position"
    resume_frames, _current = _freestyle_choice_frames(
        resume_choices,
        current,
        rng or random.Random(),
        preserve_timing=preserve_timing,
        base_step_seconds=getattr(motion_controller, "step_delay", 0.25),
    )
    frames = [*edge_steps, *resume_frames]

    if preserve_timing and hasattr(motion_controller, "apply_position_frames"):
        return motion_controller.apply_position_frames(
            frames,
            source="freestyle edge reaction",
            final_stop_on_target=False,
        ), edge_steps, resume_choices
    if backend == "hamp" and hasattr(motion_controller, "apply_frames"):
        return motion_controller.apply_frames(
            frames,
            source="freestyle edge reaction",
        ), edge_steps, resume_choices
    if hasattr(motion_controller, "apply_position_frames"):
        return motion_controller.apply_position_frames(
            frames,
            source="freestyle edge reaction",
            final_stop_on_target=False,
        ), edge_steps, resume_choices
    return False, edge_steps, resume_choices


# Freestyle candidate helpers expect the canonical ``FreestyleCandidate``
# dict shape produced by ``web._freestyle_candidate_patterns()`` (see
# ``strokegpt.mode_contracts.FreestyleCandidate``): a mapping with at least
# an ``id``/``record`` pair plus optional ``name``, ``enabled``, ``weight``,
# and ``feedback`` fields. Callers passing a bare record-like object are no
# longer supported — the historical duck-typing fallback was removed once
# every caller produced the canonical dict.
def _candidate_record(candidate):
    return candidate.get("record")


def _candidate_id(candidate, record):
    return _slug_pattern_id(
        candidate.get("id")
        or candidate.get("pattern_id")
        or getattr(record, "pattern_id", "")
        or getattr(record, "name", "")
    )


def _candidate_name(candidate, record, pattern_id):
    return str(
        candidate.get("name")
        or getattr(record, "name", "")
        or pattern_id
    ).strip()


def _candidate_weight(candidate, record):
    weight = candidate.get("weight")
    feedback = candidate.get("feedback") or getattr(record, "feedback", None) or {}
    if weight is None and isinstance(feedback, dict):
        weight = 50 + int(feedback.get("thumbs_up") or 0) * 12
        weight += int(feedback.get("neutral") or 0) * 2
        weight -= int(feedback.get("thumbs_down") or 0) * 18
    try:
        return max(0.0, min(100.0, float(weight if weight is not None else 50)))
    except (TypeError, ValueError):
        return 50.0


def _candidate_enabled(candidate, record):
    if candidate.get("enabled", getattr(record, "enabled", True)) is False:
        return False
    if _candidate_weight(candidate, record) <= 0:
        return False
    return True


def _candidate_allowed_for_routine_freestyle(pattern_id, pattern_name, feedback_target):
    text = _slug_pattern_id(f"{pattern_id} {pattern_name}")
    is_edge_pattern = pattern_id.startswith("edge-")
    is_staccato_pattern = any(
        word in text for word in ("flick", "flutter", "snap", "burst")
    )
    if not is_edge_pattern and not is_staccato_pattern:
        return True
    if not feedback_target:
        return False
    requested = _slug_pattern_id(feedback_target.label)
    return bool("edge" in requested or pattern_id in requested or requested in text)


def _freestyle_profile(pattern_id, pattern_name):
    text = f"{pattern_id} {pattern_name}".lower()
    profile = {
        "speed": 40.0,
        "depth": 50.0,
        "range": 58.0,
        "mood": "Playful",
        "kind": "balanced",
    }
    if any(word in text for word in ("flick", "flutter", "snap", "burst")):
        profile.update({"speed": 58.0, "depth": 22.0, "range": 24.0, "mood": "Playful", "kind": "quick-tip"})
    elif any(word in text for word in ("hold", "press", "squeeze")):
        profile.update({"speed": 30.0, "depth": 62.0, "range": 30.0, "mood": "Confident", "kind": "pressure"})
    elif any(word in text for word in ("wide", "full", "stroke", "wave", "sway")):
        profile.update({"speed": 42.0, "depth": 50.0, "range": 82.0, "mood": "Passionate", "kind": "wide"})
    elif any(word in text for word in ("ramp", "build", "ladder", "surge", "climb")):
        profile.update({"speed": 46.0, "depth": 54.0, "range": 68.0, "mood": "Anticipatory", "kind": "build"})
    elif any(word in text for word in ("tease", "edge", "tip")):
        profile.update({"speed": 34.0, "depth": 24.0, "range": 30.0, "mood": "Teasing", "kind": "tease"})
    elif any(word in text for word in ("deep", "base")):
        profile.update({"speed": 38.0, "depth": 82.0, "range": 36.0, "mood": "Dominant", "kind": "deep"})
    elif "milk" in text:
        profile.update({"speed": 60.0, "depth": 58.0, "range": 70.0, "mood": "Passionate", "kind": "finish"})
    return profile


def _blend(a, b, amount):
    return a + (b - a) * max(0.0, min(1.0, amount))


def _freestyle_target(pattern_id, pattern_name, profile, current, feedback_target, rng):
    if feedback_target:
        speed = _blend(profile["speed"], feedback_target.speed, 0.65)
        depth = _blend(profile["depth"], feedback_target.depth, 0.65)
        stroke_range = _blend(profile["range"], feedback_target.stroke_range, 0.65)
    else:
        speed = _blend(profile["speed"], max(12.0, current.speed), 0.18)
        depth = _blend(profile["depth"], current.depth, 0.12)
        stroke_range = _blend(profile["range"], current.stroke_range, 0.16)
    target = MotionTarget(
        speed + rng.uniform(-2.0, 2.0),
        depth + rng.uniform(-3.5, 3.5),
        stroke_range + rng.uniform(-4.0, 4.0),
        label=f"Freestyle: {pattern_name or pattern_id}",
    )
    return target.clamped()


def _freestyle_continuous_hold_seconds(choice, min_time, max_time, rng):
    base = rng.uniform(float(min_time or 0.0), float(max_time or 0.0))
    cycle_seconds = 0.0
    try:
        from .motion_patterns import continuous_motion_plan_from_pattern

        plan = continuous_motion_plan_from_pattern(choice.record.to_motion_pattern())
        if plan is not None:
            cycle_seconds = float(getattr(plan, "duration_seconds", 0.0) or 0.0)
    except Exception:
        cycle_seconds = 0.0
    hold_floor = max(
        FREESTYLE_CONTINUOUS_MIN_HOLD_SECONDS,
        cycle_seconds * FREESTYLE_CONTINUOUS_CYCLE_HOLD_MULTIPLIER,
    )
    return min(FREESTYLE_CONTINUOUS_MAX_HOLD_SECONDS, max(base, hold_floor))


def _freestyle_choice_can_repeat(choice):
    source = str(getattr(choice.record, "source", "") or "").lower()
    if source in {"imported", "trained", "user"}:
        return False
    return callable(getattr(choice.record, "to_motion_pattern", None))


def _freestyle_repeat_choice(choice, current, rng):
    current = current.clamped()
    speed_delta = rng.uniform(4.0, 7.0)
    speed_direction = -1.0 if current.speed >= 82 else 1.0
    target = MotionTarget(
        current.speed + speed_delta * speed_direction,
        current.depth + rng.uniform(-3.0, 3.0),
        current.stroke_range + rng.uniform(-4.0, 4.0),
        label=choice.target.label,
    ).clamped()
    return replace(
        choice,
        target=target,
        reason="Holding the same Freestyle rhythm a little longer.",
        debug_reason=f"{choice.debug_reason}; same-pattern repeat",
    )


def _freestyle_flow_target(choice):
    target = choice.target.clamped()
    return MotionTarget(
        target.speed,
        target.depth,
        target.stroke_range,
        label="freestyle flow",
    ).clamped()


def _call_generated_target(motion_controller, target, *, source, trace_metadata=None):
    apply_generated = getattr(motion_controller, "apply_generated_target", None)
    if not callable(apply_generated):
        return False
    try:
        params = inspect.signature(apply_generated).parameters
        accepts_metadata = "trace_metadata" in params or any(
            param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
        )
    except (TypeError, ValueError):
        accepts_metadata = True
    if accepts_metadata:
        result = apply_generated(target, source=source, trace_metadata=trace_metadata)
    else:
        result = apply_generated(target, source=source)
    return True if result is None else bool(result)


def _freestyle_score(pattern_id, pattern_name, candidate, record, profile, current, feedback_target, recent_ids):
    weight = _candidate_weight(candidate, record)
    score = 12.0 + weight
    recent_penalty = sum(1 for recent_id in recent_ids if recent_id == pattern_id) * 34.0
    score -= recent_penalty
    if pattern_id not in recent_ids:
        score += 18.0

    if feedback_target:
        requested = _slug_pattern_id(feedback_target.label)
        text = _slug_pattern_id(f"{pattern_id} {pattern_name}")
        if pattern_id and (pattern_id in requested or requested in text):
            score += 120.0
        score += max(0.0, 35.0 - abs(profile["speed"] - feedback_target.speed) * 0.45)
        score += max(0.0, 35.0 - abs(profile["depth"] - feedback_target.depth) * 0.45)
        score += max(0.0, 35.0 - abs(profile["range"] - feedback_target.stroke_range) * 0.35)
    else:
        if current.speed >= 58 and profile["speed"] >= 48:
            score += 18.0
        if current.speed <= 24 and profile["speed"] <= 38:
            score += 12.0
        if current.stroke_range >= 72 and profile["range"] >= 68:
            score += 14.0
        if current.depth >= 70 and profile["depth"] >= 60:
            score += 10.0

    return max(1.0, score)


def _freestyle_narration(profile, feedback_target):
    if feedback_target:
        return "Following that direction in Freestyle."
    by_kind = {
        "quick-tip": "Keeping Freestyle quick and shallow.",
        "pressure": "Adding slower pressure in Freestyle.",
        "wide": "Opening Freestyle into wider strokes.",
        "build": "Building Freestyle up gradually.",
        "tease": "Keeping Freestyle light and teasing.",
        "deep": "Moving Freestyle deeper.",
        "finish": "Pushing Freestyle into a stronger finish rhythm.",
        "balanced": "Keeping Freestyle varied.",
    }
    return by_kind.get(profile.get("kind"), "Keeping Freestyle varied.")


def _weighted_freestyle_choice(choices, rng):
    if not choices:
        return None
    total = sum(max(1.0, choice.score) for choice in choices)
    roll = rng.uniform(0.0, total)
    running = 0.0
    for choice in choices:
        running += max(1.0, choice.score)
        if roll <= running:
            return choice
    return choices[-1]


def _freestyle_explicit_match(pattern_id, pattern_name, feedback_target):
    if not feedback_target:
        return False
    requested = _slug_pattern_id(feedback_target.label)
    text = _slug_pattern_id(f"{pattern_id} {pattern_name}")
    return bool(pattern_id and (pattern_id in requested or requested in text))


def _choose_freestyle_pattern(candidates, current, feedback_target=None, recent_ids=(), rng=None):
    rng = rng or random.Random()
    choices = []
    for candidate in candidates or ():
        if not isinstance(candidate, dict):
            # ``FreestyleCandidate`` is the canonical shape; reject anything
            # else (e.g., bare records) instead of silently mishandling it.
            continue
        record = _candidate_record(candidate)
        pattern_id = _candidate_id(candidate, record)
        if not pattern_id or not record or not _candidate_enabled(candidate, record):
            continue
        if not hasattr(record, "to_motion_pattern"):
            continue
        pattern_name = _candidate_name(candidate, record, pattern_id)
        if not _candidate_allowed_for_routine_freestyle(pattern_id, pattern_name, feedback_target):
            continue
        profile = _freestyle_profile(pattern_id, pattern_name)
        score = _freestyle_score(pattern_id, pattern_name, candidate, record, profile, current, feedback_target, recent_ids)
        target = _freestyle_target(pattern_id, pattern_name, profile, current, feedback_target, rng)
        debug_reason = (
            f"Freestyle selecting {pattern_name}: {profile['kind']} profile, "
            f"weight {int(round(_candidate_weight(candidate, record)))}."
        )
        reason = _freestyle_narration(profile, feedback_target)
        choices.append(FreestyleChoice(
            pattern_id,
            pattern_name,
            record,
            target,
            score,
            profile["mood"],
            reason,
            debug_reason,
        ))

    choices.sort(key=lambda choice: choice.score, reverse=True)
    explicit_matches = [
        choice
        for choice in choices
        if _freestyle_explicit_match(choice.pattern_id, choice.pattern_name, feedback_target)
    ]
    if explicit_matches:
        return explicit_matches[0]
    top_choices = choices[:8]
    return _weighted_freestyle_choice(top_choices, rng)


def _freestyle_choice_chain(candidates, current, feedback_target, recent_ids, rng, length=FREESTYLE_CHAIN_LENGTH):
    choices = []
    planned_recent = list(recent_ids)
    planned_current = current
    for index in range(max(1, int(length))):
        choice = _choose_freestyle_pattern(
            candidates,
            planned_current,
            feedback_target=feedback_target if index == 0 else None,
            recent_ids=tuple(planned_recent),
            rng=rng,
        )
        if not choice:
            break
        choices.append(choice)
        planned_recent.append(choice.pattern_id)
        planned_recent[:] = planned_recent[-8:]
        planned_current = choice.target
    return choices


def _apply_freestyle_choices(
    motion_controller,
    choices,
    rng,
    trace_metadata=None,
):
    backend = getattr(motion_controller, "backend", "")
    if backend == "continuous":
        if not choices:
            return False
        choice = choices[0]
        record_source = str(getattr(choice.record, "source", "") or "").lower()
        apply_authored = getattr(motion_controller, "apply_authored_actions", None)
        if record_source == "fixed":
            flow_metadata = dict(trace_metadata or {})
            flow_metadata.setdefault("freestyle_fixed_pattern_transport", "area_focus")
            flow_metadata.setdefault("freestyle_fixed_pattern_id", choice.pattern_id)
            flow_metadata.setdefault("freestyle_fixed_pattern_name", choice.pattern_name)
            if _call_generated_target(
                motion_controller,
                _freestyle_flow_target(choice),
                source="freestyle planner",
                trace_metadata=flow_metadata,
            ):
                return True
        if callable(apply_authored) and record_source in {"imported", "trained", "user"}:
            return apply_authored(
                getattr(choice.record, "actions", ()) or (),
                choice.target,
                source="freestyle planner",
                trace_metadata=trace_metadata,
            )
        apply_pattern = getattr(motion_controller, "apply_continuous_pattern", None)
        if callable(apply_pattern):
            try:
                pattern = choice.record.to_motion_pattern()
            except Exception:
                pattern = None
            if pattern is not None:
                return apply_pattern(
                    pattern,
                    choice.target,
                    source="freestyle planner",
                    trace_metadata=trace_metadata,
                )
        apply_continuous = getattr(motion_controller, "apply_continuous_target", None)
        if callable(apply_continuous):
            return apply_continuous(
                choice.target,
                source="freestyle planner",
                trace_metadata=trace_metadata,
            )
        return False

    preserve_timing = backend == "position"
    frames, _current = _freestyle_choice_frames(
        choices,
        _semantic_target(motion_controller),
        rng,
        preserve_timing=preserve_timing,
        base_step_seconds=getattr(motion_controller, "step_delay", 0.25),
    )
    if not frames:
        return False
    if preserve_timing and hasattr(motion_controller, "apply_position_frames"):
        return motion_controller.apply_position_frames(
            frames,
            source="freestyle planner",
            final_stop_on_target=False,
        )
    if backend == "hamp" and hasattr(motion_controller, "apply_frames"):
        return motion_controller.apply_frames(
            frames,
            source="freestyle planner",
        )
    if hasattr(motion_controller, "apply_position_frames"):
        return motion_controller.apply_position_frames(
            frames,
            source="freestyle planner",
            final_stop_on_target=False,
        )
    return False


def _record_freestyle_edge_playback(edge_steps, resume_choices, remember_pattern_id, recent_ids, update_mood):
    for played_choice in resume_choices:
        remember_pattern_id(played_choice.pattern_id)
        recent_ids.append(played_choice.pattern_id)
    recent_ids[:] = recent_ids[-8:]
    if resume_choices:
        update_mood(resume_choices[-1].mood)
    elif edge_steps:
        update_mood(edge_steps[-1].mood)
    return len(resume_choices)
