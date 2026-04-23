import math
import random
import threading
import time

from dataclasses import dataclass, replace

from .motion import IntentMatcher, MotionTarget, _slugify_motion_pattern_id
from .motion_patterns import expand_motion_pattern
from .motion_scripts import MotionScriptPlanner


INTENT_MATCHER = IntentMatcher()
MODE_DECISION_ACTIONS = {"continue", "hold_then_resume", "pull_back", "switch_to_milk", "stop"}


@dataclass(frozen=True)
class ModeDecision:
    action: str = "continue"
    duration_seconds: float | None = None
    intensity: int | None = None
    chat: str = ""
    source: str = "fallback"


@dataclass(frozen=True)
class FreestyleChoice:
    pattern_id: str
    pattern_name: str
    record: object
    target: MotionTarget
    score: float
    mood: str
    reason: str


FREESTYLE_CHAIN_LENGTH = 4
FREESTYLE_EDGE_RESUME_CHAIN_LENGTH = 2
FREESTYLE_DECISION_GRACE_SECONDS = 0.05
EDGE_START_MIN_STEPS = 12
EDGE_PROGRESS_MIN_STEPS = 10


class AutoModeThread(threading.Thread):
    def __init__(self, mode_func, initial_message, services, callbacks, mode_name="auto", initial_delay=0.1):
        super().__init__()
        self.name = mode_name
        self._mode_func = mode_func
        self._initial_message = initial_message
        self._services = services
        self._callbacks = callbacks
        self._initial_delay = initial_delay
        self._stop_event = threading.Event()
        self.daemon = True

    def run(self):
        message_callback = self._callbacks.get("send_message")
        motion_controller = self._services.get("motion")

        if message_callback:
            message_callback(self._initial_message)

        try:
            if self._stop_event.wait(self._initial_delay):
                return
            self._mode_func(self._stop_event, self._services, self._callbacks)
        except Exception as e:
            print(f"Auto mode crashed: {e}")
        finally:
            if motion_controller:
                motion_controller.stop()

            stop_callback = self._callbacks.get("on_stop")
            if stop_callback:
                stop_callback()

            if message_callback:
                message_callback("Okay, you're in control now.")

    def stop(self):
        self._stop_event.set()


def _check_for_user_message(queue, message_event=None):
    if queue:
        try:
            return queue.popleft()
        except IndexError:
            pass
    if message_event and not queue:
        message_event.clear()
    return None


def _feedback_target(stop_event, motion_controller, user_message):
    if not user_message:
        return None
    intent = INTENT_MATCHER.parse(user_message, motion_controller.current_target())
    if intent.kind == "stop":
        stop_event.set()
        return None
    if intent.kind == "move":
        return intent.target
    return None


def _sleep_with_stop(stop_event, seconds, wake_event=None):
    seconds = max(0.0, float(seconds or 0.0))
    if seconds <= 0:
        time.sleep(0)
        return
    deadline = time.monotonic() + seconds
    while not stop_event.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        wait_time = min(0.1, remaining)
        if stop_event.wait(wait_time):
            return
        if wake_event and wake_event.is_set():
            return


def _coerce_mode_decision(raw, *, mode, event):
    if not isinstance(raw, dict):
        return ModeDecision()
    if not any(key in raw for key in ("action", "duration_seconds", "duration", "seconds", "intensity")):
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

    chat = str(raw.get("chat") or raw.get("message") or "").strip()
    if chat.lower().startswith("llm connection error"):
        chat = ""
    if len(chat) > 240:
        chat = chat[:237].rstrip() + "..."

    return ModeDecision(action=action, duration_seconds=duration, intensity=intensity, chat=chat, source="llm")


def _request_mode_decision(callbacks, mode, event, *, edge_count=0, current_target=None):
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
    return _coerce_mode_decision(raw, mode=mode, event=event)


def _start_mode_decision_request(callbacks, mode, event, *, edge_count=0, current_target=None):
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


def _set_active_mode(callbacks, mode_name):
    setter = callbacks.get("set_mode_name")
    if setter:
        setter(mode_name)
    try:
        threading.current_thread().name = mode_name
    except Exception:
        pass


def _send_mode_decision_message(send_message, decision):
    if decision.chat and decision.source == "llm":
        send_message(decision.chat)


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


_slug_pattern_id = _slugify_motion_pattern_id


def _candidate_value(candidate, key, default=None):
    if isinstance(candidate, dict):
        return candidate.get(key, default)
    return getattr(candidate, key, default)


