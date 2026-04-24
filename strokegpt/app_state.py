from collections import deque
from dataclasses import dataclass, field
import threading


def default_ollama_pull_state():
    return {
        "state": "idle",
        "model": "",
        "message": "No model download running.",
        "completed": 0,
        "total": 0,
        "percent": None,
    }


def default_motion_training_state():
    return {
        "state": "idle",
        "pattern_id": "",
        "pattern_name": "",
        "message": "Motion training idle.",
        "last_feedback": "",
        "preview": False,
    }


@dataclass
class AppState:
    lock: threading.RLock = field(default_factory=threading.RLock)
    chat_history: deque = field(default_factory=lambda: deque(maxlen=20))
    messages_for_ui: deque = field(default_factory=deque)
    auto_mode_active_task: object | None = None
    current_mood: str = "Curious"
    use_long_term_memory: bool = True
    calibration_pos_mm: float = 0.0
    user_signal_event: threading.Event = field(default_factory=threading.Event)
    mode_message_event: threading.Event = field(default_factory=threading.Event)
    mode_message_queue: deque = field(default_factory=lambda: deque(maxlen=5))
    active_mode_name: str = ""
    active_mode_started_at: float | None = None
    active_mode_paused_at: float | None = None
    active_mode_paused_total: float = 0.0
    motion_pause_active: bool = False
    edging_start_time: float | None = None
    depth_test_lock: threading.Lock = field(default_factory=threading.Lock)
    ollama_pull_thread: threading.Thread | None = None
    ollama_pull_state: dict = field(default_factory=default_ollama_pull_state)
    motion_training_thread: threading.Thread | None = None
    motion_training_stop_event: threading.Event = field(default_factory=threading.Event)
    motion_training_state: dict = field(default_factory=default_motion_training_state)
    last_live_motion_pattern_id: str = ""
    special_persona_mode: str | None = None
    special_persona_interactions_left: int = 0

    def set_ollama_pull_state(self, **updates):
        with self.lock:
            self.ollama_pull_state.update(updates)
            return dict(self.ollama_pull_state)

    def ollama_pull_snapshot(self):
        with self.lock:
            return dict(self.ollama_pull_state)

    def motion_training_snapshot(self):
        with self.lock:
            return dict(self.motion_training_state)

    def set_motion_training_state(self, **updates):
        with self.lock:
            self.motion_training_state.update(updates)
            return dict(self.motion_training_state)

    def reset_motion_training_state(self):
        with self.lock:
            self.motion_training_state.clear()
            self.motion_training_state.update(default_motion_training_state())
            return dict(self.motion_training_state)


APP_STATE_EXPORTS = frozenset(AppState.__dataclass_fields__)
