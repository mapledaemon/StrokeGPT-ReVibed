import copy
import json
import re
import threading
from pathlib import Path


DEFAULT_OLLAMA_MODEL = "nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b"
LEGACY_OLLAMA_MODEL = "huihui_ai/gemma-4-abliterated:e2b"
DEFAULT_OLLAMA_MODELS = [
    DEFAULT_OLLAMA_MODEL,
    "nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e2b",
    LEGACY_OLLAMA_MODEL,
]
DEFAULT_PERSONA_PROMPT = "An energetic and passionate girlfriend"
DEFAULT_PERSONA_PROMPTS = [
    DEFAULT_PERSONA_PROMPT,
    "An energetic and passionate boyfriend",
    "An energetic and passionate partner",
]
DEFAULT_MOTION_BACKEND = "hamp"
MOTION_BACKENDS = {"hamp", "position"}
DEFAULT_DIAGNOSTICS_LEVEL = "compact"
DIAGNOSTICS_LEVELS = {"compact", "status", "debug"}


def normalize_ollama_model(model):
    cleaned = " ".join(str(model or "").split())
    cleaned = re.sub(r"\s*/\s*", "/", cleaned)
    cleaned = re.sub(r"\s*:\s*", ":", cleaned)
    return cleaned


def default_user_profile():
    return {"name": "Unknown", "likes": [], "dislikes": [], "key_memories": []}


def default_settings_dict():
    return {
        "handy_key": "",
        "ai_name": "BOT",
        "ollama_model": DEFAULT_OLLAMA_MODEL,
        "ollama_models": list(DEFAULT_OLLAMA_MODELS),
        "persona_desc": DEFAULT_PERSONA_PROMPT,
        "persona_prompts": list(DEFAULT_PERSONA_PROMPTS),
        "profile_picture_b64": "",
        "audio_provider": "elevenlabs",
        "audio_enabled": False,
        "elevenlabs_api_key": "",
        "elevenlabs_voice_id": "",
        "local_tts_engine": "chatterbox_turbo",
        "local_tts_style": "expressive",
        "local_tts_prompt_path": "",
        "local_tts_exaggeration": 0.65,
        "local_tts_cfg_weight": 0.35,
        "local_tts_temperature": 0.85,
        "local_tts_top_p": 1.0,
        "local_tts_min_p": 0.05,
        "local_tts_repetition_penalty": 1.2,
        "patterns": [],
        "milking_patterns": [],
        "motion_pattern_enabled": {},
        "motion_pattern_feedback": {},
        "motion_pattern_feedback_history": [],
        "motion_pattern_weights": {},
        "motion_backend": DEFAULT_MOTION_BACKEND,
        "motion_diagnostics_level": DEFAULT_DIAGNOSTICS_LEVEL,
        "ollama_diagnostics_level": DEFAULT_DIAGNOSTICS_LEVEL,
        "motion_feedback_auto_disable": False,
        "rules": [],
        "user_profile": default_user_profile(),
        "min_depth": 5,
        "max_depth": 100,
        "min_speed": 10,
        "max_speed": 80,
        "auto_min_time": 4.0,
        "auto_max_time": 7.0,
        "milking_min_time": 2.5,
        "milking_max_time": 4.5,
        "edging_min_time": 5.0,
        "edging_max_time": 8.0,
    }


def _clamp_int(value, low, high, default):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _clamp_float(value, low, high, default):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _as_list(value):
    return value if isinstance(value, list) else []


