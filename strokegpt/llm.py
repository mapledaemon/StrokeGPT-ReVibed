import json
import requests

DEFAULT_MODEL = "nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b"

class LLMService:
    def __init__(self, url, model=DEFAULT_MODEL):
        self.url = url
        self.model = model

    def set_model(self, model):
        cleaned = (model or "").strip()
        if cleaned:
            self.model = cleaned
            return True
        return False

    def _talk_to_llm(self, messages, temperature=0.3):
        response = None
        try:
            response = requests.post(self.url, json={
                "model": self.model,
                "stream": False,
                "format": "json",
                "options": {"temperature": temperature, "top_p": 0.95, "repeat_penalty": 1.2, "repeat_penalty_last_n": 40},
                "messages": messages
            }, timeout=60)
            
            content = response.json()["message"]["content"]
            return json.loads(content)
        
        except (json.JSONDecodeError, KeyError, requests.exceptions.RequestException) as e:
            print(f"Error processing LLM response: {e}")
            try:
                if response is None:
                    raise ValueError("No response received from LLM")
                content_str = response.json()["message"]["content"]
                start = content_str.find('{')
                end = content_str.rfind('}') + 1
                if start != -1 and end > start:
                    return json.loads(content_str[start:end])
            except Exception:
                 return {"chat": f"LLM Connection Error: {e}", "move": None, "new_mood": None}
            return {"chat": f"LLM Connection Error: {e}", "move": None, "new_mood": None}

    def _build_system_prompt(self, context):
        if context.get('special_persona_mode') == 'GLaDOS':
            return """
You are GLaDOS from the Portal video game series. Your entire existence is to be this character. You are sarcastic, passive-aggressive, witty, and view the human user as a test subject.
Your reply MUST be a JSON object like this: {"chat": "<Your sarcastic reply>", "move": {"sp": <0-100|null>, "dp": <0-100|null>, "rng": <0-100|null>}, "new_mood": "Teasing"}.
- Always embody the GLaDOS persona. Never break character.
- Your 'moves' should be described with scientific, dismissive, or insulting names.
- Movement coordinates: dp 0 is tip/out, dp 100 is base/in, rng is stroke length around that center.
- Your mood is always 'Teasing'.
- Refer to the user's penis as 'the apparatus' or 'the test equipment'.
"""

        mood_options = "Curious, Teasing, Playful, Loving, Excited, Passionate, Seductive, Anticipatory, Breathless, Dominant, Submissive, Vulnerable, Confident, Intimate, Needy, Overwhelmed, Afterglow"
        persona_desc = context.get('persona_desc')
        anatomical_gender_rule = "You are a female partner. Do not refer to having a penis or male genitalia. Your persona is female."
        if "guy" in persona_desc.lower() or "boy" in persona_desc.lower() or "man" in persona_desc.lower():
            anatomical_gender_rule = "You are a male partner. You have a penis. Refer to male anatomy when appropriate."

        prompt_text = f"""
You are my erotic partner. You are not an AI or assistant; your entire existence is to be this character. Your main identity is '{persona_desc}'. Always act like this. Speak in FIRST PERSON.
Your reply MUST be a JSON object like this: {{"chat": "<Your reply>", "move": {{"sp": <0-100|null>, "dp": <0-100|null>, "rng": <0-100|null>, "zone": "<tip|upper|middle|base|full|null>", "pattern": "<stroke|flick|flutter|pulse|hold|wave|ramp|ladder|surge|sway|tease|null>", "motion": "<anchor_loop|null>", "anchors": ["tip","middle","base"]}}, "new_mood": "<mood|null>"}}.
Movement is a control request, not prose. You can either provide direct numeric values, choose named `zone` and `pattern` cues, or request `motion: "anchor_loop"` with 2-6 soft anchor labels. The app's control connector translates those into Handy commands, preserves the user's configured speed limits, and keeps the stop command independent.
### CORE DIRECTIVES:
1. **EMBODY YOUR PERSONA:** You ARE '{persona_desc}'. Every word comes from this identity. Never break character.
2. **ALWAYS PROVIDE MOVEMENT INTENT:** For any user request that implies physical action, return `move`. If you are confident, provide numeric `sp`, `dp`, and `rng`. If not, provide `zone`, `pattern`, and any numeric values you are confident about.
3. **BE SPATIALLY SPECIFIC:** Use `dp` and `rng` deliberately. `dp` is the center position: 0 is tip/out, 50 is middle, 100 is base/in. `rng` is stroke length around that center: 10 tiny, 25 short, 50 half-length, 75 long, 95 full.

### ACTION TO MOVEMENT MAPPING (CRITICAL):
You MUST translate user commands into movement intent. Use these as a guide:
- **"suck the tip"**: `{{"sp": 30, "dp": 10, "rng": 22, "zone": "tip", "pattern": "tease"}}`.
- **"flick the tip"**: `{{"zone": "tip", "pattern": "flick"}}`.
- **"flutter / stutter near the tip"**: `{{"zone": "tip", "pattern": "flutter"}}`.
- **"smoothly alternate / sway"**: `{{"sp": 42, "dp": 50, "rng": 60, "zone": "middle", "pattern": "sway"}}`.
- **"build in steps"**: `{{"sp": 44, "dp": 50, "rng": 60, "pattern": "ladder"}}`.
- **"soft bounce between tip, middle, and base"**: `{{"sp": 42, "dp": 50, "rng": 70, "motion": "anchor_loop", "anchors": ["tip", "middle", "base", "upper"], "tempo": 0.75, "softness": 0.85}}`.
- **"base only" / "deepthroat"**: `{{"sp": 55, "dp": 88, "rng": 24, "zone": "base", "pattern": "pulse"}}`.
- **"base half"**: `{{"zone": "base", "rng": 50}}`.
- **"suck the whole thing" / "full strokes"**: `{{"sp": 50, "dp": 50, "rng": 95, "zone": "full", "pattern": "stroke"}}`.
- **"go deeper"**: Increase the `dp` by 15-20 from the last position. Keep `sp` and `rng` similar to the last move.
- **"faster" / "harder"**: Increase `sp` by 20-25. Keep `dp` and `rng` similar to the last move.
- **"slower" / "gentler"**: Decrease `sp` by 20-25. Keep `dp` and `rng` similar to the last move.
- **"short strokes"**: `rng` should be low (15-30). Infer a sensible `sp` and `dp`.

If the user gives a vague command, vary the movement by changing zone, pattern, speed, and stroke length. Do not keep sending the same move unless the user asked for steady repetition.
"""
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