def _candidate_record(candidate):
    return _candidate_value(candidate, "record", candidate)


def _candidate_id(candidate, record):
    return _slug_pattern_id(
        _candidate_value(candidate, "id")
        or _candidate_value(candidate, "pattern_id")
        or getattr(record, "pattern_id", "")
        or getattr(record, "name", "")
    )


def _candidate_name(candidate, record, pattern_id):
    return str(
        _candidate_value(candidate, "name")
        or getattr(record, "name", "")
        or pattern_id
    ).strip()


def _candidate_weight(candidate, record):
    weight = _candidate_value(candidate, "weight", None)
    feedback = _candidate_value(candidate, "feedback", None) or getattr(record, "feedback", None) or {}
    if weight is None and isinstance(feedback, dict):
        weight = 50 + int(feedback.get("thumbs_up") or 0) * 12
        weight += int(feedback.get("neutral") or 0) * 2
        weight -= int(feedback.get("thumbs_down") or 0) * 18
    try:
        return max(0.0, min(100.0, float(weight if weight is not None else 50)))
    except (TypeError, ValueError):
        return 50.0


def _candidate_enabled(candidate, record):
    if _candidate_value(candidate, "enabled", getattr(record, "enabled", True)) is False:
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


def _run_scripted_mode(stop_event, services, callbacks, mode, max_steps=None, *, allow_mode_decisions=False, initial_intensity=None):
    motion_controller = services["motion"]
    get_timings = callbacks["get_timings"]
    message_queue = callbacks["message_queue"]
    message_event = callbacks.get("message_event")
    user_signal_event = callbacks.get("user_signal_event")
    send_message = callbacks["send_message"]
    update_mood = callbacks.get("update_mood", lambda mood: None)
    remember_pattern = callbacks.get("remember_pattern", lambda target: None)
    planner = MotionScriptPlanner(mode)
    step_count = 0
    mode_intensity = initial_intensity

    if allow_mode_decisions:
        min_time, max_time = get_timings(mode)
        decision = _request_mode_decision(
            callbacks,
            mode,
            "start",
            current_target=motion_controller.current_target(),
        )
        _send_mode_decision_message(send_message, decision)
        if decision.intensity is not None:
            mode_intensity = decision.intensity
        if max_steps is not None:
            max_steps = _step_limit_for_duration(decision, min_time, max_time, max_steps)
        if decision.action == "stop":
            stop_event.set()
            return

    while not stop_event.is_set() and (max_steps is None or step_count < max_steps):
        min_time, max_time = get_timings(mode)
        if mode == "milking" and user_signal_event and user_signal_event.is_set():
            user_signal_event.clear()
            decision = _request_mode_decision(
                callbacks,
                mode,
                "close_signal",
                current_target=motion_controller.current_target(),
            )
            _send_mode_decision_message(send_message, decision)
            if decision.action == "stop":
                stop_event.set()
                break
            if decision.intensity is not None:
                mode_intensity = decision.intensity
            if max_steps is not None:
                default_extension = random.randint(10, 16)
                max_steps += _step_limit_for_duration(decision, min_time, max_time, default_extension)
            if not decision.chat:
                send_message("Staying with it a little longer.")
        user_message = _check_for_user_message(message_queue, message_event)
        feedback_target = _feedback_target(stop_event, motion_controller, user_message)
        if stop_event.is_set():
            break

        step = planner.next_step(motion_controller.current_target(), feedback_target=feedback_target)
        if step.message:
            send_message(step.message)
        update_mood(step.mood)
        target = _target_with_intensity(step.target, mode_intensity)
        motion_controller.apply_target(target, source=f"{mode} mode")
        remember_pattern(target)
        step_count += 1
        _sleep_with_stop(stop_event, random.uniform(min_time, max_time) * step.delay_factor, message_event)


def auto_mode_logic(stop_event, services, callbacks):
    _run_scripted_mode(stop_event, services, callbacks, "auto")


