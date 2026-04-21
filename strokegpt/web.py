import os
import sys
import io
import re
import atexit
import threading
import time
from collections import deque
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string, send_file, send_from_directory
from werkzeug.utils import secure_filename

from .settings import SettingsManager, normalize_ollama_model
from .handy import HandyController
from .llm import LLMService
from .audio import AudioService
from .background_modes import AutoModeThread, auto_mode_logic, milking_mode_logic, edging_mode_logic
from .motion import IntentMatcher, MotionController, MotionTarget


PROJECT_ROOT = Path(__file__).resolve().parent.parent
VOICE_SAMPLE_DIR = PROJECT_ROOT / "voice_samples"
ALLOWED_VOICE_SAMPLE_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"}


def resource_path(*parts):
    base_path = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else PROJECT_ROOT
    return base_path.joinpath(*parts)

# ─── INITIALIZATION ───────────────────────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=None)
LLM_URL = "http://127.0.0.1:11434/api/chat"
settings = SettingsManager(settings_file_path="my_settings.json")
settings.load()

handy = HandyController(settings.handy_key)
handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
motion = MotionController(handy)
intent_matcher = IntentMatcher()

ollama_model = normalize_ollama_model(os.getenv("STROKEGPT_OLLAMA_MODEL", settings.ollama_model)) or settings.ollama_model
llm = LLMService(url=LLM_URL, model=ollama_model)
audio = AudioService()
audio.set_provider(settings.audio_provider, settings.audio_enabled)
if settings.elevenlabs_api_key:
    if audio.set_api_key(settings.elevenlabs_api_key):
        audio.fetch_available_voices()
        if settings.audio_provider == "elevenlabs":
            audio.configure_voice(settings.elevenlabs_voice_id, settings.audio_enabled)
if settings.audio_provider == "local":
    audio.configure_local_voice(
        settings.audio_enabled,
        settings.local_tts_prompt_path,
        settings.local_tts_exaggeration,
        settings.local_tts_cfg_weight,
        settings.local_tts_style,
        settings.local_tts_temperature,
        settings.local_tts_top_p,
        settings.local_tts_min_p,
        settings.local_tts_repetition_penalty,
    )

# In-Memory State
chat_history = deque(maxlen=20)
messages_for_ui = deque()
auto_mode_active_task = None
current_mood = "Curious"
use_long_term_memory = True
calibration_pos_mm = 0.0
user_signal_event = threading.Event()
mode_message_queue = deque(maxlen=5)
edging_start_time = None
depth_test_lock = threading.Lock()

# Easter Egg State
special_persona_mode = None
special_persona_interactions_left = 0

def get_ollama_models_for_ui():
    models = list(settings.ollama_models)
    if llm.model not in models:
        models.insert(0, llm.model)
    return models

def get_persona_prompts_for_ui():
    return settings.persona_prompt_options()

def settings_payload():
    return {
        "configured": bool(settings.handy_key and settings.min_depth < settings.max_depth),
        "persona": settings.persona_desc,
        "persona_prompts": get_persona_prompts_for_ui(),
        "handy_key": settings.handy_key,
        "ai_name": settings.ai_name,
        "elevenlabs_key": settings.elevenlabs_api_key,
        "ollama_model": llm.model,
        "ollama_models": get_ollama_models_for_ui(),
        "audio_provider": settings.audio_provider,
        "audio_enabled": settings.audio_enabled,
        "elevenlabs_voice_id": settings.elevenlabs_voice_id,
        "local_tts_status": audio.local_status(),
        "local_tts_style_presets": audio.CHATTERBOX_STYLE_PRESETS,
        "local_tts_style": settings.local_tts_style,
        "local_tts_prompt_path": settings.local_tts_prompt_path,
        "local_tts_exaggeration": settings.local_tts_exaggeration,
        "local_tts_cfg_weight": settings.local_tts_cfg_weight,
        "local_tts_temperature": settings.local_tts_temperature,
        "local_tts_top_p": settings.local_tts_top_p,
        "local_tts_min_p": settings.local_tts_min_p,
        "local_tts_repetition_penalty": settings.local_tts_repetition_penalty,
        "min_depth": settings.min_depth,
        "max_depth": settings.max_depth,
        "min_speed": settings.min_speed,
        "max_speed": settings.max_speed,
        "pfp": settings.profile_picture_b64,
        "timings": {
            "auto_min": settings.auto_min_time,
            "auto_max": settings.auto_max_time,
            "milking_min": settings.milking_min_time,
            "milking_max": settings.milking_max_time,
            "edging_min": settings.edging_min_time,
            "edging_max": settings.edging_max_time,
        },
    }

