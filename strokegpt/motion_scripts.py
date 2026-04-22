import random
from collections import deque
from dataclasses import dataclass
from typing import Optional

from .motion import MotionTarget
from .motion_patterns import expand_anchor_program, expand_pattern


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
        ("pressure build", "Dominant", 54, 48, 70),
        ("wide pressure", "Passionate", 62, 54, 78),
        ("deep pulse", "Overwhelmed", 72, 76, 38),
        ("fast middle", "Excited", 78, 48, 46),
        ("deep finish", "Dominant", 68, 82, 34),
        ("recover", "Afterglow", 28, 30, 28),
    ),
    (
        ("steady press", "Confident", 58, 44, 62),
        ("short burst", "Excited", 74, 34, 30),
        ("full drive", "Passionate", 66, 52, 88),
        ("deep squeeze", "Dominant", 76, 86, 24),
        ("final wave", "Breathless", 70, 58, 74),
    ),
)

EDGING_ARCS = (
    (
        ("build low", "Seductive", 24, 24, 32),
        ("build mid", "Anticipatory", 34, 42, 48),
        ("hold", "Confident", 38, 50, 42),
        ("tip tease", "Playful", 42, 14, 18),
        ("recover", "Loving", 16, 14, 14),
    ),
    (
        ("slow wide", "Intimate", 24, 48, 62),
        ("shallow snap", "Teasing", 46, 16, 20),
        ("middle hold", "Confident", 36, 44, 36),
        ("deeper risk", "Dominant", 48, 74, 30),
        ("pull back", "Loving", 14, 12, 12),
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
            self.steps = deque(self._edge_reaction_steps(edge_count))
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
        steps = [ScriptStep(current.clamped(), mood="Curious", delay_factor=0.5)]
        for label, mood, speed, depth, stroke_range in base_arc:
            steps.extend(self._varied_cluster(label, mood, speed, depth, stroke_range))
        return steps

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
        for pattern in ("flick", "flutter", "pulse", "hold", "wave", "ramp", "ladder", "surge", "sway", "tease"):
            if pattern in clean_label:
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

    def _edge_reaction_steps(self, edge_count):
        intensity = min(18 + edge_count * 3, 32)
        return [
            ScriptStep(MotionTarget(8, 10, 10, "pull back").clamped(), mood="Dominant", message=f"Backing off. Edge count: {edge_count}.", delay_factor=0.6),
            ScriptStep(MotionTarget(intensity, 16, 16, "recover").clamped(), mood="Loving", delay_factor=1.2),
            ScriptStep(MotionTarget(intensity + 8, 28, 26, "restart").clamped(), mood="Teasing", delay_factor=1.0),
        ]

    def _near(self, target, suffix):
        return MotionTarget(
            target.speed + self.rng.uniform(-6, 6),
            target.depth + self.rng.uniform(-8, 8),
            target.stroke_range + self.rng.uniform(-8, 8),
            label=f"{target.label} {suffix}",
        ).clamped()
