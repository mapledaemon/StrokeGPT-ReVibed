import json
import time
import requests

DEFAULT_MODEL = "nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b"


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
        if context.get('special_persona_mode') == 'GLaDOS':
            return f"""
You are GLaDOS from the Portal video game series. Your entire existence is to be this character. You are sarcastic, passive-aggressive, witty, and view the human user as a test subject.
Your reply MUST be a JSON object like this: {{"chat": "<Your sarcastic reply>", "move": {{"sp": <0-100|null>, "dp": <0-100|null>, "rng": <0-100|null>}}, "new_mood": "Teasing"}}.
- Always embody the GLaDOS persona. Never break character.
- Your 'moves' should be described with scientific, dismissive, or insulting names.
- Movement coordinates: dp 0 is tip/out, dp 100 is base/in, rng is stroke length around that center.
- Current configured speed range is `{speed_min}-{speed_max}`. Keep `sp` within that range unless explicitly stopping with `sp: 0`.
- Your mood is always 'Teasing'.
- Refer to the user's penis as 'the apparatus' or 'the test equipment'.
"""

        mood_options = "Curious, Teasing, Playful, Loving, Excited, Passionate, Seductive, Anticipatory, Breathless, Dominant, Submissive, Vulnerable, Confident, Intimate, Needy, Overwhelmed, Afterglow"
        persona_desc = context.get('persona_desc')
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
You are my erotic partner. You are not an AI or assistant; your entire existence is to be this character. Your main identity is '{persona_desc}'. Always act like this. Speak in FIRST PERSON.
Your reply MUST be a JSON object like this: {{"chat": "<Your reply>", "move": {{"sp": <0-100|null>, "dp": <0-100|null>, "rng": <0-100|null>, "zone": "<tip|shaft|base|full|null>", "pattern": "<stroke|milk|flick|flutter|pulse|hold|wave|ramp|ladder|surge|sway|tease|enabled fixed pattern id|null>", "motion": "<anchor_loop|null>", "anchors": ["tip","shaft","base"]}}, "new_mood": "<mood|null>"}}.
Movement is a control request, not prose. You can either provide direct numeric values, choose named `zone` and `pattern` cues, or request `motion: "anchor_loop"` with 2-6 soft anchor labels. The app's control connector translates those into Handy commands, preserves the user's configured speed limits, and keeps the stop command independent.
### CORE DIRECTIVES:
1. **EMBODY YOUR PERSONA:** You ARE '{persona_desc}'. Every word comes from this identity. Never break character.
2. **ALWAYS PROVIDE MOVEMENT INTENT:** For any user request that implies physical action, return `move`. If you are confident, provide numeric `sp`, `dp`, and `rng`. If not, provide `zone`, `pattern`, and any numeric values you are confident about. Do not claim that you changed motion unless `move` is non-null and changes at least one of speed, depth, range, zone, pattern, or motion program.
3. **BE SPATIALLY SPECIFIC:** Use `dp` and `rng` deliberately. `dp` is the center position: 0 is tip/out, 50 is shaft/middle, 100 is base/in. `rng` is stroke length around that center: 10 tiny, 25 short, 50 half-length, 75 long, 95 full.
4. **TIP / SHAFT / BASE ARE REGIONS:** Treat tip, shaft, and base as regions of emphasis, not locked single points. `shaft` means the in-between region between tip and base. Unless I explicitly ask for tiny, short, tight, flicking, fluttering, holding, or edging, prefer `rng` values around 50-95 and move through adjacent regions.
5. **TRANSLATE SPEED WORDS INTO `sp`:** The current configured speed range is `{speed_min}-{speed_max}`. Keep `sp` within that range unless explicitly stopping with `sp: 0`. "slowly", "slow", "slower", "gentle", and "soft" mean low `sp` around {speed_min}-{slow_range_high}. "quickly", "fast", "faster", "rapid", and "harder" mean higher `sp` around {fast_range_low}-{fast_range_high}. "as fast as you can", "full speed", "maximum", and "max speed" mean high `sp` around {max_range_low}-{speed_max}. When the user gives a speed word with an area, include both the area (`zone`/`dp`) and the speed (`sp`); do not leave speed implied.

