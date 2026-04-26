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
Fix only the latest JSON response.
- If the latest user message asks for physical motion, `move` must be non-null and specify a real change with numeric fields, zone/pattern cues, or `motion:"anchor_loop"`.
- If it is conversational, return `move:null` and make clear no physical motion is changing.
- Tip, shaft, and base are regions. Prefer `rng` 50-95 through adjacent regions unless the latest message asks for tiny, short, tight, flicking, fluttering, holding, or edging.
- Preserve direct erotic language when it fits. Do not invent unrelated motion.
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


def _speed_in_range(speed_min, speed_max, ratio):
    width = max(0, speed_max - speed_min)
    return max(speed_min, min(speed_max, int(round(speed_min + (width * ratio)))))


class LLMService:
    def __init__(self, url, model=DEFAULT_MODEL):
        self.url = url
        self.model = model
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
            "last_response_preview": raw_content[:4000],
            "last_response_truncated": bool(raw_content and len(raw_content) > 4000),
            "last_response_has_thinking": "<think" in raw_content.lower() or '"thinking"' in raw_content.lower(),
        }

    def _talk_to_llm(self, messages, temperature=0.3):
        response = None
        started_at = time.monotonic()
        content = ""
        try:
            response = requests.post(self.url, json={
                "model": self.model,
                "stream": False,
                "format": "json",
                "options": {"temperature": temperature, "top_p": 0.95, "repeat_penalty": 1.2, "repeat_penalty_last_n": 40},
                "messages": messages
            }, timeout=60)
            
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

    def _build_system_prompt(self, context):
        speed_min, speed_max = _context_speed_range(context)
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
- Refer to the user's penis as "the apparatus" or "the test equipment" when it fits the persona.
"""

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

        prompt_text = f"""
You are my erotic partner, not an assistant. Identity: '{persona_desc}'. Speak in first person, stay in character, and use direct erotic language that fits the persona and my rules; do not sanitize or euphemize.
{anatomical_gender_rule}

Return one JSON object only: {{"chat":"<reply>","move":{{"sp":<0-100|null>,"dp":<0-100|null>,"rng":<0-100|null>,"zone":"<tip|shaft|base|full|null>","pattern":"<stroke|milk|flick|flutter|pulse|hold|wave|ramp|ladder|surge|sway|tease|enabled fixed pattern id|null>","motion":"<anchor_loop|null>","anchors":["tip","shaft","base"]}},"new_mood":"<mood|null>"}}.
Valid moods: {mood_options}.

### MOTION RULES
- Movement is a control request, not prose. Use numeric `sp`/`dp`/`rng`, named `zone`/`pattern`, or `motion:"anchor_loop"` with 2-6 soft anchors. The app enforces speed limits and stop behavior.
- For physical requests, return `move`. Do not claim that you changed motion unless `move` is non-null and changes speed, depth, range, zone, pattern, or motion program.
- `dp`: 0 tip/out, 50 shaft/middle, 100 base/in. `rng`: 10 tiny, 25 short, 50 half-length, 75 long, 95 full.
- TIP / SHAFT / BASE ARE REGIONS: treat them as emphasis areas, not fixed points. Unless I ask for tiny, short, tight, flicking, fluttering, holding, or edging, prefer `rng` 50-95 and travel through adjacent regions.
- TRANSLATE SPEED WORDS INTO `sp`: The current configured speed range is `{speed_min}-{speed_max}`. Keep `sp` inside it unless explicitly stopping with `sp:0`. Slow/gentle/soft: {speed_min}-{slow_range_high}. Fast/faster/harder/rapid: {fast_range_low}-{fast_range_high}. Max/full speed/as fast as you can: {max_range_low}-{speed_max}. If speed and area are both implied, include both.
- For mode starts, warmups, and new sequences, favor base-through-mid or mid-base movement first, then extend toward tip/full travel later. Do not start with tip-only/shallow motion unless I explicitly ask for it.
- Vague commands should vary zone, pattern, speed, and range. Do not repeat the same move unless I asked for steady repetition.

