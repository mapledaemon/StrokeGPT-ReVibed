"""Typed contracts for long-running mode services and callbacks."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
import threading
from typing import Any, Protocol, TypedDict

from .motion import MotionTarget


class MotionService(Protocol):
    def current_target(self) -> MotionTarget:
        ...

    def apply_target(self, target: MotionTarget, source: str = "target") -> Any:
        ...

    def apply_position_frames(
        self,
        frames: Sequence[Any],
        *,
        stop_after: bool = False,
        source: str = "pattern preview",
        final_stop_on_target: bool = True,
    ) -> bool:
        ...

    def stop(self) -> Any:
        ...

    def pause(self) -> Any:
        ...

    def resume(self) -> Any:
        ...


class ModeServices(TypedDict, total=False):
    llm: object
    handy: object
    motion: MotionService


class FreestyleCandidate(TypedDict, total=False):
    id: str
    name: str
    source: str
    enabled: bool
    weight: object
    feedback: Mapping[str, object]
    record: object


class ModeDecisionProvider(Protocol):
    def __call__(
        self,
        *,
        mode: str,
        event: str,
        edge_count: int = 0,
        current_target: MotionTarget | None = None,
    ) -> object:
        ...


class ModeCallbacks(TypedDict, total=False):
    send_message: Callable[[str], None]
    get_context: Callable[[], dict[str, Any]]
    get_timings: Callable[[str], tuple[float, float]]
    on_stop: Callable[[], None]
    update_mood: Callable[[str], None]
    user_signal_event: threading.Event
    message_event: threading.Event
    message_queue: deque[str]
    remember_pattern: Callable[[MotionTarget | None], object]
    remember_pattern_id: Callable[[str], object]
    freestyle_candidates: Callable[[], Iterable[FreestyleCandidate]]
    allow_llm_edge_in_freestyle: Callable[[], bool]
    set_mode_name: Callable[[str], None]
    mode_decision: ModeDecisionProvider
    pause_event: threading.Event


ModeLogic = Callable[[threading.Event, ModeServices, ModeCallbacks], None]


__all__ = [
    "FreestyleCandidate",
    "ModeCallbacks",
    "ModeDecisionProvider",
    "ModeLogic",
    "ModeServices",
    "MotionService",
]
