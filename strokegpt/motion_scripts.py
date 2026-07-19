import random
import re
from collections import deque
from dataclasses import dataclass
from typing import Optional

from .motion import LEGACY_BUILTIN_PATTERN_ALIASES, MotionTarget, canonical_motion_pattern_id
from .motion_patterns import (
    PATTERNS,
    continuous_anchor_motion_plan,
    continuous_motion_plan_from_pattern,
    expand_anchor_program,
    expand_pattern,
)


def _slug_label(value):
    cleaned = str(value or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-_")
    return cleaned


@dataclass(frozen=True)
class ScriptStep:
    target: MotionTarget
    mood: str = "Curious"
    message: Optional[str] = None
    delay_factor: float = 1.0
    hold_seconds_floor: float = 0.0


CONTINUOUS_STEP_CYCLE_HOLD_MULTIPLIER = 1.15
CONTINUOUS_MODE_PATTERN_REPEAT_MODES = {"milking", "edging"}
CONTINUOUS_MODE_PATTERN_REPEAT_STEPS = 3


def _continuous_hold_floor_for_pattern(pattern_id):
    pattern = PATTERNS.get(canonical_motion_pattern_id(pattern_id))
    if not pattern:
        return 0.0
    plan = continuous_motion_plan_from_pattern(pattern)
    if plan is None:
        return 0.0
    return max(0.0, float(plan.duration_seconds or 0.0) * CONTINUOUS_STEP_CYCLE_HOLD_MULTIPLIER)


def _slug_matches_pattern_id(slug_label, pattern_id):
    candidate = str(pattern_id or "").strip().lower()
    if not candidate:
        return False
    return slug_label == candidate or slug_label.startswith(f"{candidate}-")


def _label_matches_pattern_id(clean_label, pattern_id):
    candidate = str(pattern_id or "").strip().lower()
    if not candidate:
        return False
    return bool(re.search(rf"(?<![a-z0-9_-]){re.escape(candidate)}(?![a-z0-9_-])", clean_label))


def _pattern_id_from_label(label):
    clean_label = (label or "").lower()
    slug_label = _slug_label(label)
    candidates = sorted((*PATTERNS, *LEGACY_BUILTIN_PATTERN_ALIASES), key=len, reverse=True)
    for candidate in candidates:
        if _slug_matches_pattern_id(slug_label, candidate):
            return canonical_motion_pattern_id(candidate)
    for candidate in candidates:
        if _label_matches_pattern_id(clean_label, candidate):
            return canonical_motion_pattern_id(candidate)
    return None


def _continuous_hold_floor_for_target(target, pattern_id=None):
    if not isinstance(target, MotionTarget):
        return 0.0
    if target.motion_program:
        plan = continuous_anchor_motion_plan(target.motion_program)
        if plan is not None:
            return max(0.0, float(plan.duration_seconds or 0.0) * CONTINUOUS_STEP_CYCLE_HOLD_MULTIPLIER)
    if pattern_id:
        return _continuous_hold_floor_for_pattern(pattern_id)
    resolved_pattern_id = _pattern_id_from_label(target.label)
    return _continuous_hold_floor_for_pattern(resolved_pattern_id) if resolved_pattern_id else 0.0


AUTO_ARCS = (
    (
        ("stroke", "Curious", 24, 20, 24),
        ("tease", "Teasing", 30, 18, 34),
        ("stroke", "Playful", 38, 40, 56),
        ("stroke", "Passionate", 48, 50, 86),
        ("pulse", "Anticipatory", 44, 78, 30),
        ("tease", "Loving", 26, 28, 26),
    ),
    (
        ("tease", "Seductive", 22, 25, 36),
        ("tease", "Confident", 34, 42, 48),
        ("stroke", "Excited", 44, 52, 70),
        ("pulse", "Playful", 52, 16, 24),
        ("tease", "Intimate", 32, 38, 44),
    ),
    (
        ("tease", "Teasing", 28, 72, 20),
        ("tease", "Dominant", 36, 84, 28),
        ("stroke", "Passionate", 46, 48, 58),
        ("stroke", "Breathless", 42, 50, 90),
        ("tease", "Loving", 24, 24, 28),
    ),
)

MILKING_ARCS = (
    (
        ("pulse", "Dominant", 54, 66, 46),
        ("pulse", "Passionate", 62, 58, 68),
        ("pulse", "Overwhelmed", 72, 76, 38),
        ("pulse", "Excited", 78, 48, 46),
        ("pulse", "Dominant", 68, 82, 34),
        ("pulse", "Afterglow", 28, 30, 28),
    ),
    (
        ("pulse", "Confident", 58, 64, 48),
        ("pulse", "Excited", 74, 58, 30),
        ("pulse", "Passionate", 66, 52, 88),
        ("pulse", "Dominant", 76, 86, 24),
        ("pulse", "Breathless", 70, 58, 74),
    ),
)

EDGING_ARCS = (
    (
        ("tease", "Seductive", 24, 78, 28),
        ("tease", "Anticipatory", 34, 62, 42),
        ("tease", "Confident", 34, 42, 42),
        ("tease", "Playful", 42, 14, 18),
        ("tease", "Loving", 18, 68, 48),
    ),
    (
        ("tease", "Dominant", 28, 78, 28),
        ("tease", "Confident", 36, 52, 36),
        ("tease", "Intimate", 30, 54, 52),
        ("tease", "Teasing", 46, 16, 20),
        ("tease", "Loving", 14, 88, 18),
    ),
)

ARCS_BY_MODE = {
    "auto": AUTO_ARCS,
    "milking": MILKING_ARCS,
    "edging": EDGING_ARCS,
}


class MotionScriptPlanner:
    def __init__(self, mode, rng=None, continuous_patterns=False):
        self.mode = mode
        self.rng = rng or random.Random()
        self.continuous_patterns = bool(continuous_patterns)
        self.steps = deque()
        self.last_arc_index = None
        self.recent_labels = deque(maxlen=10)

    def next_step(self, current, feedback_target=None, edge_count=None):
        if feedback_target:
            self.steps = deque(self._feedback_steps(current, feedback_target))
        elif edge_count is not None:
            self.steps = deque(self._edge_reaction_steps(current, edge_count))
        elif not self.steps:
            self.steps = deque(self._build_arc(current))

        step = self.steps.popleft()
        self.recent_labels.append(step.target.label)
        return step

    def _build_arc(self, current):
        arcs = ARCS_BY_MODE.get(self.mode, AUTO_ARCS)
        arc_index = self.rng.randrange(len(arcs))
        if len(arcs) > 1 and arc_index == self.last_arc_index:
            arc_index = (arc_index + 1) % len(arcs)
        self.last_arc_index = arc_index

        base_arc = arcs[arc_index]
        steps = []
        previous = current.clamped()
        for pattern_id, mood, speed, depth, stroke_range in base_arc:
            pattern_steps = self._pattern_cluster(previous, pattern_id, mood, speed, depth, stroke_range)
            steps.extend(pattern_steps)
            if pattern_steps:
                previous = pattern_steps[-1].target
        return steps

    def _pattern_cluster(self, current, pattern_id, mood, speed, depth, stroke_range):
        pattern_id = canonical_motion_pattern_id(pattern_id)
        pattern = PATTERNS.get(pattern_id)
        label = pattern.name if pattern else pattern_id
        target = MotionTarget(
            speed + self.rng.uniform(-3, 3),
            depth + self.rng.uniform(-5, 5),
            stroke_range + self.rng.uniform(-7, 7),
            label=label,
        ).clamped()
        if self.continuous_patterns and pattern:
            hold_floor = _continuous_hold_floor_for_pattern(pattern_id)
            repeat_steps = (
                CONTINUOUS_MODE_PATTERN_REPEAT_STEPS
                if self.mode in CONTINUOUS_MODE_PATTERN_REPEAT_MODES
                else 1
            )
            steps = [
                ScriptStep(
                    target,
                    mood=mood,
                    delay_factor=self.rng.uniform(0.9, 1.12),
                    hold_seconds_floor=hold_floor,
                )
            ]
            previous_target = target
            for repeat_index in range(1, repeat_steps):
                varied = self._same_pattern_variation(previous_target, label)
                steps.append(
                    ScriptStep(
                        varied,
                        mood=mood,
                        delay_factor=self.rng.uniform(0.9, 1.12),
                        hold_seconds_floor=hold_floor,
                    )
                )
                previous_target = varied
            return steps
        frames = expand_pattern(pattern_id, current, target, rng=self.rng)
        if not frames:
            return [ScriptStep(target, mood=mood, delay_factor=self.rng.uniform(0.75, 1.15))]
        return [
            ScriptStep(frame.target, mood=mood, delay_factor=frame.delay_factor)
            for frame in frames
        ]

    def _same_pattern_variation(self, current, label):
        current = current.clamped()
        speed_delta = self.rng.uniform(4.0, 7.0)
        depth_delta = self.rng.uniform(5.5, 8.5)
        range_delta = self.rng.uniform(5.5, 8.5)
        speed_direction = -1.0 if current.speed >= 82 else 1.0
        depth_direction = -1.0 if current.depth >= 58 else 1.0
        range_direction = -1.0 if current.stroke_range >= 68 else 1.0
        return MotionTarget(
            current.speed + speed_delta * speed_direction,
            current.depth + depth_delta * depth_direction,
            current.stroke_range + range_delta * range_direction,
            label=label,
            motion_program=current.motion_program,
        ).clamped()

    def _varied_cluster(self, label, mood, speed, depth, stroke_range):
        cluster_size = self.rng.randint(1, 3)
        cluster = []
        for index in range(cluster_size):
            jittered = MotionTarget(
                speed + self.rng.uniform(-5, 5),
                depth + self.rng.uniform(-8, 8),
                stroke_range + self.rng.uniform(-10, 10),
                label=f"{label} {index + 1}",
            ).clamped()
            cluster.append(ScriptStep(jittered, mood=mood, delay_factor=self.rng.uniform(0.75, 1.25)))
        return cluster

    def _feedback_steps(self, current, target):
        target = target.clamped()
        if target.motion_program:
            return self._anchor_feedback_steps(current, target)

        pattern = self._pattern_from_label(target.label)
        if pattern:
            return self._pattern_feedback_steps(current, target, pattern)

        if self.continuous_patterns:
            return [
                ScriptStep(
                    target,
                    mood="Confident",
                    message="Adjusting.",
                    delay_factor=1.0,
                    hold_seconds_floor=_continuous_hold_floor_for_target(target),
                )
            ]

        midpoint = MotionTarget(
            (current.speed + target.speed) / 2,
            (current.depth + target.depth) / 2,
            (current.stroke_range + target.stroke_range) / 2,
            label=f"{target.label} bridge",
        ).clamped()
        return [
            ScriptStep(midpoint, mood="Confident", message="Adjusting.", delay_factor=0.6),
            ScriptStep(target, mood="Confident", delay_factor=0.85),
            ScriptStep(self._near(target, "variation"), mood="Playful", delay_factor=0.85),
            ScriptStep(self._near(target, "settle"), mood="Intimate", delay_factor=1.1),
        ]

    def _pattern_from_label(self, label):
        return _pattern_id_from_label(label)

    def _pattern_feedback_steps(self, current, target, pattern):
        pattern = canonical_motion_pattern_id(pattern)
        bridge = MotionTarget(
            (current.speed + target.speed) / 2,
            (current.depth + target.depth) / 2,
            (current.stroke_range + target.stroke_range) / 2,
            label=f"{target.label} bridge",
        ).clamped()
        if self.continuous_patterns:
            return [
                ScriptStep(
                    target,
                    mood="Confident",
                    message="Adjusting.",
                    delay_factor=1.0,
                    hold_seconds_floor=_continuous_hold_floor_for_pattern(pattern),
                )
            ]
        steps = [ScriptStep(bridge, mood="Confident", message="Adjusting.", delay_factor=0.5)]
        mood_by_pattern = {
            "stroke": "Passionate",
            "pulse": "Dominant",
            "tease": "Teasing",
        }
        frames = expand_pattern(pattern, current, target, rng=self.rng)
        steps.extend(
            ScriptStep(frame.target, mood=mood_by_pattern.get(pattern, "Confident"), delay_factor=frame.delay_factor)
            for frame in frames
        )
        return steps

    def _anchor_feedback_steps(self, current, target):
        bridge = MotionTarget(
            (current.speed + target.speed) / 2,
            (current.depth + target.depth) / 2,
            (current.stroke_range + target.stroke_range) / 2,
            label=f"{target.label} bridge",
        ).clamped()
        if self.continuous_patterns:
            return [
                ScriptStep(
                    target,
                    mood="Intimate",
                    message="Adjusting.",
                    delay_factor=1.0,
                    hold_seconds_floor=_continuous_hold_floor_for_target(target),
                )
            ]
        steps = [ScriptStep(bridge, mood="Confident", message="Adjusting.", delay_factor=0.5)]
        frames = expand_anchor_program(current, target, target.motion_program, rng=self.rng)
        steps.extend(
            ScriptStep(frame.target, mood="Intimate", delay_factor=frame.delay_factor)
            for frame in frames
        )
        return steps

    def _edge_reaction_steps(self, current, edge_count):
        intensity = min(18 + edge_count * 3, 32)
        steps = self._pattern_cluster(
            current.clamped(),
            "tease",
            "Dominant",
            8,
            88,
            18,
        )
        if not steps:
            steps = [
                ScriptStep(
                    MotionTarget(8, 88, 18, PATTERNS["tease"].name).clamped(),
                    mood="Dominant",
                    delay_factor=0.6,
                )
            ]
        first_step = steps[0]
        steps[0] = ScriptStep(
            first_step.target,
            mood=first_step.mood,
            message="Backing off for a moment.",
            delay_factor=first_step.delay_factor,
        )
        steps.extend(
            self._pattern_cluster(
                steps[-1].target,
                "tease",
                "Loving",
                intensity,
                68,
                48,
            )
        )
        steps.extend(
            self._pattern_cluster(
                steps[-1].target,
                "tease",
                "Confident",
                intensity,
                32,
                46,
            )
        )
        return steps

    def _near(self, target, suffix):
        return MotionTarget(
            target.speed + self.rng.uniform(-6, 6),
            target.depth + self.rng.uniform(-8, 8),
            target.stroke_range + self.rng.uniform(-8, 8),
            label=f"{target.label} {suffix}",
        ).clamped()
