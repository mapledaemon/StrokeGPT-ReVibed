"""Freestyle planner helpers.

Pulled out of ``background_modes`` so the adaptive pattern selection,
scoring, and edge-reaction chaining can evolve without growing the mode
orchestration module. The orchestration loop (``freestyle_mode_logic``)
stays in ``background_modes``; this module owns the scoring, candidate
shaping, and chain planning that loop delegates to.
"""

import random
from dataclasses import dataclass, replace

from .mode_decisions import _target_with_intensity
from .motion import MotionTarget, _slugify_motion_pattern_id
from .motion_patterns import expand_motion_pattern
from .motion_scripts import MotionScriptPlanner


FREESTYLE_CHAIN_LENGTH = 4
FREESTYLE_EDGE_RESUME_CHAIN_LENGTH = 2
FREESTYLE_DECISION_GRACE_SECONDS = 0.05


@dataclass(frozen=True)
class FreestyleChoice:
    pattern_id: str
    pattern_name: str
    record: object
    target: MotionTarget
    score: float
    mood: str
    reason: str


# Kept as a module-level alias so the local ``_slug_pattern_id`` name used
# throughout the freestyle helpers stays short while delegating to the
# canonical implementation in ``motion``.
_slug_pattern_id = _slugify_motion_pattern_id


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


def _edge_reaction_steps(motion_controller, edge_count, intensity=None, rng=None):
    planner = MotionScriptPlanner("edging", rng=rng)
    steps = [planner.next_step(motion_controller.current_target(), edge_count=edge_count)]
    while planner.steps:
        steps.append(planner.steps.popleft())

    adjusted_steps = []
    for step in steps:
        target = _target_with_intensity(step.target, intensity)
        adjusted_steps.append(type(step)(target, mood=step.mood, message=step.message, delay_factor=step.delay_factor))
    return adjusted_steps


def _freestyle_choice_frames(choices, current, rng):
    frames = []
    for choice in choices:
        choice_frames = expand_motion_pattern(
            choice.record.to_motion_pattern(),
            current,
            choice.target,
            rng=rng,
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
    current = edge_steps[-1].target if edge_steps else motion_controller.current_target()
    resume_choices = _freestyle_choice_chain(
        resume_candidates,
        current,
        None,
        recent_ids,
        rng or random.Random(),
        length=FREESTYLE_EDGE_RESUME_CHAIN_LENGTH,
    )
    resume_frames, _current = _freestyle_choice_frames(resume_choices, current, rng or random.Random())
    frames = [*edge_steps, *resume_frames]

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
        speed + rng.uniform(-4.0, 4.0),
        depth + rng.uniform(-7.0, 7.0),
        stroke_range + rng.uniform(-8.0, 8.0),
        label=f"Freestyle: {pattern_name or pattern_id}",
    )
    return target.clamped()


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
        profile = _freestyle_profile(pattern_id, pattern_name)
        score = _freestyle_score(pattern_id, pattern_name, candidate, record, profile, current, feedback_target, recent_ids)
        target = _freestyle_target(pattern_id, pattern_name, profile, current, feedback_target, rng)
        reason = (
            f"Freestyle selecting {pattern_name}: {profile['kind']} profile, "
            f"weight {int(round(_candidate_weight(candidate, record)))}."
        )
        choices.append(FreestyleChoice(pattern_id, pattern_name, record, target, score, profile["mood"], reason))

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


def _apply_freestyle_choices(motion_controller, choices, rng):
    frames, _current = _freestyle_choice_frames(choices, motion_controller.current_target(), rng)
    if not frames:
        return False
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
