THUMBS_DOWN_DISABLE_THRESHOLD = 3
BASE_PATTERN_WEIGHT = 50
MAX_PATTERN_WEIGHT = 100
MIN_PATTERN_WEIGHT = 0


def clamp_weight(value):
    try:
        value = int(round(float(value)))
    except (TypeError, ValueError):
        value = BASE_PATTERN_WEIGHT
    return max(MIN_PATTERN_WEIGHT, min(MAX_PATTERN_WEIGHT, value))


def feedback_weight(feedback):
    feedback = feedback if isinstance(feedback, dict) else {}
    thumbs_up = int(feedback.get("thumbs_up") or 0)
    neutral = int(feedback.get("neutral") or 0)
    thumbs_down = int(feedback.get("thumbs_down") or 0)
    if thumbs_down >= THUMBS_DOWN_DISABLE_THRESHOLD:
        return 0
    return clamp_weight(BASE_PATTERN_WEIGHT + (thumbs_up * 12) + (neutral * 2) - (thumbs_down * 18))


def adjust_weight_for_feedback(current_weight, rating, feedback):
    if rating == "thumbs_up":
        return clamp_weight(current_weight + 10)
    if rating == "thumbs_down":
        return 0 if should_auto_disable(feedback) else clamp_weight(current_weight - 20)
    return clamp_weight(current_weight)


def should_auto_disable(feedback):
    feedback = feedback if isinstance(feedback, dict) else {}
    return int(feedback.get("thumbs_down") or 0) >= THUMBS_DOWN_DISABLE_THRESHOLD


def enrich_catalog(catalog, weight_overrides=None):
    weight_overrides = weight_overrides or {}
    patterns = []
    for pattern in catalog.get("patterns", []) if isinstance(catalog, dict) else []:
        enriched = dict(pattern)
        feedback = enriched.get("feedback") if isinstance(enriched.get("feedback"), dict) else {}
        if enriched.get("source") == "fixed":
            if enriched.get("id") in weight_overrides:
                weight = clamp_weight(weight_overrides[enriched["id"]])
            elif "weight" in enriched:
                weight = clamp_weight(enriched.get("weight"))
            else:
                weight = feedback_weight(feedback)
            enriched["weight"] = weight
            enriched["llm_visible"] = bool(enriched.get("enabled", True)) and weight > 0
        else:
            enriched["llm_visible"] = False
        patterns.append(enriched)
    updated = dict(catalog or {})
    updated["patterns"] = patterns
    return updated


def build_motion_preference_payload(catalog):
    enriched = enrich_catalog(catalog)
    fixed_patterns = [
        pattern
        for pattern in enriched.get("patterns", [])
        if pattern.get("source") == "fixed"
    ]
    enabled_fixed = sorted(
        (pattern for pattern in fixed_patterns if pattern.get("enabled", True)),
        key=lambda pattern: (-int(pattern.get("weight") or 0), str(pattern.get("id") or "")),
    )
    disabled_fixed = sorted(
        (pattern for pattern in fixed_patterns if not pattern.get("enabled", True)),
        key=lambda pattern: str(pattern.get("id") or ""),
    )
    llm_visible_fixed = sorted(
        (pattern for pattern in fixed_patterns if pattern.get("llm_visible")),
        key=lambda pattern: (-int(pattern.get("weight") or 0), str(pattern.get("id") or "")),
    )
    return {
        "enabled_fixed_patterns": enabled_fixed,
        "disabled_fixed_patterns": disabled_fixed,
        "llm_visible_fixed_patterns": llm_visible_fixed,
        "summary": format_motion_preferences_for_ui(enabled_fixed, disabled_fixed),
        "prompt": format_motion_preferences_for_prompt(llm_visible_fixed),
    }


def format_motion_preferences_for_ui(enabled_fixed, disabled_fixed):
    if not enabled_fixed and not disabled_fixed:
        return "No fixed motion pattern weights are available."
    lines = []
    if enabled_fixed:
        lines.append(
            "Enabled fixed patterns: "
            + ", ".join(f"{pattern['id']}={pattern.get('weight', 0)}" for pattern in enabled_fixed)
            + "."
        )
    if disabled_fixed:
        lines.append(
            "Disabled fixed patterns: "
            + ", ".join(str(pattern.get("id") or "") for pattern in disabled_fixed[:8])
            + "."
        )
    return " ".join(line for line in lines if line)


def format_motion_preferences_for_prompt(enabled_fixed):
    lines = [
        "Available fixed move.pattern weights from 0-100. Higher weight means prefer that pattern when it fits the user's request. Only choose listed pattern names; patterns not listed are unavailable.",
    ]
    if enabled_fixed:
        lines.append(", ".join(f"{pattern.get('id')}={pattern.get('weight', 0)}" for pattern in enabled_fixed))
    else:
        lines.append("- No fixed patterns are currently enabled; use numeric sp/dp/rng or anchor_loop instead.")
    return "\n".join(lines)