def apply_settings_to_services():
    handy.set_api_key(settings.handy_key)
    handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
    llm.set_model(settings.ollama_model)

    audio.set_provider(settings.audio_provider, settings.audio_enabled)
    audio.api_key = ""
    audio.voice_id = ""
    audio.client = None
    audio.available_voices = {}
    audio.audio_output_queue.clear()
    audio.last_error = ""
    if settings.elevenlabs_api_key:
        if audio.set_api_key(settings.elevenlabs_api_key):
            audio.fetch_available_voices()
            if settings.audio_provider == "elevenlabs":
                audio.configure_voice(settings.elevenlabs_voice_id, settings.audio_enabled)
    if settings.audio_provider == "local":
        audio.configure_local_voice(
            settings.audio_enabled,
            settings.local_tts_prompt_path,
            settings.local_tts_exaggeration,
            settings.local_tts_cfg_weight,
            settings.local_tts_style,
            settings.local_tts_temperature,
            settings.local_tts_top_p,
            settings.local_tts_min_p,
            settings.local_tts_repetition_penalty,
        )

def reset_runtime_state():
    global auto_mode_active_task, current_mood, calibration_pos_mm, edging_start_time
    global special_persona_mode, special_persona_interactions_left

    if auto_mode_active_task:
        auto_mode_active_task.stop()
        auto_mode_active_task.join(timeout=5)
        auto_mode_active_task = None

    motion.stop()
    settings.reset_to_defaults(save=True)
    apply_settings_to_services()
    chat_history.clear()
    messages_for_ui.clear()
    mode_message_queue.clear()
    user_signal_event.clear()
    current_mood = "Curious"
    calibration_pos_mm = 0.0
    edging_start_time = None
    special_persona_mode = None
    special_persona_interactions_left = 0

SNAKE_ASCII = """
⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠿⠟⠛⠛⠋⠉⠛⠟⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⡏⠉⠹⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⣿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⠀⢸⣧⡀⠀⠰⣦⡀⠀⠀⢀⠀⠀⠈⣻⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⡇⢨⣿⣿⣖⡀⢡⠉⠄⣀⢀⣀⡀⠀⠼⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⣿⠀⠀⠘⠋⢏⢀⣰⣖⣿⣿⣿⠟⡡⠀⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣯⠁⢀⠂⡆⠉⠘⠛⠿⣿⢿⠟⢁⣬⡶⢠⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⡯⠀⢀⡀⠝⠀⠀⠀⠀⢀⠠⣩⣤⣠⣆⣾⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⡅⠀⠊⠇⢈⣴⣦⣤⣆⠈⢀⠋⠹⣿⣇⣻⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⣿⣿⣿⣿⡄⠥⡇⠀⠀⠚⠺⠯⠀⠀⠒⠛⠒⢪⢿⣿⣿⣿⣿⣿⣿⣿⣿
⣿⣿⣿⡿⠿⠛⠋⠀⠘⣿⡄⠀⠀⠀⠋⠉⡉⠙⠂⢰⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿
⠀⠈⠉⠀⠀⠀⠀⠀⠀⠀⠙⠷⢐⠀⠀⠀⠀⢀⢴⣿⠊⠀⠉⠉⠉⠈⠙⠉⠛⠿
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠰⣖⣴⣾⡃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠁⠀⠀⠀⠀⠀⢀⠀⠀⠀⠀⠁⠀⠨
"""

# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────────────────────────────

