import json
import re
from pathlib import Path
import threading

DEFAULT_OLLAMA_MODEL = "nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b"
LEGACY_OLLAMA_MODEL = "huihui_ai/gemma-4-abliterated:e2b"
DEFAULT_OLLAMA_MODELS = [
    DEFAULT_OLLAMA_MODEL,
    "nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e2b",
    LEGACY_OLLAMA_MODEL,
]


def normalize_ollama_model(model):
    cleaned = " ".join(str(model or "").split())
    cleaned = re.sub(r"\s*/\s*", "/", cleaned)
    cleaned = re.sub(r"\s*:\s*", ":", cleaned)
    return cleaned

class SettingsManager:
    def __init__(self, settings_file_path):
        self.file_path = Path(settings_file_path)
        self._save_lock = threading.Lock()

        # Default values
        self.handy_key = ""
        self.ai_name = "BOT" # New field
        self.ollama_model = DEFAULT_OLLAMA_MODEL
        self.ollama_models = list(DEFAULT_OLLAMA_MODELS)
        self.persona_desc = "An energetic and passionate girlfriend"
        self.profile_picture_b64 = ""
        self.patterns = []
        self.milking_patterns = []
        self.rules = []
        self.user_profile = self._get_default_profile()
        self.session_liked_patterns = []
        self.audio_provider = "elevenlabs"
        self.audio_enabled = False
        self.elevenlabs_api_key = ""
        self.elevenlabs_voice_id = ""
        self.local_tts_style = "expressive"
        self.local_tts_prompt_path = ""
        self.local_tts_exaggeration = 0.65
        self.local_tts_cfg_weight = 0.35
        self.local_tts_temperature = 0.85
        self.local_tts_top_p = 1.0
        self.local_tts_min_p = 0.05
        self.local_tts_repetition_penalty = 1.2
        self.min_depth = 5
        self.max_depth = 100
        self.min_speed = 10
        self.max_speed = 80
        self.auto_min_time = 4.0
        self.auto_max_time = 7.0
        self.milking_min_time = 2.5
        self.milking_max_time = 4.5
        self.edging_min_time = 5.0
        self.edging_max_time = 8.0

    def _get_default_profile(self):
        return {"name": "Unknown", "likes": [], "dislikes": [], "key_memories": []}

    def load(self):
        if not self.file_path.exists():
            print("[INFO] No settings file found, creating one with default values.")
            self.save()
            return

        try:
            data = json.loads(self.file_path.read_text())
            self.handy_key = data.get("handy_key", "")
            self.ai_name = data.get("ai_name", "BOT") # Load name
            loaded_model = normalize_ollama_model(data.get("ollama_model", DEFAULT_OLLAMA_MODEL))
            if loaded_model == LEGACY_OLLAMA_MODEL:
                loaded_model = DEFAULT_OLLAMA_MODEL
            self.ollama_model = loaded_model or DEFAULT_OLLAMA_MODEL
            self.ollama_models = self._normalize_model_list(
                data.get("ollama_models", []),
                include_current=True,
            )
            self.persona_desc = data.get("persona_desc", "An energetic and passionate girlfriend")
            self.profile_picture_b64 = data.get("profile_picture_b64", "")
            self.patterns = data.get("patterns", [])
            self.milking_patterns = data.get("milking_patterns", [])
            self.rules = data.get("rules", [])
            self.user_profile = data.get("user_profile", self._get_default_profile())
            self.audio_provider = data.get("audio_provider", "elevenlabs")
            self.audio_enabled = data.get("audio_enabled", False)
            self.elevenlabs_api_key = data.get("elevenlabs_api_key", "")
            self.elevenlabs_voice_id = data.get("elevenlabs_voice_id", "")
            self.local_tts_style = data.get("local_tts_style", "expressive")
            self.local_tts_prompt_path = data.get("local_tts_prompt_path", "")
            self.local_tts_exaggeration = data.get("local_tts_exaggeration", 0.65)
            self.local_tts_cfg_weight = data.get("local_tts_cfg_weight", 0.35)
            self.local_tts_temperature = data.get("local_tts_temperature", 0.85)
            self.local_tts_top_p = data.get("local_tts_top_p", 1.0)
            self.local_tts_min_p = data.get("local_tts_min_p", 0.05)
            self.local_tts_repetition_penalty = data.get("local_tts_repetition_penalty", 1.2)
            self.min_depth = data.get("min_depth", 5)
            self.max_depth = data.get("max_depth", 100)
            self.min_speed = data.get("min_speed", 10)
            self.max_speed = data.get("max_speed", 80)
            self.auto_min_time = data.get("auto_min_time", 4.0)
            self.auto_max_time = data.get("auto_max_time", 7.0)
            self.milking_min_time = data.get("milking_min_time", 2.5)
            self.milking_max_time = data.get("milking_max_time", 4.5)
            self.edging_min_time = data.get("edging_min_time", 5.0)
            self.edging_max_time = data.get("edging_max_time", 8.0)
            print("[OK] Loaded settings from my_settings.json")
        except Exception as e:
            print(f"[WARN] Couldn't read settings file, using defaults. Error: {e}")

    def save(self, llm_service=None, chat_history_to_save=None):
        with self._save_lock:
            if llm_service and chat_history_to_save:
                self.user_profile = llm_service.consolidate_user_profile(
                    list(chat_history_to_save), self.user_profile
                )
            
            if self.session_liked_patterns:
                print(f"[INFO] Saving {len(self.session_liked_patterns)} liked patterns...")
                for new_pattern in self.session_liked_patterns:
                    if not any(p["name"] == new_pattern["name"] for p in self.patterns):
                        self.patterns.append(new_pattern)
                self.session_liked_patterns.clear()

            settings_dict = {
                "handy_key": self.handy_key,
                "ai_name": self.ai_name, # Save name
                "ollama_model": self.ollama_model,
                "ollama_models": self._normalize_model_list(self.ollama_models, include_current=True),
                "persona_desc": self.persona_desc,
                "profile_picture_b64": self.profile_picture_b64,
                "audio_provider": self.audio_provider, "audio_enabled": self.audio_enabled,
                "elevenlabs_api_key": self.elevenlabs_api_key, "elevenlabs_voice_id": self.elevenlabs_voice_id,
                "local_tts_style": self.local_tts_style,
                "local_tts_prompt_path": self.local_tts_prompt_path,
                "local_tts_exaggeration": self.local_tts_exaggeration,
                "local_tts_cfg_weight": self.local_tts_cfg_weight,
                "local_tts_temperature": self.local_tts_temperature,
                "local_tts_top_p": self.local_tts_top_p,
                "local_tts_min_p": self.local_tts_min_p,
                "local_tts_repetition_penalty": self.local_tts_repetition_penalty,
                "patterns": self.patterns, "milking_patterns": self.milking_patterns,
                "rules": self.rules, "user_profile": self.user_profile,
                "min_depth": self.min_depth, "max_depth": self.max_depth,
                "min_speed": self.min_speed, "max_speed": self.max_speed,
                "auto_min_time": self.auto_min_time, "auto_max_time": self.auto_max_time,
                "milking_min_time": self.milking_min_time, "milking_max_time": self.milking_max_time,
                "edging_min_time": self.edging_min_time, "edging_max_time": self.edging_max_time,
            }
            self.file_path.write_text(json.dumps(settings_dict, indent=2))

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

    def set_ollama_model(self, model):
        normalized = normalize_ollama_model(model)
        if not normalized:
            return False
        self.ollama_model = normalized
        self.ollama_models = self._normalize_model_list(self.ollama_models, include_current=True)
        return True
