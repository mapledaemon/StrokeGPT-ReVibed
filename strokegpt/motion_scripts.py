import random
import re
from collections import deque
from dataclasses import dataclass
from typing import Optional

from .motion import MotionTarget
from .motion_patterns import PATTERNS, expand_anchor_program, expand_pattern


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


AUTO_ARCS = (
    (
        ("warmup", "Curious", 24, 20, 24),
        ("shallow drift", "Teasing", 30, 18, 34),
        ("mid glide", "Playful", 38, 40, 56),
        ("full sweep", "Passionate", 48, 50, 86),
        ("deep pulse", "Anticipatory", 44, 78, 30),
        ("reset", "Loving", 26, 28, 26),
    ),
    (
        ("slow ladder", "Seductive", 22, 25, 36),
        ("steady climb", "Confident", 34, 42, 48),
        ("wide climb", "Excited", 44, 52, 70),
        ("quick shallow", "Playful", 52, 16, 24),
        ("settle", "Intimate", 32, 38, 44),
    ),
    (
        ("deep tease", "Teasing", 28, 72, 20),
        ("deep hold", "Dominant", 36, 84, 28),
        ("middle wave", "Passionate", 46, 48, 58),
        ("long release", "Breathless", 42, 50, 90),
        ("soft return", "Loving", 24, 24, 28),
    ),
)

MILKING_ARCS = (
    (
        ("milking-pressure-build", "Dominant", 54, 48, 70),
        ("milking-wide-pressure", "Passionate", 62, 54, 78),
        ("milking-deep-pulse", "Overwhelmed", 72, 76, 38),
        ("milking-fast-middle", "Excited", 78, 48, 46),
        ("milking-deep-finish", "Dominant", 68, 82, 34),
        ("milking-recover", "Afterglow", 28, 30, 28),
    ),
    (
        ("milking-steady-press", "Confident", 58, 44, 62),
        ("milking-short-burst", "Excited", 74, 34, 30),
        ("milking-full-drive", "Passionate", 66, 52, 88),
        ("milking-deep-squeeze", "Dominant", 76, 86, 24),
        ("milking-final-wave", "Breathless", 70, 58, 74),
    ),
)

EDGING_ARCS = (
    (
        ("edge-build-low", "Seductive", 24, 24, 32),
        ("edge-build-mid", "Anticipatory", 34, 42, 48),
        ("edge-hold", "Confident", 34, 32, 46),
        ("edge-tip-tease", "Playful", 42, 14, 18),
        ("edge-recover", "Loving", 18, 68, 48),
    ),
    (
        ("edge-slow-wide", "Intimate", 24, 48, 62),
        ("edge-shallow-snap", "Teasing", 46, 16, 20),
        ("edge-middle-hold", "Confident", 36, 44, 36),
        ("edge-deeper-risk", "Dominant", 48, 74, 30),
        ("edge-pull-back", "Loving", 14, 88, 18),
    ),
)

ARCS_BY_MODE = {
    "auto": AUTO_ARCS,
    "milking": MILKING_ARCS,
    "edging": EDGING_ARCS,
}


class MotionScriptPlanner:
    def __init__(self, mode, rng=None):
        self.mode = mode
        self.rng = rng or random.Random()
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
        pattern = PATTERNS.get(pattern_id)
        label = pattern.name if pattern else pattern_id
        target = MotionTarget(
            speed + self.rng.uniform(-3, 3),
            depth + self.rng.uniform(-5, 5),
            stroke_range + self.rng.uniform(-7, 7),
            label=label,
        ).clamped()
        frames = expand_pattern(pattern_id, current, target, rng=self.rng)
        if not frames:
            return [ScriptStep(target, mood=mood, delay_factor=self.rng.uniform(0.75, 1.15))]
        return [
            ScriptStep(frame.target, mood=mood, delay_factor=frame.delay_factor)
            for frame in frames
        ]

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
        clean_label = (label or "").lower()
        slug_label = _slug_label(label)
        for pattern in sorted(PATTERNS, key=len, reverse=True):
            if pattern in clean_label or slug_label == pattern or slug_label.startswith(f"{pattern}-"):
                return pattern
        return None

    def _pattern_feedback_steps(self, current, target, pattern):
        bridge = MotionTarget(
            (current.speed + target.speed) / 2,
            (current.depth + target.depth) / 2,
            (current.stroke_range + target.stroke_range) / 2,
            label=f"{target.label} bridge",
        ).clamped()
        steps = [ScriptStep(bridge, mood="Confident", message="Adjusting.", delay_factor=0.5)]
        mood_by_pattern = {
            "flick": "Playful",
            "flutter": "Playful",
            "pulse": "Dominant",
            "hold": "Confident",
            "wave": "Anticipatory",
            "ramp": "Anticipatory",
            "ladder": "Anticipatory",
            "surge": "Passionate",
            "sway": "Intimate",
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
            "edge-pull-back",
            "Dominant",
            8,
            88,
            18,
        )
        if not steps:
            steps = [
                ScriptStep(
                    MotionTarget(8, 88, 18, PATTERNS["edge-pull-back"].name).clamped(),
                    mood="Dominant",
                    delay_factor=0.6,
                )
            ]
        first_step = steps[0]
        steps[0] = ScriptStep(
            first_step.target,
            mood=first_step.mood,
            message=f"Backing off. Edge count: {edge_count}.",
            delay_factor=first_step.delay_factor,
        )
        steps.extend(
            self._pattern_cluster(
                steps[-1].target,
                "edge-recover",
                "Loving",
                intensity,
                68,
                48,
            )
        )
        steps.extend(
            self._pattern_cluster(
                steps[-1].target,
                "edge-hold",
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