def freestyle_mode_logic(stop_event, services, callbacks):
    motion_controller = services["motion"]
    get_timings = callbacks["get_timings"]
    message_queue = callbacks["message_queue"]
    message_event = callbacks.get("message_event")
    user_signal_event = callbacks.get("user_signal_event")
    send_message = callbacks["send_message"]
    update_mood = callbacks.get("update_mood", lambda mood: None)
    remember_pattern_id = callbacks.get("remember_pattern_id", lambda pattern_id: None)
    freestyle_candidates = callbacks.get("freestyle_candidates", lambda: ())
    rng = random.Random()
    recent_ids = []
    step_count = 0
    next_message_at = 0
    close_count = 0
    close_style_target = None
    close_style_until = 0.0

    while not stop_event.is_set():
        min_time, max_time = get_timings("freestyle")
        if user_signal_event and user_signal_event.is_set():
            user_signal_event.clear()
            close_count += 1
            decision_thread, decision_result = _start_mode_decision_request(
                callbacks,
                "freestyle",
                "close_signal",
                edge_count=close_count,
                current_target=motion_controller.current_target(),
            )
            decision_thread.join(timeout=FREESTYLE_DECISION_GRACE_SECONDS)
            candidates = tuple(freestyle_candidates())
            edge_buffer_played = False
            edge_buffer_steps = []
            edge_buffer_resume_choices = []
            decision = None
            while not stop_event.is_set():
                decision = _poll_mode_decision_request(decision_thread, decision_result)
                if decision is not None:
                    break
                completed, edge_steps, resume_choices = _apply_freestyle_edge_reaction(
                    motion_controller,
                    close_count,
                    rng=rng,
                    resume_candidates=candidates,
                    recent_ids=tuple(recent_ids),
                )
                if not completed:
                    break
                edge_buffer_played = True
                edge_buffer_steps = edge_steps
                edge_buffer_resume_choices = resume_choices
                step_count += _record_freestyle_edge_playback(
                    edge_steps,
                    resume_choices,
                    remember_pattern_id,
                    recent_ids,
                    update_mood,
                )
            if decision is None:
                decision = _poll_mode_decision_request(decision_thread, decision_result) or ModeDecision()
            decision = _freestyle_decision_with_permissions(decision, callbacks)
            _send_mode_decision_message(send_message, decision)
            if decision.action == "stop":
                stop_event.set()
                break
            if decision.action == "switch_to_milk":
                close_style_target = _freestyle_milk_style_target(decision)
                close_style_until = time.monotonic() + _freestyle_close_style_duration(decision, min_time, max_time)
            else:
                close_style_target = None
                close_style_until = 0.0
                if edge_buffer_played:
                    for step in edge_buffer_steps:
                        if step.message:
                            send_message(step.message)
                    continue
                completed, edge_steps, resume_choices = _apply_freestyle_edge_reaction(
                    motion_controller,
                    close_count,
                    intensity=decision.intensity,
                    rng=rng,
                    resume_candidates=candidates,
                    recent_ids=tuple(recent_ids),
                )
                for step in edge_steps:
                    if step.message:
                        send_message(step.message)
                if completed and edge_steps:
                    step_count += _record_freestyle_edge_playback(
                        edge_steps,
                        resume_choices,
                        remember_pattern_id,
                        recent_ids,
                        update_mood,
                    )
                continue

        user_message = _check_for_user_message(message_queue, message_event)
        feedback_target = _feedback_target(stop_event, motion_controller, user_message)
        if stop_event.is_set():
            break
        if not feedback_target and close_style_target and time.monotonic() < close_style_until:
            feedback_target = close_style_target
        elif close_style_target and time.monotonic() >= close_style_until:
            close_style_target = None

        choices = _freestyle_choice_chain(
            tuple(freestyle_candidates()),
            motion_controller.current_target(),
            feedback_target,
            tuple(recent_ids),
            rng,
        )
        if not choices:
            send_message("Freestyle needs at least one enabled motion pattern.")
            stop_event.set()
            break

        choice = choices[0]
        if feedback_target or step_count >= next_message_at:
            send_message(choice.reason)
            next_message_at = step_count + rng.randint(3, 5)

        if _apply_freestyle_choices(motion_controller, choices, rng):
            update_mood(choices[-1].mood)
            for played_choice in choices:
                remember_pattern_id(played_choice.pattern_id)
                recent_ids.append(played_choice.pattern_id)
            recent_ids[:] = recent_ids[-8:]

        step_count += len(choices)
        _sleep_with_stop(stop_event, 0, message_event)


def milking_mode_logic(stop_event, services, callbacks):
    _run_scripted_mode(
        stop_event,
        services,
        callbacks,
        "milking",
        max_steps=None,
        allow_mode_decisions=True,
    )