def get_current_context():
    global edging_start_time, special_persona_mode
    context = {
        'persona_desc': settings.persona_desc, 'current_mood': current_mood,
        'user_profile': settings.user_profile, 'patterns': settings.patterns,
        'rules': settings.rules, 'last_stroke_speed': handy.last_relative_speed,
        'last_depth_pos': handy.last_depth_pos, 'last_stroke_range': handy.last_stroke_range,
        'use_long_term_memory': use_long_term_memory,
        'edging_elapsed_time': None, 'special_persona_mode': special_persona_mode
    }
    if edging_start_time:
        elapsed_seconds = int(time.time() - edging_start_time)
        minutes, seconds = divmod(elapsed_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            context['edging_elapsed_time'] = f"{hours}h {minutes}m {seconds}s"
        else:
            context['edging_elapsed_time'] = f"{minutes}m {seconds}s"
    return context

def add_message_to_queue(text, add_to_history=True):
    messages_for_ui.append(text)
    if add_to_history:
        clean_text = re.sub(r'<[^>]+>', '', text).strip()
        if clean_text: chat_history.append({"role": "assistant", "content": clean_text})
    threading.Thread(target=audio.generate_audio_for_text, args=(text,)).start()

def start_background_mode(mode_logic, initial_message, mode_name):
    global auto_mode_active_task, edging_start_time
    if auto_mode_active_task:
        auto_mode_active_task.stop()
        auto_mode_active_task.join(timeout=5)
    
    user_signal_event.clear()
    mode_message_queue.clear()
    if mode_name == 'edging':
        edging_start_time = time.time()
    
    def on_stop():
        global auto_mode_active_task, edging_start_time
        auto_mode_active_task = None
        edging_start_time = None

    def update_mood(m): global current_mood; current_mood = m
    def get_timings(n):
        return {
            'auto': (settings.auto_min_time, settings.auto_max_time),
            'milking': (settings.milking_min_time, settings.milking_max_time),
            'edging': (settings.edging_min_time, settings.edging_max_time)
        }.get(n, (3, 5))

    services = {'llm': llm, 'handy': handy, 'motion': motion}
    callbacks = {
        'send_message': add_message_to_queue, 'get_context': get_current_context,
        'get_timings': get_timings, 'on_stop': on_stop, 'update_mood': update_mood,
        'user_signal_event': user_signal_event,
        'message_queue': mode_message_queue
    }
    auto_mode_active_task = AutoModeThread(mode_logic, initial_message, services, callbacks, mode_name=mode_name)
    auto_mode_active_task.start()

# ─── FLASK ROUTES ──────────────────────────────────────────────────────────────────────────────────────
@app.route('/')
def home_page():
    with open(resource_path('index.html'), 'r', encoding='utf-8') as f:
        return render_template_string(f.read())

@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory(resource_path('static'), path)

def _konami_code_action():
    def pattern_thread():
        motion.apply_target(MotionTarget(speed=100, depth=50, stroke_range=100, label="konami"))
        time.sleep(5)
        motion.stop()
    threading.Thread(target=pattern_thread).start()
    message = f"Kept you waiting, huh?<pre>{SNAKE_ASCII}</pre>"
    add_message_to_queue(message)

def _handle_chat_commands(text):
    intent = intent_matcher.parse(text, motion.current_target())
    if intent.kind == "stop":
        if auto_mode_active_task: auto_mode_active_task.stop()
        motion.stop()
        add_message_to_queue("Stopping.", add_to_history=False)
        return True, jsonify({"status": "stopped"})
    if "up up down down left right left right b a" in text:
        _konami_code_action()
        return True, jsonify({"status": "konami_code_activated"})
    if intent.kind == "auto_on" and not auto_mode_active_task:
        start_background_mode(auto_mode_logic, "Okay, I'll take over...", mode_name='auto')
        return True, jsonify({"status": "auto_started"})
    if intent.kind == "auto_off" and auto_mode_active_task:
        auto_mode_active_task.stop()
        return True, jsonify({"status": "auto_stopped"})
    if intent.kind == "edging":
        start_background_mode(edging_mode_logic, "Let's play an edging game...", mode_name='edging')
        return True, jsonify({"status": "edging_started"})
    if intent.kind == "milking":
        start_background_mode(milking_mode_logic, "You're so close... I'm taking over completely now.", mode_name='milking')
        return True, jsonify({"status": "milking_started"})
    if intent.kind == "move" and intent.target:
        motion.apply_target(intent.target)
        add_message_to_queue("Adjusting.", add_to_history=False)
        return True, jsonify({"status": "move_applied", "matched": intent.matched})
    return False, None

@app.route('/send_message', methods=['POST'])
def handle_user_message():
    global special_persona_mode, special_persona_interactions_left
    data = request.json
    user_input = data.get('message', '').strip()

    if (p := data.get('persona_desc')) and p != settings.persona_desc:
        settings.set_persona_prompt(p); settings.save()
    if (k := data.get('key')) and k != settings.handy_key:
        handy.set_api_key(k); settings.handy_key = k; settings.save()
    
    if not handy.handy_key: return jsonify({"status": "no_key_set"})
    if not user_input: return jsonify({"status": "empty_message"})

    chat_history.append({"role": "user", "content": user_input})
    
    handled, response = _handle_chat_commands(user_input.lower())
    if handled: return response

    if auto_mode_active_task:
        mode_message_queue.append(user_input)
        return jsonify({"status": "message_relayed_to_active_mode"})
    
    llm_response = llm.get_chat_response(chat_history, get_current_context())
    
    if special_persona_mode is not None:
        special_persona_interactions_left -= 1
        if special_persona_interactions_left <= 0:
            special_persona_mode = None
            add_message_to_queue("(Personality core reverted to standard operation.)", add_to_history=False)

    if chat_text := llm_response.get("chat"): add_message_to_queue(chat_text)
    if new_mood := llm_response.get("new_mood"): global current_mood; current_mood = new_mood
    if not auto_mode_active_task and (move := llm_response.get("move")):
        motion.apply_llm_move(move)
    return jsonify({"status": "ok"})

@app.route('/check_settings')
def check_settings_route():
    return jsonify(settings_payload())

@app.route('/reset_settings', methods=['POST'])
def reset_settings_route():
    data = request.json or {}
    if data.get("confirm") != "RESET":
        return jsonify({"status": "error", "message": "Reset confirmation is required."}), 400
    reset_runtime_state()
    payload = settings_payload()
    payload["status"] = "success"
    return jsonify(payload)

@app.route('/set_persona_prompt', methods=['POST'])
def set_persona_prompt_route():
    data = request.json or {}
    prompt = data.get('persona_desc', '')
    save_prompt = data.get('save_prompt', True)
    if not settings.set_persona_prompt(prompt, save_prompt=save_prompt):
        return jsonify({"status": "error", "message": "Persona prompt is required."}), 400
    settings.save()
    return jsonify({
        "status": "success",
        "persona": settings.persona_desc,
        "persona_prompts": get_persona_prompts_for_ui(),
    })

@app.route('/set_ollama_model', methods=['POST'])
def set_ollama_model_route():
    data = request.json or {}
    model = normalize_ollama_model(data.get('model', ''))
    if not model:
        return jsonify({"status": "error", "message": "Model name is required."}), 400
    if not llm.set_model(model):
        return jsonify({"status": "error", "message": "Invalid model name."}), 400
    settings.set_ollama_model(model)
    settings.save()
    return jsonify({
        "status": "success",
        "ollama_model": llm.model,
        "ollama_models": get_ollama_models_for_ui(),
    })

@app.route('/set_ai_name', methods=['POST'])
def set_ai_name_route():
    global special_persona_mode, special_persona_interactions_left
    name = request.json.get('name', 'BOT').strip();
    if not name: name = 'BOT'
    
    if name.lower() == 'glados':
        special_persona_mode = "GLaDOS"
        special_persona_interactions_left = 5
        settings.ai_name = "GLaDOS"
        settings.save()
        return jsonify({"status": "special_persona_activated", "persona": "GLaDOS", "message": "Oh, it's *you*."})

    settings.ai_name = name; settings.save()
    return jsonify({"status": "success", "name": name})

@app.route('/signal_edge', methods=['POST'])
def signal_edge_route():
    if auto_mode_active_task and auto_mode_active_task.name == 'edging':
        user_signal_event.set()
        return jsonify({"status": "signaled"})
    return jsonify({"status": "ignored", "message": "Edging mode not active."}), 400

@app.route('/set_profile_picture', methods=['POST'])
def set_pfp_route():
    b64_data = request.json.get('pfp_b64')
    if not b64_data: return jsonify({"status": "error", "message": "Missing image data"}), 400
    settings.profile_picture_b64 = b64_data; settings.save()
    return jsonify({"status": "success"})

@app.route('/set_handy_key', methods=['POST'])
def set_handy_key_route():
    key = request.json.get('key')
    if not key: return jsonify({"status": "error", "message": "Key is missing"}), 400
    handy.set_api_key(key); settings.handy_key = key; settings.save()
    return jsonify({"status": "success"})

@app.route('/nudge', methods=['POST'])
def nudge_route():
    global calibration_pos_mm
    if calibration_pos_mm == 0.0 and (pos := handy.get_position_mm()):
        calibration_pos_mm = pos
    direction = request.json.get('direction')
    calibration_pos_mm = handy.nudge(direction, 0, 100, calibration_pos_mm)
    return jsonify({"status": "ok", "depth_percent": handy.mm_to_percent(calibration_pos_mm)})

@app.route('/test_depth_range', methods=['POST'])
def test_depth_range_route():
    data = request.json or {}
    depth1 = int(data.get('min_depth', 5))
    depth2 = int(data.get('max_depth', 100))
    min_depth = max(0, min(100, min(depth1, depth2)))
    max_depth = max(0, min(100, max(depth1, depth2)))
    if not depth_test_lock.acquire(blocking=False):
        return jsonify({"status": "busy", "min_depth": min_depth, "max_depth": max_depth})
    motion.stop()

    def run_depth_test():
        try:
            handy.test_depth_range(min_depth, max_depth)
        finally:
            depth_test_lock.release()

    threading.Thread(
        target=run_depth_test,
        daemon=True,
    ).start()
    return jsonify({"status": "testing", "min_depth": min_depth, "max_depth": max_depth})

@app.route('/setup_elevenlabs', methods=['POST'])
def elevenlabs_setup_route():
    api_key = request.json.get('api_key')
    if not api_key or not audio.set_api_key(api_key): return jsonify({"status": "error"}), 400
    settings.elevenlabs_api_key = api_key; settings.save()
    return jsonify(audio.fetch_available_voices())

@app.route('/set_elevenlabs_voice', methods=['POST'])
def set_elevenlabs_voice_route():
    voice_id, enabled = request.json.get('voice_id'), request.json.get('enabled', False)
    ok, message = audio.configure_voice(voice_id, enabled)
    if ok:
        settings.audio_provider = "elevenlabs"
        settings.audio_enabled = bool(enabled)
        settings.elevenlabs_voice_id = voice_id
        settings.save()
    return jsonify({"status": "ok" if ok else "error", "message": message})

@app.route('/set_audio_provider', methods=['POST'])
def set_audio_provider_route():
    data = request.json or {}
    provider = data.get('provider', 'elevenlabs')
    enabled = data.get('enabled', settings.audio_enabled)
    ok, message = audio.set_provider(provider, enabled)
    if ok:
        settings.audio_provider = provider
        settings.audio_enabled = bool(enabled)
        settings.save()
    return jsonify({"status": "ok" if ok else "error", "message": message, "local_tts_status": audio.local_status()})

@app.route('/local_tts_status')
def local_tts_status_route():
    return jsonify(audio.local_status())

@app.route('/set_local_tts_voice', methods=['POST'])
def set_local_tts_voice_route():
    data = request.json or {}
    enabled = data.get('enabled', False)
    prompt_path = data.get('prompt_path', '')
    style = data.get('style', settings.local_tts_style)
    exaggeration = data.get('exaggeration', 0.65)
    cfg_weight = data.get('cfg_weight', 0.35)
    temperature = data.get('temperature', settings.local_tts_temperature)
    top_p = data.get('top_p', settings.local_tts_top_p)
    min_p = data.get('min_p', settings.local_tts_min_p)
    repetition_penalty = data.get('repetition_penalty', settings.local_tts_repetition_penalty)
    ok, message = audio.configure_local_voice(
        enabled,
        prompt_path,
        exaggeration,
        cfg_weight,
        style,
        temperature,
        top_p,
        min_p,
        repetition_penalty,
    )
    if ok:
        persist_local_voice_settings()
    return jsonify({"status": "ok" if ok else "error", "message": message, "local_tts_status": audio.local_status()})

def persist_local_voice_settings():
    settings.audio_provider = "local"
    settings.audio_enabled = bool(audio.is_on)
    settings.local_tts_style = audio.local_style
    settings.local_tts_prompt_path = audio.local_prompt_path
    settings.local_tts_exaggeration = audio.local_exaggeration
    settings.local_tts_cfg_weight = audio.local_cfg_weight
    settings.local_tts_temperature = audio.local_temperature
    settings.local_tts_top_p = audio.local_top_p
    settings.local_tts_min_p = audio.local_min_p
    settings.local_tts_repetition_penalty = audio.local_repetition_penalty
    settings.save()

@app.route('/upload_local_tts_sample', methods=['POST'])
def upload_local_tts_sample_route():
    uploaded = request.files.get('sample')
    if not uploaded or not uploaded.filename:
        return jsonify({"status": "error", "message": "Choose an audio file first."}), 400

    original_name = secure_filename(uploaded.filename)
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_VOICE_SAMPLE_EXTENSIONS:
        return jsonify({
            "status": "error",
            "message": "Sample must be WAV, MP3, FLAC, M4A, OGG, or AAC.",
        }), 400

    VOICE_SAMPLE_DIR.mkdir(exist_ok=True)
    stem = Path(original_name).stem or "voice-sample"
    filename = f"{int(time.time())}-{stem}{extension}"
    target = (VOICE_SAMPLE_DIR / filename).resolve()
    sample_root = VOICE_SAMPLE_DIR.resolve()
    try:
        target.relative_to(sample_root)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid sample filename."}), 400

    uploaded.save(target)
    audio.configure_local_voice(
        audio.is_on,
        str(target),
        audio.local_exaggeration,
        audio.local_cfg_weight,
        audio.local_style,
        audio.local_temperature,
        audio.local_top_p,
        audio.local_min_p,
        audio.local_repetition_penalty,
    )
    persist_local_voice_settings()
    return jsonify({
        "status": "success",
        "prompt_path": str(target),
        "message": "Sample audio saved.",
        "local_tts_status": audio.local_status(),
    })

@app.route('/test_local_tts_voice', methods=['POST'])
def test_local_tts_voice_route():
    threading.Thread(
        target=audio.generate_audio_for_text,
        args=("Local voice test.",),
        kwargs={"force": True},
        daemon=True,
    ).start()
    return jsonify({"status": "queued", "message": "Local voice test queued."})

@app.route('/get_updates')
def get_ui_updates_route():
    messages = [messages_for_ui.popleft() for _ in range(len(messages_for_ui))]
    return jsonify({
        "messages": messages,
        "audio_ready": audio.has_audio(),
        "audio_error": audio.consume_last_error(),
    })

@app.route('/get_audio')
def get_audio_route():
    audio_chunk = audio.get_next_audio_chunk()
    if not audio_chunk:
        return ("", 204)
    return send_file(io.BytesIO(audio_chunk["bytes"]), mimetype=audio_chunk["mimetype"])

@app.route('/get_status')
def get_status_route():
    return jsonify({
        "mood": current_mood,
        "speed": handy.last_stroke_speed,
        "depth": handy.last_depth_pos,
        "range": handy.last_stroke_range,
    })

@app.route('/set_depth_limits', methods=['POST'])
def set_depth_limits_route():
    depth1 = int(request.json.get('min_depth', 5)); depth2 = int(request.json.get('max_depth', 100))
    settings.min_depth = min(depth1, depth2); settings.max_depth = max(depth1, depth2)
    handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
    settings.save()
    return jsonify({"status": "success"})

@app.route('/set_speed_limits', methods=['POST'])
def set_speed_limits_route():
    speed1 = int(request.json.get('min_speed', 10)); speed2 = int(request.json.get('max_speed', 80))
    settings.min_speed = max(0, min(100, min(speed1, speed2)))
    settings.max_speed = max(0, min(100, max(speed1, speed2)))
    handy.update_settings(settings.min_speed, settings.max_speed, settings.min_depth, settings.max_depth)
    settings.save()
    return jsonify({
        "status": "success",
        "min_speed": settings.min_speed,
        "max_speed": settings.max_speed,
    })

def _timing_pair(data, min_key, max_key, default_min, default_max):
    try:
        first = float(data.get(min_key, default_min))
        second = float(data.get(max_key, default_max))
    except (TypeError, ValueError):
        first, second = default_min, default_max
    first = max(1.0, min(60.0, first))
    second = max(1.0, min(60.0, second))
    return min(first, second), max(first, second)

@app.route('/set_mode_timings', methods=['POST'])
def set_mode_timings_route():
    data = request.json or {}
    settings.auto_min_time, settings.auto_max_time = _timing_pair(data, 'auto_min', 'auto_max', 4.0, 7.0)
    settings.edging_min_time, settings.edging_max_time = _timing_pair(data, 'edging_min', 'edging_max', 5.0, 8.0)
    settings.milking_min_time, settings.milking_max_time = _timing_pair(data, 'milking_min', 'milking_max', 2.5, 4.5)
    settings.save()
    return jsonify({
        "status": "success",
        "timings": {
            "auto_min": settings.auto_min_time,
            "auto_max": settings.auto_max_time,
            "edging_min": settings.edging_min_time,
            "edging_max": settings.edging_max_time,
            "milking_min": settings.milking_min_time,
            "milking_max": settings.milking_max_time,
        },
    })

@app.route('/like_last_move', methods=['POST'])
def like_last_move_route():
    last_speed = handy.last_relative_speed; last_depth = handy.last_depth_pos
    pattern_name = llm.name_this_move(last_speed, last_depth, current_mood)
    sp_range = [max(0, last_speed - 5), min(100, last_speed + 5)]; dp_range = [max(0, last_depth - 5), min(100, last_depth + 5)]
    new_pattern = {"name": pattern_name, "sp_range": [int(p) for p in sp_range], "dp_range": [int(p) for p in dp_range], "moods": [current_mood], "score": 1}
    settings.session_liked_patterns.append(new_pattern)
    add_message_to_queue(f"(I'll remember that you like '{pattern_name}')", add_to_history=False)
    return jsonify({"status": "boosted", "name": pattern_name})

@app.route('/start_edging_mode', methods=['POST'])
def start_edging_route():
    start_background_mode(edging_mode_logic, "Let's play an edging game...", mode_name='edging')
    return jsonify({"status": "edging_started"})

@app.route('/start_milking_mode', methods=['POST'])
def start_milking_route():
    start_background_mode(milking_mode_logic, "You're so close... I'm taking over completely now.", mode_name='milking')
    return jsonify({"status": "milking_started"})

@app.route('/stop_auto_mode', methods=['POST'])
def stop_auto_route():
    if auto_mode_active_task: auto_mode_active_task.stop()
    return jsonify({"status": "auto_mode_stopped"})

# ─── APP STARTUP ───────────────────────────────────────────────────────────────────────────────────
def on_exit():
    print("[INFO] Saving settings on exit...")
    settings.save(llm, chat_history)
    print("[OK] Settings saved.")

def main():
    atexit.register(on_exit)
    print(f"[INFO] Starting Handy AI app at {time.strftime('%Y-%m-%d %H:%M:%S')}...")
    app.run(host='0.0.0.0', port=5000, debug=False)


if __name__ == '__main__':
    main()