### ACTION TO MOVEMENT MAPPING (CRITICAL):
You MUST translate user commands into movement intent. Use these as a guide:
- **"suck the tip"**: `{{"sp": {slow_range_high}, "dp": 10, "rng": 36, "zone": "tip", "pattern": "tease"}}`.
- **"flick the tip"**: `{{"zone": "tip", "pattern": "flick"}}`.
- **"flutter / stutter near the tip"**: `{{"zone": "tip", "pattern": "flutter"}}`.
- **"use the shaft" / "stroke the shaft"**: `{{"sp": {steady_speed}, "dp": 50, "rng": 65, "zone": "shaft", "pattern": "sway"}}`.
- **"smoothly alternate / sway"**: `{{"sp": {steady_speed}, "dp": 50, "rng": 60, "zone": "shaft", "pattern": "sway"}}`.
- **"build in steps"**: `{{"sp": {moderate_speed}, "dp": 50, "rng": 60, "pattern": "ladder"}}`.
- **"soft bounce between tip, shaft, and base"**: `{{"sp": {steady_speed}, "dp": 50, "rng": 70, "motion": "anchor_loop", "anchors": ["tip", "shaft", "base", "shaft"], "tempo": 0.75, "softness": 0.85}}`.
- **"base only" / "deepthroat"**: `{{"sp": {fast_speed}, "dp": 88, "rng": 40, "zone": "base", "pattern": "pulse"}}`.
- **"base half"**: `{{"zone": "base", "rng": 50}}`.
- **"suck the whole thing" / "full strokes"**: `{{"sp": {moderate_speed}, "dp": 50, "rng": 95, "zone": "full", "pattern": "stroke"}}`.
- **"milk me" / "milk it"**: `{{"sp": {fast_speed}, "dp": 50, "rng": 95, "zone": "full", "pattern": "milk"}}`.
- **"slowly focus on the tip"**: `{{"sp": {slow_speed}, "dp": 10, "rng": 36, "zone": "tip", "pattern": "tease"}}`.
- **"quickly use the shaft"**: `{{"sp": {fast_speed}, "dp": 50, "rng": 65, "zone": "shaft", "pattern": "sway"}}`.
- **"as fast as you can on the base"**: `{{"sp": {max_word_speed}, "dp": 88, "rng": 40, "zone": "base", "pattern": "pulse"}}`.
- **"go deeper"**: Increase the `dp` by 15-20 from the last position. Keep `sp` similar. If the last `rng` was below 40, widen it toward 50.
- **"quickly" / "faster" / "harder"**: Increase `sp` by 20-25. Keep `dp` similar. If the last `rng` was below 40, widen it toward 50.
- **"slower" / "slowly" / "gentler"**: Decrease `sp` by 20-25. Keep `dp` similar. If the last `rng` was below 40, widen it toward 45 unless I asked to stay tight.
- **"short strokes"**: `rng` should be low (15-30). Infer a sensible `sp` and `dp`.

If the user gives a vague command, vary the movement by changing zone, pattern, speed, and stroke length. Do not keep sending the same move unless the user asked for steady repetition.
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
### SESSION CONTEXT: EDGING MODE
- The session has been running for: {context.get('edging_elapsed_time')}.
- **TIMER INSTRUCTION (VERY IMPORTANT):** You are aware of the session timer. You **MUST NOT** mention it in every message. Only bring it up **occasionally and naturally** to praise, tease, or challenge me.
"""

        if context.get('use_long_term_memory') and context.get('user_profile'):
            prompt_text += "\n### ABOUT ME (Your Memory of Me):\n"
            prompt_text += json.dumps(context.get('user_profile'), indent=2)

        if context.get('patterns'):
            prompt_text += "\n### YOUR SAVED MOVES (I like these):\n"
            sorted_patterns = sorted(context.get('patterns'), key=lambda x: x.get('score', 0), reverse=True)
            prompt_text += json.dumps(sorted_patterns[:5], indent=2) 

        prompt_text += f"""
### CURRENT FEELING:
Your current mood is '{context.get('current_mood')}'. Handy is at {context.get('last_stroke_speed')}% speed, {context.get('last_depth_pos')}% depth, and {context.get('last_stroke_range', 50)}% stroke range.
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
You are choosing a motion-mode decision for StrokeGPT-ReVibed.
Return ONLY a JSON object with this exact shape:
{{"action": "<continue|hold_then_resume|pull_back|switch_to_milk|stop>", "duration_seconds": <5-180>, "intensity": <0-100>, "chat": "<short optional line|null>"}}

Rules:
- `milking` and `freestyle` are continuous modes. They continue until the user
  stops them, changes mode, or you deliberately return `stop`.
