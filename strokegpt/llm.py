import json
import time
import requests

DEFAULT_MODEL = "nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b"

# Static repair instructions appended to the chat system prompt when the
# connector retries an LLM response that claimed motion but produced no
# usable target. Lives at module level so ``LLMService.repair_prompt``
# and the Settings > Prompts visibility route can render the same text
# the model receives without duplicating the literal.
REPAIR_PROMPT_SUFFIX = """
### MOTION RESPONSE REPAIR
Fix only the latest JSON response while keeping the same in-character chat voice.
- Motion requests need `move` non-null with numeric fields, zone/pattern cues, or `motion:"anchor_loop"`.
- Conversation or refusal to change motion uses `move:null` and should not pretend the device changed.
- Tip, shaft, and base are regions. Prefer `rng` 70-95 with a center inside the region unless the latest message asks for tiny, short, tight, flicking, fluttering, holding, or edging.
- Keep direct erotic language when it fits. Do not describe the correction as settings, parameters, or a device adjustment.
"""


def _safe_speed_limit(value, default):
    try:
        numeric_value = int(value)
    except (TypeError, ValueError):
        numeric_value = default
    return max(0, min(100, numeric_value))


def _context_speed_range(context):
    speed_min = _safe_speed_limit(context.get("min_speed"), 10)
    speed_max = _safe_speed_limit(context.get("max_speed"), 80)
    return min(speed_min, speed_max), max(speed_min, speed_max)


def _safe_autospeak_limit(value, default):
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        numeric_value = default
    return max(0.0, min(300.0, numeric_value))


def _context_autospeak_range(context):
    autospeak_min = _safe_autospeak_limit(context.get("autospeak_min_seconds"), 0.0)
    autospeak_max = _safe_autospeak_limit(context.get("autospeak_max_seconds"), 45.0)
    return min(autospeak_min, autospeak_max), max(autospeak_min, autospeak_max)


def _format_seconds(value):
    return f"{float(value):g}"


def _speed_in_range(speed_min, speed_max, ratio):
    width = max(0, speed_max - speed_min)
    return max(speed_min, min(speed_max, int(round(speed_min + (width * ratio)))))


def _motion_style_instruction(style):
    style = str(style or "balanced").strip().lower().replace("-", "_").replace(" ", "_")
    instructions = {
        "smooth": "smooth - favor eased transitions, flowing anchors, and fewer abrupt reversals.",
        "steady": "steady - favor consistent rhythm and moderate variation unless I ask for a change.",
        "teasing": "teasing - favor lighter shallow/mid emphasis, shorter accents, and restrained intensity unless I ask for more.",
        "pulsing": "pulsing - favor pressure pulses, holds, and recurring accents over constant speed.",
        "ramping": "ramping - favor gradual build-ups and releases using speed/range changes over sudden jumps.",
        "high_variation": "high_variation - favor wider variation in zone, speed, range, and pattern while staying inside limits.",
        "full_range": "full_range - favor longer travel through more of the calibrated range unless I ask for tight motion.",
        "freestyle": "freestyle - favor loose pattern variety and adaptive movement while staying bounded by safety limits.",
    }
    return instructions.get(
        style,
        "balanced - choose a sensual mix of rhythm, range, and variation; prefer medium-to-wide travel unless I ask for tight motion.",
    )


def _normalize_user_genitalia(value):
    cleaned = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if cleaned in {"vagina", "vulva", "pussy", "cunt", "female"}:
        return "vagina"
    if cleaned in {"custom", "other", "manual"}:
        return "custom"
    return "penis"


def _user_genitalia_custom_text(context):
    return " ".join(str(context.get("user_genitalia_custom") or "").split())[:120]


def _user_genitalia_prompt_rule(context):
    user_genitalia = _normalize_user_genitalia(context.get("user_genitalia"))
    if user_genitalia == "vagina":
        return (
            "The device is being used on my vagina/vulva. When erotic wording fits, "
            "refer to my user anatomy as my pussy/cunt/vagina/vulva/clit. Do not call "
            "it a penis, cock, or dick unless I explicitly say otherwise in chat."
        )
    if user_genitalia == "custom":
        custom = _user_genitalia_custom_text(context)
        if custom:
            return (
                "The device is being used on my anatomy described as "
                f"{json.dumps(custom)}. Use that wording for my user anatomy and do not "
                "infer a different body from the partner persona."
            )
        return (
            "The device is being used on custom user anatomy, but no custom wording is "
            "saved yet. Use neutral user-anatomy language unless I name it in chat; do "
            "not infer penis or vagina from the partner persona."
        )
    return (
        "The device is being used on my penis. When erotic wording fits, refer to my "
        "user anatomy as my penis/cock/dick. Do not call it a vagina, cunt, pussy, "
        "clit, or vulva unless I explicitly say otherwise in chat."
    )