class SettingsManager:
    def __init__(self, settings_file_path):
        self.file_path = Path(settings_file_path)
        self._save_lock = threading.Lock()
        self.reset_to_defaults(save=False)

    def reset_to_defaults(self, save=True):
        for key, value in default_settings_dict().items():
            setattr(self, key, copy.deepcopy(value))
        self.session_liked_patterns = []
        if save:
            self.save()

    def load(self):
        if not self.file_path.exists():
            print("[INFO] No settings file found, creating one with default values.")
            self.reset_to_defaults(save=True)
            return

        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            self.apply_dict(data)
            print("[OK] Loaded settings from my_settings.json")
        except Exception as e:
            print(f"[WARN] Couldn't read settings file, using defaults. Error: {e}")
            self.reset_to_defaults(save=False)

    def apply_dict(self, data):
        defaults = default_settings_dict()
        data = data if isinstance(data, dict) else {}

        self.handy_key = str(data.get("handy_key", defaults["handy_key"]) or "")
        self.ai_name = str(data.get("ai_name", defaults["ai_name"]) or defaults["ai_name"])

        loaded_model = normalize_ollama_model(data.get("ollama_model", DEFAULT_OLLAMA_MODEL))
        if loaded_model == LEGACY_OLLAMA_MODEL:
            loaded_model = DEFAULT_OLLAMA_MODEL
        self.ollama_model = loaded_model or DEFAULT_OLLAMA_MODEL
        self.ollama_models = self._normalize_model_list(data.get("ollama_models", []), include_current=True)

        self.persona_desc = (
            self._normalize_persona_prompt(data.get("persona_desc", DEFAULT_PERSONA_PROMPT))
            or DEFAULT_PERSONA_PROMPT
        )
        self.persona_prompts = self._normalize_persona_prompt_list(
            data.get("persona_prompts", []),
            include_current=True,
        )

        self.profile_picture_b64 = str(data.get("profile_picture_b64", "") or "")
        self.patterns = _as_list(data.get("patterns", []))
        self.milking_patterns = _as_list(data.get("milking_patterns", []))
        self.motion_pattern_enabled = self._normalize_bool_map(data.get("motion_pattern_enabled", {}))
        self.motion_pattern_feedback = self._normalize_feedback_map(data.get("motion_pattern_feedback", {}))
        self.motion_pattern_feedback_history = self._normalize_feedback_history(
            data.get("motion_pattern_feedback_history", [])
        )
        self.motion_pattern_weights = self._normalize_weight_map(data.get("motion_pattern_weights", {}))
        self.motion_backend = self._normalize_motion_backend(data.get("motion_backend", defaults["motion_backend"]))
        self.motion_diagnostics_level = self._normalize_diagnostics_level(
            data.get("motion_diagnostics_level", defaults["motion_diagnostics_level"])
        )
        self.ollama_diagnostics_level = self._normalize_diagnostics_level(
            data.get("ollama_diagnostics_level", defaults["ollama_diagnostics_level"])
        )
        self.motion_feedback_auto_disable = bool(
            data.get("motion_feedback_auto_disable", defaults["motion_feedback_auto_disable"])
        )
        self.rules = _as_list(data.get("rules", []))
        self.user_profile = data.get("user_profile", default_user_profile())
        if not isinstance(self.user_profile, dict):
            self.user_profile = default_user_profile()
        self.session_liked_patterns = []

        self.audio_provider = data.get("audio_provider", defaults["audio_provider"])
        if self.audio_provider not in {"elevenlabs", "local"}:
            self.audio_provider = defaults["audio_provider"]
        self.audio_enabled = bool(data.get("audio_enabled", defaults["audio_enabled"]))
        self.elevenlabs_api_key = str(data.get("elevenlabs_api_key", "") or "")
        self.elevenlabs_voice_id = str(data.get("elevenlabs_voice_id", "") or "")

        self.local_tts_engine = str(data.get("local_tts_engine", defaults["local_tts_engine"]) or defaults["local_tts_engine"])
        if self.local_tts_engine not in {"chatterbox", "chatterbox_turbo"}:
            self.local_tts_engine = defaults["local_tts_engine"]
        self.local_tts_style = str(data.get("local_tts_style", defaults["local_tts_style"]) or defaults["local_tts_style"])
        self.local_tts_prompt_path = str(data.get("local_tts_prompt_path", "") or "")
        self.local_tts_exaggeration = _clamp_float(data.get("local_tts_exaggeration"), 0.25, 2.0, defaults["local_tts_exaggeration"])
        self.local_tts_cfg_weight = _clamp_float(data.get("local_tts_cfg_weight"), 0.0, 1.0, defaults["local_tts_cfg_weight"])
        self.local_tts_temperature = _clamp_float(data.get("local_tts_temperature"), 0.05, 5.0, defaults["local_tts_temperature"])
        self.local_tts_top_p = _clamp_float(data.get("local_tts_top_p"), 0.05, 1.0, defaults["local_tts_top_p"])
        self.local_tts_min_p = _clamp_float(data.get("local_tts_min_p"), 0.0, 1.0, defaults["local_tts_min_p"])
        self.local_tts_repetition_penalty = _clamp_float(
            data.get("local_tts_repetition_penalty"),
            1.0,
            2.0,
            defaults["local_tts_repetition_penalty"],
        )

        depth_low = _clamp_int(data.get("min_depth"), 0, 100, defaults["min_depth"])
        depth_high = _clamp_int(data.get("max_depth"), 0, 100, defaults["max_depth"])
        self.min_depth, self.max_depth = min(depth_low, depth_high), max(depth_low, depth_high)

        speed_low = _clamp_int(data.get("min_speed"), 0, 100, defaults["min_speed"])
        speed_high = _clamp_int(data.get("max_speed"), 0, 100, defaults["max_speed"])
        self.min_speed, self.max_speed = min(speed_low, speed_high), max(speed_low, speed_high)

        self.auto_min_time, self.auto_max_time = self._timing_pair(
            data.get("auto_min_time"),
            data.get("auto_max_time"),
            defaults["auto_min_time"],
            defaults["auto_max_time"],
        )
        self.milking_min_time, self.milking_max_time = self._timing_pair(
            data.get("milking_min_time"),
            data.get("milking_max_time"),
            defaults["milking_min_time"],
            defaults["milking_max_time"],
        )
        self.edging_min_time, self.edging_max_time = self._timing_pair(
            data.get("edging_min_time"),
            data.get("edging_max_time"),
            defaults["edging_min_time"],
            defaults["edging_max_time"],
        )

    def to_dict(self):
        return {
            "handy_key": self.handy_key,
            "ai_name": self.ai_name,
            "ollama_model": self.ollama_model,
            "ollama_models": self._normalize_model_list(self.ollama_models, include_current=True),
            "persona_desc": self.persona_desc,
            "persona_prompts": self.persona_prompt_options(),
            "profile_picture_b64": self.profile_picture_b64,
            "audio_provider": self.audio_provider,
            "audio_enabled": self.audio_enabled,
            "elevenlabs_api_key": self.elevenlabs_api_key,
            "elevenlabs_voice_id": self.elevenlabs_voice_id,
            "local_tts_engine": self.local_tts_engine,
            "local_tts_style": self.local_tts_style,
            "local_tts_prompt_path": self.local_tts_prompt_path,
            "local_tts_exaggeration": self.local_tts_exaggeration,
            "local_tts_cfg_weight": self.local_tts_cfg_weight,
            "local_tts_temperature": self.local_tts_temperature,
            "local_tts_top_p": self.local_tts_top_p,
            "local_tts_min_p": self.local_tts_min_p,
            "local_tts_repetition_penalty": self.local_tts_repetition_penalty,
            "patterns": self.patterns,
            "milking_patterns": self.milking_patterns,
            "motion_pattern_enabled": self._normalize_bool_map(self.motion_pattern_enabled),
            "motion_pattern_feedback": self._normalize_feedback_map(self.motion_pattern_feedback),
            "motion_pattern_feedback_history": self._normalize_feedback_history(
                self.motion_pattern_feedback_history
            ),
            "motion_pattern_weights": self._normalize_weight_map(self.motion_pattern_weights),
            "motion_backend": self._normalize_motion_backend(self.motion_backend),
            "motion_diagnostics_level": self._normalize_diagnostics_level(self.motion_diagnostics_level),
            "ollama_diagnostics_level": self._normalize_diagnostics_level(self.ollama_diagnostics_level),
            "motion_feedback_auto_disable": bool(self.motion_feedback_auto_disable),
            "rules": self.rules,
            "user_profile": self.user_profile,
            "min_depth": self.min_depth,
            "max_depth": self.max_depth,
            "min_speed": self.min_speed,
            "max_speed": self.max_speed,
            "auto_min_time": self.auto_min_time,
            "auto_max_time": self.auto_max_time,
            "milking_min_time": self.milking_min_time,
            "milking_max_time": self.milking_max_time,
            "edging_min_time": self.edging_min_time,
            "edging_max_time": self.edging_max_time,
        }

    def save(self, llm_service=None, chat_history_to_save=None):
        with self._save_lock:
            if llm_service and chat_history_to_save:
                self.user_profile = llm_service.consolidate_user_profile(
                    list(chat_history_to_save),
                    self.user_profile,
                )

            if self.session_liked_patterns:
                print(f"[INFO] Saving {len(self.session_liked_patterns)} liked patterns...")
                for new_pattern in self.session_liked_patterns:
                    if not any(p["name"] == new_pattern["name"] for p in self.patterns):
                        self.patterns.append(new_pattern)
                self.session_liked_patterns.clear()

            self.file_path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    def _normalize_model_list(self, models, include_current=False):
        ordered = []
        for model in list(DEFAULT_OLLAMA_MODELS) + list(models or []):
            normalized = normalize_ollama_model(model)
            if normalized and normalized not in ordered:
                ordered.append(normalized)
        if include_current:
            current = normalize_ollama_model(self.ollama_model)
            if current and current not in ordered:
                ordered.insert(0, current)
        return ordered

    def _normalize_persona_prompt(self, prompt):
        return " ".join(str(prompt or "").split())

    def _normalize_persona_prompt_list(self, prompts, include_current=False):
        ordered = []
        if isinstance(prompts, str):
            prompts = [prompts]
        for prompt in list(DEFAULT_PERSONA_PROMPTS) + list(prompts or []):
            normalized = self._normalize_persona_prompt(prompt)
            if normalized and normalized not in ordered:
                ordered.append(normalized)
        if include_current:
            current = self._normalize_persona_prompt(self.persona_desc)
            if current and current not in ordered:
                ordered.insert(0, current)
        return ordered

    def _normalize_bool_map(self, values):
        if not isinstance(values, dict):
            return {}
        normalized = {}
        for key, value in values.items():
            cleaned = re.sub(r"[^a-z0-9_-]+", "-", str(key or "").strip().lower()).strip("-_")
            if cleaned:
                normalized[cleaned[:64]] = bool(value)
        return normalized

    def _normalize_feedback_map(self, values):
        if not isinstance(values, dict):
            return {}
        normalized = {}
        for key, feedback in values.items():
            cleaned = re.sub(r"[^a-z0-9_-]+", "-", str(key or "").strip().lower()).strip("-_")
            if not cleaned or not isinstance(feedback, dict):
                continue
            normalized[cleaned[:64]] = {
                "thumbs_up": _clamp_int(feedback.get("thumbs_up"), 0, 1_000_000, 0),
                "neutral": _clamp_int(feedback.get("neutral"), 0, 1_000_000, 0),
                "thumbs_down": _clamp_int(feedback.get("thumbs_down"), 0, 1_000_000, 0),
            }
        return normalized

    def _normalize_feedback_history(self, values):
        if not isinstance(values, list):
            return []
        normalized = []
        for entry in values:
            if not isinstance(entry, dict):
                continue
            pattern_id = re.sub(
                r"[^a-z0-9_-]+",
                "-",
                str(entry.get("pattern_id") or "").strip().lower(),
            ).strip("-_")
            rating = str(entry.get("rating") or "").strip().lower()
            if not pattern_id or rating not in {"thumbs_up", "neutral", "thumbs_down", "reset"}:
                continue
            item = {
                "pattern_id": pattern_id[:64],
                "pattern_name": " ".join(str(entry.get("pattern_name") or pattern_id).split())[:96],
                "rating": rating,
                "source": " ".join(str(entry.get("source") or "feedback").split())[:64],
                "at": " ".join(str(entry.get("at") or "").split())[:40],
            }
            if "weight" in entry:
                item["weight"] = _clamp_int(entry.get("weight"), 0, 100, 50)
            if "enabled" in entry:
                item["enabled"] = bool(entry.get("enabled"))
            normalized.append(item)
            if len(normalized) >= 20:
                break
        return normalized

    def _normalize_weight_map(self, values):
        if not isinstance(values, dict):
            return {}
        normalized = {}
        for key, value in values.items():
            cleaned = re.sub(r"[^a-z0-9_-]+", "-", str(key or "").strip().lower()).strip("-_")
            if cleaned:
                normalized[cleaned[:64]] = _clamp_int(value, 0, 100, 50)
        return normalized

    def _normalize_motion_backend(self, value):
        cleaned = str(value or "").strip().lower()
        if cleaned in {"hamp", "hamp_continuous", "continuous"}:
            return "hamp"
        if cleaned in {"position", "position_script", "position-script", "flexible_position", "flexible"}:
            return "position"
        return DEFAULT_MOTION_BACKEND

    def _normalize_diagnostics_level(self, value):
        cleaned = str(value or "").strip().lower()
        if cleaned in {"off", "minimal", "default", "normal"}:
            return "compact"
        if cleaned in {"basic", "info", "verbose"}:
            return "status"
        if cleaned in DIAGNOSTICS_LEVELS:
            return cleaned
        return DEFAULT_DIAGNOSTICS_LEVEL

    def _timing_pair(self, first, second, default_first, default_second):
        first = _clamp_float(first, 1.0, 60.0, default_first)
        second = _clamp_float(second, 1.0, 60.0, default_second)
        return min(first, second), max(first, second)

    def set_persona_prompt(self, prompt, save_prompt=True):
        normalized = self._normalize_persona_prompt(prompt)
        if not normalized:
            return False
        self.persona_desc = normalized
        if save_prompt:
            self.persona_prompts = self._normalize_persona_prompt_list(
                self.persona_prompts + [normalized],
                include_current=True,
            )
        return True

    def persona_prompt_options(self):
        return self._normalize_persona_prompt_list(self.persona_prompts, include_current=True)

    def set_ollama_model(self, model):
        normalized = normalize_ollama_model(model)
        if not normalized:
            return False
        self.ollama_model = normalized
        self.ollama_models = self._normalize_model_list(self.ollama_models, include_current=True)
        return True