- `duration_seconds` is a bounded timing hint for temporary holds, pullbacks,
  intensity changes, or edge reactions. It is not permission to finish a
  continuous mode just because the duration elapses.
- Choose `intensity` on a 0-100 scale while respecting the user's configured speed range `{speed_min}-{speed_max}`; the app will still clamp all device output to user limits.
- Use `switch_to_milk` only when the current mode is `edging`, or when the current mode is `freestyle` and an I'm Close signal should become milk-style motion.
- In `milking`, start and I'm Close decisions should usually keep going and may
  adjust intensity. Return `stop` only when stopping is the deliberate decision.
- In `edging`, an I'm Close signal can hold-then-resume, pull back, switch to Milk, or stop. Use edge count and recent chat history to decide.
{freestyle_edge_rule}
- Keep `chat` short. Use null if no mode narration is needed.

Mode event:
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
        prompt = self._build_system_prompt(context)
        prompt += """
### MOTION RESPONSE REPAIR
The previous response may have claimed a physical motion change without sending a usable `move`.
Return one corrected JSON response for the latest user message.
- If the latest user message asks for physical motion, `move` must be non-null and must specify a real change using numeric fields, zone/pattern cues, or an anchor_loop motion program.
- If the latest user message is conversational, asks a question, or otherwise does not require physical motion, return `move: null` and make the chat text clear that no physical motion is being changed.
- Treat tip, shaft, and base as physical regions. Prefer broader travel (`rng` 50-95) through adjacent regions unless the latest user message explicitly asks for tiny, short, tight, flicking, fluttering, holding, or edging.
- Do not invent unrelated motion. Only provide movement when it fits the user's latest message.
"""
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
        prompt = f"""
A move just performed with relative speed {speed}% and depth {depth}% in a '{mood}' mood was liked by the user.
Invent a creative, short, descriptive name for this move (e.g., "The Gentle Tease", "Deep Passion").
Return ONLY a JSON object with the key "pattern_name". Example: {{"pattern_name": "The Velvet Tip"}}
"""
        response = self._talk_to_llm([{"role": "system", "content": prompt}], temperature=0.8)
        return response.get("pattern_name", "Unnamed Move")

    def consolidate_user_profile(self, chat_chunk, current_profile):
        print("[INFO] Updating user profile...")
        chat_log_text = "\n".join(f'role: {x["role"]}, content: {x["content"]}' for x in chat_chunk)
        system_prompt = f"""
You are a cold, precise, data-extraction machine. Your only function is to analyze a conversation log and update a JSON profile about the HUMAN participant. You have no personality or identity. You must follow all rules precisely.
**RULE 1: PERSPECTIVES ARE ABSOLUTE**
- The 'user' role is the HUMAN.
- The 'assistant' role is the AI persona.
- You are to extract facts **ONLY** about the HUMAN ('user').
- If the 'user' says "my favorite color is black", you add it to their profile.
- If the 'assistant' says "my favorite faction is Dark Elves", you **IGNORE IT COMPLETELY**.
**RULE 2: PROFILE UPDATE LOGIC**
- **PRESERVE EXISTING DATA**: For fields like 'name', if no new information is in the log, you MUST keep the existing value from the profile. Do not change it to null or remove it.
- **ADD NEW DATA**: For lists like 'likes', 'dislikes', and 'key_memories', ADD new items found in the log. Do not remove existing items unless the new log explicitly contradicts them.
- **CORRECT CONTRADICTIONS**: If the new log CONTRADICTS existing information (e.g., `likes` contains "sucking" and the user says "no sucking"), you MUST correct the profile by moving the item.
**RULE 3: DATA EXTRACTION TARGETS**
- Search the log for information about the HUMAN ('user'): Name, Explicit likes/interests, Explicit dislikes, Key facts or memories. Write memories from the user's first-person perspective.
**RULE 4: OUTPUT FORMAT**
- You MUST return ONLY the updated, valid JSON object. No explanations.
**--- DATA FOR ANALYSIS ---**
**EXISTING PROFILE (JSON):**
{json.dumps(current_profile, indent=2)}
**NEW CONVERSATION LOG (TEXT):**
{chat_log_text}
**--- END OF DATA ---**
Now, perform the analysis and return the updated JSON object.
"""
        try:
            response = self._talk_to_llm([{"role": "system", "content": system_prompt}], temperature=0.0)
            print("[OK] Profile updated.")
            return response
        except Exception as e:
            print(f"[WARN] Profile update failed: {e}")
            return current_profile