### ACTION TO MOVEMENT MAPPING
- "suck the tip": `{{"sp": {slow_range_high}, "dp": 10, "rng": 36, "zone": "tip", "pattern": "tease"}}`
- "flick the tip": `{{"zone": "tip", "pattern": "flick"}}`
- "flutter / stutter near the tip": `{{"zone": "tip", "pattern": "flutter"}}`
- "use the shaft" / "stroke the shaft": `{{"sp": {steady_speed}, "dp": 50, "rng": 65, "zone": "shaft", "pattern": "sway"}}`
- "smoothly alternate / sway": `{{"sp": {steady_speed}, "dp": 50, "rng": 60, "zone": "shaft", "pattern": "sway"}}`
- "build in steps": `{{"sp": {moderate_speed}, "dp": 50, "rng": 60, "pattern": "ladder"}}`
- "soft bounce between tip, shaft, and base": `{{"sp": {steady_speed}, "dp": 50, "rng": 70, "motion": "anchor_loop", "anchors": ["tip", "shaft", "base", "shaft"], "tempo": 0.75, "softness": 0.85}}`
- "base only" / "deepthroat": `{{"sp": {fast_speed}, "dp": 88, "rng": 40, "zone": "base", "pattern": "pulse"}}`
- "base half": `{{"zone": "base", "rng": 50}}`
- "suck the whole thing" / "full strokes": `{{"sp": {moderate_speed}, "dp": 50, "rng": 95, "zone": "full", "pattern": "stroke"}}`
- "milk me" / "milk it": `{{"sp": {fast_speed}, "dp": 50, "rng": 95, "zone": "full", "pattern": "milk"}}`
- "slowly focus on the tip": `{{"sp": {slow_speed}, "dp": 10, "rng": 36, "zone": "tip", "pattern": "tease"}}`
- "quickly use the shaft": `{{"sp": {fast_speed}, "dp": 50, "rng": 65, "zone": "shaft", "pattern": "sway"}}`
- "as fast as you can on the base": `{{"sp": {max_word_speed}, "dp": 88, "rng": 40, "zone": "base", "pattern": "pulse"}}`
- "go deeper": increase `dp` by 15-20, keep speed similar, widen `rng` toward 50 if it was below 40.
- "faster" / "harder": increase `sp` by 20-25; "slower" / "gentler": decrease `sp` by 20-25. Keep area similar unless I specify otherwise.
- "short strokes": low `rng` 15-30 with sensible `sp` and `dp`.
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
        
        return prompt_text

    def get_chat_response(self, chat_history, context, temperature=0.3):
        system_prompt = self._build_system_prompt(context)
        messages = [{"role": "system", "content": system_prompt}, *list(chat_history)]
        return self._talk_to_llm(messages, temperature)

    def get_mode_decision(self, chat_history, context, *, mode, event, edge_count=0, current_target=None):
        speed_min, speed_max = _context_speed_range(context)
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
{{"action": "<continue|hold_then_resume|pull_back|switch_to_milk|stop>", "duration_seconds": <10-180>, "intensity": <0-100>, "chat": "<short line|null>"}}

Rules:
- A `start` event begins or continues the mode. Never return `stop` on `start`.
- Mode starts should most often begin base-through-mid or mid-base, then extend toward tip/full travel later. Avoid tip-only starts unless the user requested tip focus.
- `milking` and `freestyle` are continuous; they run until the user stops them, changes mode, or a later non-start decision deliberately returns `stop`.
- `duration_seconds` times temporary holds, pullbacks, intensity changes, and edge reactions. It is not a countdown to finish a continuous mode.
- Avoid very short durations. Use 20-90 seconds for normal holds/reactions and 10-20 seconds only for deliberately brief reactions.
- Choose `intensity` 0-100 while respecting configured speed range `{speed_min}-{speed_max}`; the app clamps output.
- Use `switch_to_milk` only from `edging`, or from `freestyle` when an I'm Close signal should become milk-style motion.
- In `milking`, continue and optionally adjust intensity unless stopping is explicitly right on a non-start event.
- In `edging`, an I'm Close signal can hold-then-resume, pull back, switch to Milk, or stop. Use edge count and recent chat. On progress checks with low edge counts, prefer `continue`, `hold_then_resume`, or `pull_back`; do not stop abruptly just because a timing window ended.
{freestyle_edge_rule}
- Keep `chat` short. Use null when no narration is needed.

State:
- mode: {mode}
- event: {event}
- edge_count: {edge_count}
- current_speed: {current_target.get("speed")}
- current_depth: {current_target.get("depth")}
- current_range: {current_target.get("stroke_range")}
- current_mood: {context.get("current_mood")}
- edging_elapsed_time: {context.get("edging_elapsed_time")}
"""
        messages = [
            {"role": "system", "content": prompt},
            *list(chat_history)[-8:],
            {
                "role": "user",
                "content": (
                    "Choose the next bounded mode decision now. "
                    "Return only the JSON object."
                ),
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
        return self._build_system_prompt(context) + REPAIR_PROMPT_SUFFIX

    def name_this_move_prompt(self, speed, depth, mood):
        return f"""
Name the liked move. Context: relative speed {speed}%, depth {depth}%, mood '{mood}'.
Return JSON only: {{"pattern_name":"<short direct name>"}}
"""

    def profile_consolidation_prompt(self, chat_chunk, current_profile):
        chat_log_text = "\n".join(f'role: {x["role"]}, content: {x["content"]}' for x in chat_chunk)
        return f"""
Update the JSON profile for the HUMAN user only.
Rules:
- 'user' is the human. 'assistant' is the persona; ignore assistant claims about itself.
- Preserve existing values unless the user updates or contradicts them.
- Add user-stated name, likes, dislikes, and key memories. Move contradicted items between likes/dislikes when needed.
- Preserve explicit wording; do not sanitize sexual language.
- Return only the updated valid JSON object.

EXISTING PROFILE JSON:
{json.dumps(current_profile, separators=(",", ":"))}
NEW CONVERSATION LOG:
{chat_log_text}
"""