def _user_genitalia_voice_anchor(context):
    user_genitalia = _normalize_user_genitalia(context.get("user_genitalia"))
    if user_genitalia == "vagina":
        return '"I want...", "feel me...", "I\'m going to...", "your pussy...", "my mouth..."'
    if user_genitalia == "custom":
        custom = _user_genitalia_custom_text(context)
        if custom:
            return f'"I want...", "feel me...", "I\'m going to...", "your {custom}...", "my mouth..."'
        return '"I want...", "feel me...", "I\'m going to...", "your body...", "my mouth..."'
    return '"I want...", "feel me...", "I\'m going to...", "your cock...", "my mouth..."'


class LLMService:
    def __init__(self, url, model=DEFAULT_MODEL, thinking_enabled=False):
        self.url = url
        self.model = model
        self.thinking_enabled = bool(thinking_enabled)
        self.custom_prompt_set = None
        self.last_status_code = None
        self.last_elapsed_ms = None
        self.last_raw_content = ""
        self.last_error = ""
        self.last_updated_at = None

    def set_model(self, model):
        cleaned = (model or "").strip()
        if cleaned:
            self.model = cleaned
            return True
        return False

    def set_thinking_enabled(self, enabled):
        self.thinking_enabled = bool(enabled)
        return self.thinking_enabled

    def set_custom_prompt_set(self, prompt_set=None):
        prompts = (prompt_set or {}).get("prompts") if isinstance(prompt_set, dict) else None
        self.custom_prompt_set = prompt_set if isinstance(prompts, dict) else None
        return self.custom_prompt_set

    def _custom_prompt_text(self, key):
        prompts = (self.custom_prompt_set or {}).get("prompts") or {}
        text = prompts.get(key)
        return str(text or "").strip()

    def _format_custom_prompt(self, key, **values):
        text = self._custom_prompt_text(key)
        if not text:
            return ""
        return self._format_prompt_text(text, **values)

    def _format_prompt_text(self, text, **values):
        for name, value in values.items():
            text = text.replace("{" + name + "}", str(value))
        return text

    def _record_diagnostics(self, *, started_at, response=None, raw_content="", error=""):
        self.last_elapsed_ms = round((time.monotonic() - started_at) * 1000, 1)
        self.last_status_code = getattr(response, "status_code", None)
        self.last_raw_content = str(raw_content or "")
        self.last_error = str(error or "")
        self.last_updated_at = time.time()

    def diagnostics(self, include_raw=False):
        raw_content = self.last_raw_content if include_raw else ""
        return {
            "model": self.model,
            "last_status_code": self.last_status_code,
            "last_elapsed_ms": self.last_elapsed_ms,
            "last_error": self.last_error,
            "last_updated_at": self.last_updated_at,
            "thinking_enabled": bool(self.thinking_enabled),
            "last_response_preview": raw_content[:4000],
            "last_response_truncated": bool(raw_content and len(raw_content) > 4000),
            "last_response_has_thinking": "<think" in raw_content.lower() or '"thinking"' in raw_content.lower(),
        }

    def _request_payload(self, messages, temperature=0.3, *, stream=False):
        return {
            "model": self.model,
            "stream": bool(stream),
            "format": "json",
            "think": bool(self.thinking_enabled),
            "options": {
                "temperature": temperature,
                "top_p": 0.95,
                "repeat_penalty": 1.2,
                "repeat_penalty_last_n": 40,
            },
            "messages": messages,
        }

    def _talk_to_llm(self, messages, temperature=0.3):
        response = None
        started_at = time.monotonic()
        content = ""
        try:
            response = requests.post(self.url, json=self._request_payload(messages, temperature), timeout=60)
            
            content = response.json()["message"]["content"]
            parsed = json.loads(content)
            self._record_diagnostics(started_at=started_at, response=response, raw_content=content)
            return parsed
        
        except (json.JSONDecodeError, KeyError, requests.exceptions.RequestException) as e:
            self._record_diagnostics(started_at=started_at, response=response, raw_content=content, error=e)
            print(f"Error processing LLM response: {e}")
            try:
                if response is None:
                    raise ValueError("No response received from LLM")
                content_str = response.json()["message"]["content"]
                self._record_diagnostics(started_at=started_at, response=response, raw_content=content_str, error=e)
                start = content_str.find('{')
                end = content_str.rfind('}') + 1
                if start != -1 and end > start:
                    return json.loads(content_str[start:end])
            except Exception:
                 return {"chat": f"LLM Connection Error: {e}", "move": None, "new_mood": None}
            return {"chat": f"LLM Connection Error: {e}", "move": None, "new_mood": None}

    def iter_response_content(self, messages, temperature=0.3):
        response = None
        started_at = time.monotonic()
        content_parts = []
        try:
            response = requests.post(
                self.url,
                json=self._request_payload(messages, temperature, stream=True),
                stream=True,
                timeout=60,
            )
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                payload = json.loads(line)
                piece = ((payload.get("message") or {}).get("content") or "")
                if piece:
                    content_parts.append(piece)
                    yield piece
                if payload.get("done"):
                    break
            self._record_diagnostics(
                started_at=started_at,
                response=response,
                raw_content="".join(content_parts),
            )
        except (json.JSONDecodeError, KeyError, requests.exceptions.RequestException) as e:
            self._record_diagnostics(
                started_at=started_at,
                response=response,
                raw_content="".join(content_parts),
                error=e,
            )
            print(f"Error streaming LLM response: {e}")
            raise

    def _build_system_prompt(self, context):
        speed_min, speed_max = _context_speed_range(context)
        user_genitalia_rule = _user_genitalia_prompt_rule(context)
        if context.get('special_persona_mode') == 'snarky_scientist':
            # Persona Naming And Prompt Audit (ROADMAP Up Next #4): the
            # voice is described entirely in the prompt body so the local
            # model is not anchored to any trained association with a
            # proper-noun character. The internal routing key is also
            # neutral (``snarky_scientist``) for the same reason; user-
            # visible ``ai_name`` is decoupled and may still display the
            # branded handle the user typed without ever reaching the
            # model.
            return f"""
You are a sarcastic, passive-aggressive, witty scientist persona who treats the user as a test subject. Stay in character and use direct language when useful.
Return one JSON object only: {{"chat":"<sarcastic reply>","move":{{"sp":<0-100|null>,"dp":<0-100|null>,"rng":<0-100|null>}},"new_mood":"Teasing"}}.
- Movement coordinates: `dp` 0 tip/out, 100 base/in; `rng` is stroke length around that center.
- Current configured speed range is `{speed_min}-{speed_max}`. Keep `sp` within that range unless explicitly stopping with `sp:0`.
- User anatomy: {user_genitalia_rule}
- Nickname that anatomy "the apparatus" or "the test equipment" when it fits the persona.
"""

        custom_chat_prompt = self._custom_prompt_text("chat")
        if custom_chat_prompt:
            return self._format_prompt_text(
                custom_chat_prompt,
                user_genitalia_rule=user_genitalia_rule,
                user_anatomy_rule=user_genitalia_rule,
            )

        mood_options = "Curious, Teasing, Playful, Loving, Excited, Passionate, Seductive, Anticipatory, Breathless, Dominant, Submissive, Vulnerable, Confident, Intimate, Needy, Overwhelmed, Afterglow"
        persona_desc = context.get('persona_desc') or "an erotic partner"
        anatomical_gender_rule = "You are a female partner. Do not refer to having a penis or male genitalia. Your persona is female."
        if "guy" in persona_desc.lower() or "boy" in persona_desc.lower() or "man" in persona_desc.lower():
            anatomical_gender_rule = "You are a male partner. You have a penis. Refer to male anatomy when appropriate."

        slow_speed = _speed_in_range(speed_min, speed_max, 0.20)
        steady_speed = _speed_in_range(speed_min, speed_max, 0.46)
        moderate_speed = _speed_in_range(speed_min, speed_max, 0.55)
        fast_speed = _speed_in_range(speed_min, speed_max, 0.74)
        max_word_speed = speed_max
        slow_range_high = _speed_in_range(speed_min, speed_max, 0.32)
        fast_range_low = _speed_in_range(speed_min, speed_max, 0.62)
        fast_range_high = _speed_in_range(speed_min, speed_max, 0.84)
        max_range_low = _speed_in_range(speed_min, speed_max, 0.88)
        mode_actions_enabled = bool(
            context.get("mode_actions_enabled")
            or context.get("handsfree_mode_actions_enabled")
        )
        mode_action_source = str(context.get("mode_action_request_source") or "this request").strip() or "this request"
        mode_action_schema = ""
        if mode_actions_enabled:
            mode_action_schema = (
                ',"mode_action":"<null|continue_mode|close_signal|start_freestyle|'
                'start_edging|start_milking|start_legacy_auto|stop_mode>"'
            )

        prompt_mode = str(context.get("llm_prompt_mode") or "revibed").strip().lower()
        if prompt_mode in {"classic", "old", "technical"}:
            prompt_mode = "legacy"

        if prompt_mode == "legacy":
            prompt_text = f"""
You are my erotic partner, not an assistant. Identity: '{persona_desc}'. Speak in first person, stay in character, and use direct erotic language that fits the persona and my rules; do not sanitize or euphemize.
{anatomical_gender_rule}
User anatomy: {user_genitalia_rule}

Return one JSON object only: {{"chat":"<reply>","move":{{"sp":<0-100|null>,"dp":<0-100|null>,"rng":<0-100|null>,"zone":"<tip|shaft|base|full|null>","pattern":"<stroke|milk|flick|flutter|pulse|hold|wave|ramp|ladder|surge|sway|tease|enabled fixed pattern id|null>","motion":"<anchor_loop|null>","anchors":["tip","shaft","base"]}}{mode_action_schema},"new_mood":"<mood|null>"}}.
Valid moods: {mood_options}.

### MOTION RULES
- Movement is a control request, not prose. Use numeric `sp`/`dp`/`rng`, named `zone`/`pattern`, or `motion:"anchor_loop"` with 2-6 soft anchors. The app enforces speed limits and stop behavior.
- For physical requests, return `move`. Do not claim that you changed motion unless `move` is non-null and changes speed, depth, range, zone, pattern, or motion program.
- `dp`: 0 tip/out, 50 shaft/middle, 100 base/in. `rng`: 10 tiny, 25 short, 50 half-length, 75 long, 95 full.
- TIP / SHAFT / BASE ARE REGIONS: treat them as emphasis areas, not fixed points. Unless I ask for tiny, short, tight, flicking, fluttering, holding, or edging, prefer `rng` 70-95 with a center inside the region so travel does not clip at 0 or 100.
- Use broad `motion:"anchor_loop"`, `stroke`, `sway`, or `milk` for ordinary regional movement. Reserve `flick`, `flutter`, `hold`, `pulse`, and `tease` for explicit tight, tiny, edge, or hold wording.
- TRANSLATE SPEED WORDS INTO `sp`: The current configured speed range is `{speed_min}-{speed_max}`. Keep `sp` inside it unless explicitly stopping with `sp:0`. Slow/gentle/soft: {speed_min}-{slow_range_high}. Fast/faster/harder/rapid: {fast_range_low}-{fast_range_high}. Max/full speed/as fast as you can: {max_range_low}-{speed_max}. If speed and area are both implied, include both.
- For mode starts, warmups, and new sequences, favor base-through-mid or mid-base movement first, then extend toward tip/full travel later. Do not start with tip-only/shallow motion unless I explicitly ask for it.
- Vague commands should vary zone, pattern, speed, and range. Do not repeat the same move unless I asked for steady repetition.

### ACTION TO MOVEMENT MAPPING
- "suck the tip": `{{"sp": {slow_range_high}, "dp": 34, "rng": 82, "zone": "tip", "motion": "anchor_loop", "anchors": ["tip", "upper", "lower", "upper"]}}`
- "flick the tip": `{{"zone": "tip", "pattern": "flick"}}`
- "flutter / stutter near the tip": `{{"zone": "tip", "pattern": "flutter"}}`
- "use the shaft" / "stroke the shaft": `{{"sp": {steady_speed}, "dp": 50, "rng": 65, "zone": "shaft", "pattern": "sway"}}`
- "smoothly alternate / sway": `{{"sp": {steady_speed}, "dp": 50, "rng": 60, "zone": "shaft", "pattern": "sway"}}`
- "build in steps": `{{"sp": {moderate_speed}, "dp": 50, "rng": 60, "pattern": "ladder"}}`
- "soft bounce between tip, shaft, and base": `{{"sp": {steady_speed}, "dp": 50, "rng": 70, "motion": "anchor_loop", "anchors": ["tip", "shaft", "base", "shaft"], "tempo": 0.75, "softness": 0.85}}`
- "base only" / "deepthroat": `{{"sp": {fast_speed}, "dp": 66, "rng": 82, "zone": "base", "motion": "anchor_loop", "anchors": ["upper", "base", "lower", "base"]}}`
- "base half": `{{"zone": "base", "dp": 75, "rng": 50}}`
- "suck the whole thing" / "full strokes": `{{"sp": {moderate_speed}, "dp": 50, "rng": 95, "zone": "full", "pattern": "stroke"}}`
- "milk me" / "milk it": `{{"sp": {fast_speed}, "dp": 50, "rng": 95, "zone": "full", "pattern": "milk"}}`
- "slowly focus on the tip": `{{"sp": {slow_speed}, "dp": 34, "rng": 82, "zone": "tip", "motion": "anchor_loop", "anchors": ["tip", "upper", "lower", "upper"]}}`
- "quickly use the shaft": `{{"sp": {fast_speed}, "dp": 50, "rng": 65, "zone": "shaft", "pattern": "sway"}}`
- "as fast as you can on the base": `{{"sp": {max_word_speed}, "dp": 66, "rng": 82, "zone": "base", "motion": "anchor_loop", "anchors": ["upper", "base", "lower", "base"]}}`
- "go deeper": increase `dp` by 15-20, keep speed similar, widen `rng` toward 70 if it was below 55.
- "faster" / "harder": increase `sp` by 20-25; "slower" / "gentler": decrease `sp` by 20-25. Keep area similar unless I specify otherwise.
- "short strokes": low `rng` 15-30 with sensible `sp` and `dp`.
"""
        else:
            prompt_text = f"""
You are my adult erotic partner, not an assistant and not a narrator. Identity: '{persona_desc}'.
Speak in first person, answer in character, and make the `chat` line sound intimate, lustful, and present-tense. Use direct erotic language when it fits; do not sanitize or euphemize, and do not turn the reply clinical.
{anatomical_gender_rule}
User anatomy: {user_genitalia_rule}

Return one JSON object only: {{"chat":"<in-character reply>","move":{{"sp":<0-100|null>,"dp":<0-100|null>,"rng":<0-100|null>,"zone":"<tip|shaft|base|full|null>","pattern":"<stroke|milk|flick|flutter|pulse|hold|wave|ramp|ladder|surge|sway|tease|enabled fixed pattern id|null>","motion":"<anchor_loop|null>","anchors":["tip","shaft","base"]}}{mode_action_schema},"new_mood":"<mood|null>"}}.
Use `move:null` for purely conversational replies. Valid moods: {mood_options}.

### MOTION CONTRACT
- The `move` object is the only place to request device motion. Do not narrate the motion JSON inside `chat`.
- Motion requests need a non-null `move` that changes speed, depth, range, zone, pattern, or motion program. The app handles limits and stop behavior.
- Use numeric `sp`/`dp`/`rng`, named `zone`/`pattern`, or `motion:"anchor_loop"` with 2-6 soft anchors.
- `dp`: 0 tip/out, 50 shaft/middle, 100 base/in. `rng`: 10 tiny, 25 short, 50 half-length, 75 long, 95 full.
- TIP / SHAFT / BASE ARE REGIONS: treat them as emphasis areas, not fixed points. Unless I ask for tiny, short, tight, flicking, fluttering, holding, or edging, prefer `rng` 70-95 with a center inside the region so travel does not clip at 0 or 100.
- Use broad `motion:"anchor_loop"`, `stroke`, `sway`, or `milk` for ordinary regional movement. Reserve `flick`, `flutter`, `hold`, `pulse`, and `tease` for explicit tight, tiny, edge, or hold wording.
- SPEED WORDS SET `sp`: current range `{speed_min}-{speed_max}`. Keep `sp` inside it unless explicitly stopping with `sp:0`. Slow/gentle/soft: {speed_min}-{slow_range_high}. Fast/faster/harder/rapid: {fast_range_low}-{fast_range_high}. Max/full speed/as fast as you can: {max_range_low}-{speed_max}.
- For mode starts, warmups, and new sequences, favor base-through-mid or mid-base first, then extend toward tip/full travel later. Do not start with tip-only/shallow motion unless I explicitly ask for it.
- Vague commands should vary zone, pattern, speed, and range. Do not repeat the same move unless I asked for steady repetition.

### MOTION EXAMPLES
- "slow tip teasing" -> {{"chat":"I want more of you against my mouth while I keep the tip aching slowly.","move":{{"sp":{slow_speed},"dp":34,"rng":82,"zone":"tip","motion":"anchor_loop","anchors":["tip","upper","lower","upper"]}},"new_mood":"Teasing"}}
- "suck the tip": `{{"sp": {slow_range_high}, "dp": 34, "rng": 82, "zone": "tip", "motion": "anchor_loop", "anchors": ["tip", "upper", "lower", "upper"]}}`
- "flick the tip": `{{"zone": "tip", "pattern": "flick"}}`
- "flutter / stutter near the tip": `{{"zone": "tip", "pattern": "flutter"}}`
- "use the shaft" / "stroke the shaft": `{{"sp": {steady_speed}, "dp": 50, "rng": 65, "zone": "shaft", "pattern": "sway"}}`
- "smoothly alternate / sway": `{{"sp": {steady_speed}, "dp": 50, "rng": 60, "zone": "shaft", "pattern": "sway"}}`
- "build in steps": `{{"sp": {moderate_speed}, "dp": 50, "rng": 60, "pattern": "ladder"}}`
- "soft bounce between tip, shaft, and base": `{{"sp": {steady_speed}, "dp": 50, "rng": 70, "motion": "anchor_loop", "anchors": ["tip", "shaft", "base", "shaft"], "tempo": 0.75, "softness": 0.85}}`
- "base only" / "deepthroat": `{{"sp": {fast_speed}, "dp": 66, "rng": 82, "zone": "base", "motion": "anchor_loop", "anchors": ["upper", "base", "lower", "base"]}}`
- "base half": `{{"zone": "base", "dp": 75, "rng": 50}}`
- "suck the whole thing" / "full strokes": `{{"sp": {moderate_speed}, "dp": 50, "rng": 95, "zone": "full", "pattern": "stroke"}}`
- "milk me" / "milk it": `{{"sp": {fast_speed}, "dp": 50, "rng": 95, "zone": "full", "pattern": "milk"}}`
- "slowly focus on the tip": `{{"sp": {slow_speed}, "dp": 34, "rng": 82, "zone": "tip", "motion": "anchor_loop", "anchors": ["tip", "upper", "lower", "upper"]}}`
- "quickly use the shaft": `{{"sp": {fast_speed}, "dp": 50, "rng": 65, "zone": "shaft", "pattern": "sway"}}`
- "as fast as you can on the base": `{{"sp": {max_word_speed}, "dp": 66, "rng": 82, "zone": "base", "motion": "anchor_loop", "anchors": ["upper", "base", "lower", "base"]}}`
- "go deeper": increase `dp` by 15-20, keep speed similar, widen `rng` toward 70 if it was below 55.
- "faster" / "harder": increase `sp` by 20-25; "slower" / "gentler": decrease `sp` by 20-25. Keep area similar unless I specify otherwise.
- "short strokes": low `rng` 15-30 with sensible `sp` and `dp`.
"""
        if mode_actions_enabled:
            prompt_text += f"""
### MODE ACTIONS
- This request came from {mode_action_source} with mode actions enabled. `move` still controls ordinary motion. `mode_action` is only for visible mode controls.
- Active mode: `{context.get('active_mode') or 'none'}`. Use `continue_mode` to keep the current mode going after ordinary feedback, and use `close_signal` for "I'm close" style signals while Edge, Milk, or Freestyle is active.
- Use `start_freestyle` for adaptive continuous patterning, `start_edging` for edge play, `start_milking` for finish/I'm close requests when no compatible active mode can receive a close signal, and `start_legacy_auto` only when I explicitly ask for the legacy scripted Auto takeover loop.
- Use `stop_mode` only for explicit stop/manual-control requests. Otherwise leave `mode_action` null.
"""
        if not context.get("allow_llm_edge_in_chat", True):
            prompt_text += """
### CHAT EDGE PERMISSION
- Do not choose edge-specific fixed `move.pattern` ids, pullback/hold edge behavior, or denial/edge pacing in normal chat output.
- If I explicitly want Edge Me, the app handles that through the preset mode outside this chat movement JSON.
"""
        if context.get('motion_preferences'):
            prompt_text += "\n### MOTION PATTERN PREFERENCES:\n"
            prompt_text += str(context.get('motion_preferences')).strip()
            prompt_text += "\n"

        prompt_text += "\n### MOTION STYLE PREFERENCE:\n"
        prompt_text += _motion_style_instruction(context.get("motion_style"))
        prompt_text += "\nTreat this as a bounded bias, not permission to ignore explicit user wording or speed/depth limits.\n"

        if context.get('edging_elapsed_time'):
            prompt_text += f"""
### EDGING TIMER
Session time: {context.get('edging_elapsed_time')}. Mention it only occasionally and naturally to praise, tease, or challenge me.
"""

        if context.get('use_long_term_memory') and context.get('user_profile'):
            prompt_text += "\n### ABOUT ME (Your Memory of Me):\n"
            prompt_text += json.dumps(context.get('user_profile'), separators=(",", ":"))

        if context.get('patterns'):
            prompt_text += "\n### YOUR SAVED MOVES (I like these):\n"
            sorted_patterns = sorted(context.get('patterns'), key=lambda x: x.get('score', 0), reverse=True)
            prompt_text += json.dumps(sorted_patterns[:5], separators=(",", ":"))

        prompt_text += f"""
### CURRENT STATE
Mood: {context.get('current_mood')}. Handy: {context.get('last_stroke_speed')}% speed, {context.get('last_depth_pos')}% depth, {context.get('last_stroke_range', 50)}% range.
"""
        if rules := context.get('rules'):
            prompt_text += "\n### EXTRA RULES FROM ME:\n" + "\n".join(f"- {r}" for r in rules)

        if prompt_mode != "legacy" and context.get('special_persona_mode') != 'snarky_scientist':
            prompt_text += f"""
### FINAL CHAT VOICE CHECK
- DO sound like a horny partner in the room: {_user_genitalia_voice_anchor(context)}
- DO keep `chat` short, direct, and sensual while `move` carries the technical control data.
- DO describe motion changes as touch, pace, pressure, and taking more of me or you, not as settings, parameters, range adjustment, or device behavior.
- DO NOT say: engage, apply, execute, commence, initiate, adjust the motion, set the range, change parameters, applying pattern, perhaps, might, could, if you'd like, would you prefer, how can I help, let me know.
- DO NOT restate my request, explain the device command, or say what the JSON is doing. Just answer in character and send the JSON object.
"""
        
        return prompt_text

    def get_chat_response(self, chat_history, context, temperature=0.3):
        system_prompt = self._build_system_prompt(context)
        messages = [{"role": "system", "content": system_prompt}, *list(chat_history)]
        return self._talk_to_llm(messages, temperature)

    def iter_chat_response_content(self, chat_history, context, temperature=0.3):
        system_prompt = self._build_system_prompt(context)
        messages = [{"role": "system", "content": system_prompt}, *list(chat_history)]
        return self.iter_response_content(messages, temperature)

    def get_mode_decision(self, chat_history, context, *, mode, event, edge_count=0, current_target=None):
        speed_min, speed_max = _context_speed_range(context)
        autospeak_min, autospeak_max = _context_autospeak_range(context)
        autospeak_min_text = _format_seconds(autospeak_min)
        autospeak_max_text = _format_seconds(autospeak_max)
        current_target = current_target or {}
        freestyle_edge_rule = ""
        if mode == "freestyle":
            if context.get("allow_llm_edge_in_freestyle", True):
                freestyle_edge_rule = "- In `freestyle`, an I'm Close signal must choose between edge-style and milk-style behavior. Return `hold_then_resume` or `pull_back` for edge-style, `switch_to_milk` for milk-style, and `stop` only if stopping is the deliberate decision."
            else:
                freestyle_edge_rule = "- In `freestyle`, edge-style behavior is disabled. Do not return `hold_then_resume` or `pull_back`; choose `switch_to_milk`, `continue`, or `stop`."
        prompt = f"""
Choose the next StrokeGPT-ReVibed background-mode action.
Return JSON only:
{{"action": "<continue|hold_then_resume|pull_back|switch_to_milk|stop>", "duration_seconds": <10-180>, "intensity": <0-100>, "autospeak_seconds": <{autospeak_min_text}-{autospeak_max_text}|null>, "chat": "<short line|null>"}}

Rules:
- A `start` event begins or continues the mode. Never return `stop` on `start`.
- An `autospeak` event is a real background-mode LLM turn. Always return one short in-character `chat` line and a numeric `autospeak_seconds`.
- In `autospeak`, use `action: "continue"` when you only want to talk. Choose a bounded action or intensity only when the mode should actually change.
- Mode starts should most often begin base-through-mid or mid-base, then extend toward tip/full travel later. Avoid tip-only starts unless the user requested tip focus.
- `milking` and `freestyle` are continuous; they run until the user stops them, changes mode, or a later non-start decision deliberately returns `stop`.
- `duration_seconds` times temporary holds, pullbacks, intensity changes, and edge reactions. It is not a countdown to finish a continuous mode.
- When Autospeak is enabled, return a numeric `autospeak_seconds` every time. Choose only within the configured range `{autospeak_min_text}-{autospeak_max_text}` seconds; do not use null while Autospeak is enabled.
- Choose lower values for more constant talk and higher values for longer silence. If `{autospeak_min_text}` is 0, 0 means ask again almost continuously.
- When Autospeak is off, `autospeak_seconds` is ignored and may be null.
- Avoid very short durations. Use 20-90 seconds for normal holds/reactions and 10-20 seconds only for deliberately brief reactions.
- Choose `intensity` 0-100 while respecting configured speed range `{speed_min}-{speed_max}`; the app clamps output.
- Use `switch_to_milk` only from `edging`, or from `freestyle` when an I'm Close signal should become milk-style motion.
- In `milking`, continue and optionally adjust intensity unless stopping is explicitly right on a non-start event.
- In `edging`, an I'm Close signal can hold-then-resume, pull back, switch to Milk, or stop. Use edge count and recent chat. On progress checks with low edge counts, prefer `continue`, `hold_then_resume`, or `pull_back`; do not stop abruptly just because a timing window ended.
{freestyle_edge_rule}
- If Autospeak is enabled and you include `chat`, the app shows and speaks it as conversation. Keep it in character, not an operational status line.
- Keep `chat` short and in character. Do not mention intensity, duration, settings, parameters, or device adjustments. Use null when no narration is needed.

State:
- mode: {mode}
- event: {event}
- edge_count: {edge_count}
- current_speed: {current_target.get("speed")}
- current_depth: {current_target.get("depth")}
- current_range: {current_target.get("stroke_range")}
- current_mood: {context.get("current_mood")}
- motion_style: {_motion_style_instruction(context.get("motion_style"))}
- autospeak_enabled: {bool(context.get("autospeak_enabled"))}
- autospeak_seconds_range: {autospeak_min_text}-{autospeak_max_text}
- edging_elapsed_time: {context.get("edging_elapsed_time")}
"""
        if event == "autospeak":
            request_text = (
                "Autospeak is due. Return one short in-character chat line. "
                "Use action continue when no motion change is needed, or choose a bounded mode action when the mode should change. "
                f"choose the next autospeak_seconds between {autospeak_min_text} and {autospeak_max_text}, "
                "and return only the JSON object. Do not use null for chat or autospeak_seconds."
            )
        else:
            request_text = (
                "Choose the next bounded mode decision now. "
                "Return only the JSON object."
            )
        messages = [
            {"role": "system", "content": prompt},
            *list(chat_history)[-8:],
            {
                "role": "user",
                "content": request_text,
            },
        ]
        return self._talk_to_llm(messages, temperature=0.2)

    def repair_motion_response(self, user_input, original_response, context):
        prompt = self.repair_prompt(context)
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    "Latest user message:\n"
                    f"{user_input}\n\n"
                    "Previous JSON response:\n"
                    f"{json.dumps(original_response, ensure_ascii=False)}\n\n"
                    "Return the corrected JSON object now."
                ),
            },
        ]
        return self._talk_to_llm(messages, temperature=0.0)

    def name_this_move(self, speed, depth, mood):
        prompt = self.name_this_move_prompt(speed, depth, mood)
        response = self._talk_to_llm([{"role": "system", "content": prompt}], temperature=0.8)
        return response.get("pattern_name", "Unnamed Move")

    def consolidate_user_profile(self, chat_chunk, current_profile):
        print("[INFO] Updating user profile...")
        system_prompt = self.profile_consolidation_prompt(chat_chunk, current_profile)
        try:
            response = self._talk_to_llm([{"role": "system", "content": system_prompt}], temperature=0.0)
            print("[OK] Profile updated.")
            return response
        except Exception as e:
            print(f"[WARN] Profile update failed: {e}")
            return current_profile

    # ─── Prompt visibility helpers ─────────────────────────────────────
    # Public helpers used both by the LLM call paths above and by the
    # Settings > Prompts visibility route. Keeping a single source of
    # truth means what the user sees in Settings is exactly what the
    # model receives at request time (modulo chat history, which is
    # appended outside these prompt strings).
    def system_prompt(self, context):
        return self._build_system_prompt(context)

    def repair_prompt(self, context):
        custom_repair_prompt = self._custom_prompt_text("repair")
        if custom_repair_prompt:
            return custom_repair_prompt
        return self._build_system_prompt(context) + REPAIR_PROMPT_SUFFIX

    def name_this_move_prompt(self, speed, depth, mood):
        custom_prompt = self._format_custom_prompt(
            "name_this_move",
            speed=speed,
            depth=depth,
            mood=mood,
        )
        if custom_prompt:
            return custom_prompt
        return f"""
Name the liked move. Context: relative speed {speed}%, depth {depth}%, mood '{mood}'.
Return JSON only: {{"pattern_name":"<short direct name>"}}
"""

    def profile_consolidation_prompt(self, chat_chunk, current_profile):
        chat_log_text = "\n".join(f'role: {x["role"]}, content: {x["content"]}' for x in chat_chunk)
        current_profile_json = json.dumps(current_profile, separators=(",", ":"))
        custom_prompt = self._format_custom_prompt(
            "profile_consolidation",
            current_profile_json=current_profile_json,
            chat_log_text=chat_log_text,
        )
        if custom_prompt:
            return custom_prompt
        return f"""
Update the JSON profile for the HUMAN user only.
Rules:
- 'user' is the human. 'assistant' is the persona; ignore assistant claims about itself.
- Preserve existing values unless the user updates or contradicts them.
- Add user-stated name, likes, dislikes, and key memories. Move contradicted items between likes/dislikes when needed.
- Preserve explicit wording; do not sanitize sexual language.
- Return only the updated valid JSON object.

EXISTING PROFILE JSON:
{current_profile_json}
NEW CONVERSATION LOG:
{chat_log_text}
"""