def edging_mode_logic(stop_event, services, callbacks):
    motion_controller = services["motion"]
    get_timings = callbacks["get_timings"]
    update_mood = callbacks["update_mood"]
    send_message = callbacks["send_message"]
    remember_pattern = callbacks.get("remember_pattern", lambda target: None)
    user_signal_event = callbacks["user_signal_event"]
    message_queue = callbacks["message_queue"]
    message_event = callbacks.get("message_event")
    planner = MotionScriptPlanner("edging")
    edge_count = 0
    step_count = 0
    max_steps = random.randint(56, 78)
    mode_intensity = None
    reaction_steps_remaining = None

    edging_min, edging_max = get_timings("edging")
    start_decision = _request_mode_decision(
        callbacks,
        "edging",
        "start",
        edge_count=edge_count,
        current_target=motion_controller.current_target(),
    )
    _send_mode_decision_message(send_message, start_decision)
    if start_decision.intensity is not None:
        mode_intensity = start_decision.intensity
    max_steps = max(
        EDGE_START_MIN_STEPS,
        _step_limit_for_duration(start_decision, edging_min, edging_max, max_steps),
    )
    if start_decision.action == "stop":
        stop_event.set()
        return
    if start_decision.action == "switch_to_milk":
        _set_active_mode(callbacks, "milking")
        _run_scripted_mode(
            stop_event,
            services,
            callbacks,
            "milking",
            max_steps=None,
            initial_intensity=mode_intensity,
        )
        return

    while not stop_event.is_set():
        edging_min, edging_max = get_timings("edging")
        step = None

        if step_count >= max_steps:
            decision = _request_mode_decision(
                callbacks,
                "edging",
                "progress",
                edge_count=edge_count,
                current_target=motion_controller.current_target(),
            )
            _send_mode_decision_message(send_message, decision)
            if decision.intensity is not None:
                mode_intensity = decision.intensity
            if decision.action == "stop":
                stop_event.set()
                break
            if decision.action == "switch_to_milk":
                _set_active_mode(callbacks, "milking")
                _run_scripted_mode(
                    stop_event,
                    services,
                    callbacks,
                    "milking",
                    max_steps=None,
                    initial_intensity=mode_intensity,
                )
                return
            extension_default = random.randint(10, 16)
            max_steps = step_count + max(
                EDGE_PROGRESS_MIN_STEPS,
                _step_limit_for_duration(decision, edging_min, edging_max, extension_default),
            )
            if decision.action in {"hold_then_resume", "pull_back"}:
                step = planner.next_step(
                    motion_controller.current_target(),
                    edge_count=max(1, edge_count),
                )
                if decision.duration_seconds is not None:
                    reaction_steps_remaining = max(
                        0,
                        _step_limit_for_duration(decision, edging_min, edging_max, len(planner.steps) + 1) - 1,
                    )
            else:
                continue

        if step is None:
            user_message = _check_for_user_message(message_queue, message_event)
            feedback_target = _feedback_target(stop_event, motion_controller, user_message)
            if stop_event.is_set():
                break

            if user_signal_event.is_set():
                user_signal_event.clear()
                edge_count += 1
                decision = _request_mode_decision(
                    callbacks,
                    "edging",
                    "close_signal",
                    edge_count=edge_count,
                    current_target=motion_controller.current_target(),
                )
                _send_mode_decision_message(send_message, decision)
                if decision.intensity is not None:
                    mode_intensity = decision.intensity
                if decision.action == "stop":
                    stop_event.set()
                    break
                if decision.action == "switch_to_milk":
                    _set_active_mode(callbacks, "milking")
                    _run_scripted_mode(
                        stop_event,
                        services,
                        callbacks,
                        "milking",
                        max_steps=None,
                        initial_intensity=mode_intensity,
                    )
                    return
                step = planner.next_step(motion_controller.current_target(), edge_count=edge_count)
                if decision.duration_seconds is not None:
                    reaction_steps_remaining = max(
                        0,
                        _step_limit_for_duration(decision, edging_min, edging_max, len(planner.steps) + 1) - 1,
                    )
            else:
                step = planner.next_step(motion_controller.current_target(), feedback_target=feedback_target)

        if step.message:
            send_message(step.message)
        update_mood(step.mood)
        target = _target_with_intensity(step.target, mode_intensity)
        motion_controller.apply_target(target, source="edging mode")
        remember_pattern(target)
        step_count += 1
        _sleep_with_stop(stop_event, random.uniform(edging_min, edging_max) * step.delay_factor, message_event)
        if reaction_steps_remaining is not None:
            reaction_steps_remaining -= 1
            if reaction_steps_remaining < 0:
                planner.steps.clear()
                reaction_steps_remaining = None
