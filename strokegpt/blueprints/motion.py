import io
import json
import threading

from flask import Blueprint, jsonify, request, send_file
from werkzeug.utils import secure_filename

from .. import payloads


motion_blueprint = Blueprint("motion", __name__)


def _web():
    from .. import web

    return web


def _pattern_summary(web, record, *, include_actions=False):
    return payloads.motion_pattern_summary(
        record,
        web.settings.motion_pattern_weights,
        include_actions=include_actions,
    )


@motion_blueprint.route('/motion_patterns')
def motion_patterns_route():
    web = _web()
    return jsonify(web._motion_pattern_catalog_payload())


@motion_blueprint.route('/motion_preferences')
def motion_preferences_route():
    web = _web()
    payload = web._motion_preference_payload()
    payload["status"] = "success"
    return jsonify(payload)


@motion_blueprint.route('/motion_preferences/reset', methods=['POST'])
def reset_motion_preferences_route():
    web = _web()
    web.settings.motion_pattern_feedback = {}
    web.settings.motion_pattern_weights = {}
    web.settings.save()
    payload = web._motion_preference_payload()
    payload["status"] = "success"
    return jsonify(payload)


@motion_blueprint.route('/motion_feedback_options', methods=['POST'])
def set_motion_feedback_options_route():
    web = _web()
    data = web._request_json()
    web.settings.motion_feedback_auto_disable = bool(data.get("auto_disable", False))
    web.settings.save()
    return jsonify({
        "status": "success",
        "motion_feedback_auto_disable": web.settings.motion_feedback_auto_disable,
        "motion_patterns": web._motion_pattern_catalog_payload(),
        "motion_preferences": web._motion_preference_payload(),
    })


@motion_blueprint.route('/motion_patterns/<pattern_id>')
def motion_pattern_detail_route(pattern_id):
    web = _web()
    record = web._motion_pattern_record(pattern_id)
    if not record:
        return jsonify({"status": "error", "message": "Pattern not found."}), 404
    return jsonify({"status": "success", "pattern": _pattern_summary(web, record, include_actions=True)})


@motion_blueprint.route('/motion_patterns/<pattern_id>/export')
def export_motion_pattern_route(pattern_id):
    web = _web()
    record = web._motion_pattern_record(pattern_id)
    if not record:
        return jsonify({"status": "error", "message": "Pattern not found."}), 404
    payload = json.dumps(record.to_export_dict(), indent=2).encode("utf-8")
    return send_file(
        io.BytesIO(payload),
        mimetype="application/json",
        as_attachment=True,
        download_name=f"{record.pattern_id}.strokegpt-pattern.json",
    )


@motion_blueprint.route('/import_motion_pattern', methods=['POST'])
def import_motion_pattern_route():
    web = _web()
    try:
        if "pattern" in request.files:
            filename, payload = web._read_uploaded_pattern_payload(request.files["pattern"])
        else:
            payload = web._request_json()
            filename = (
                secure_filename(payload.get("filename") or "pattern.json")
                if isinstance(payload, dict)
                else "pattern.json"
            )
        record = web.motion_pattern_library.import_payload(payload, filename=filename)
    except web.PatternValidationError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return jsonify({"status": "success", "pattern": _pattern_summary(web, record, include_actions=True)})


@motion_blueprint.route('/motion_patterns/save_generated', methods=['POST'])
def save_generated_motion_pattern_route():
    web = _web()
    data = web._request_json()
    payload = data.get("pattern") if isinstance(data.get("pattern"), dict) else {}
    filename_source = (
        data.get("filename")
        or payload.get("id")
        or payload.get("name")
        or "trained-pattern"
    )
    filename = secure_filename(f"{filename_source}.json")
    try:
        record = web.motion_pattern_library.import_payload(
            payload,
            filename=filename,
            source_override="trained",
        )
    except web.PatternValidationError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return jsonify({
        "status": "success",
        "pattern": _pattern_summary(web, record, include_actions=True),
        "motion_patterns": web._motion_pattern_catalog_payload(),
        "motion_preferences": web._motion_preference_payload(),
    })


@motion_blueprint.route('/motion_patterns/<pattern_id>/enabled', methods=['POST'])
def set_motion_pattern_enabled_route(pattern_id):
    web = _web()
    data = web._request_json()
    record = web._motion_pattern_record(pattern_id)
    if not record:
        return jsonify({"status": "error", "message": "Pattern not found."}), 404
    web.settings.motion_pattern_enabled[record.pattern_id] = bool(data.get("enabled", True))
    web.settings.save()
    updated = web._motion_pattern_record(record.pattern_id)
    return jsonify({
        "status": "success",
        "pattern": _pattern_summary(web, updated, include_actions=True),
        "motion_patterns": web._motion_pattern_catalog_payload(),
        "motion_preferences": web._motion_preference_payload(),
    })


@motion_blueprint.route('/motion_patterns/<pattern_id>/weight', methods=['POST'])
def set_motion_pattern_weight_route(pattern_id):
    web = _web()
    data = web._request_json()
    record = web._motion_pattern_record(pattern_id)
    if not record:
        return jsonify({"status": "error", "message": "Pattern not found."}), 404
    if record.source != "fixed":
        return jsonify({"status": "error", "message": "Only fixed patterns have LLM weights."}), 400
    web.settings.motion_pattern_weights[record.pattern_id] = web.clamp_weight(data.get("weight"))
    web.settings.save()
    updated = web._motion_pattern_record(record.pattern_id)
    return jsonify({
        "status": "success",
        "pattern": _pattern_summary(web, updated, include_actions=True),
        "motion_patterns": web._motion_pattern_catalog_payload(),
        "motion_preferences": web._motion_preference_payload(),
    })


@motion_blueprint.route('/motion_patterns/<pattern_id>/feedback/reset', methods=['POST'])
def reset_motion_pattern_feedback_route(pattern_id):
    web = _web()
    record = web._motion_pattern_record(pattern_id)
    if not record:
        return jsonify({"status": "error", "message": "Pattern not found."}), 404
    web.settings.motion_pattern_feedback.pop(record.pattern_id, None)
    if record.source == "fixed":
        web.settings.motion_pattern_weights.pop(record.pattern_id, None)
    updated = web._motion_pattern_record(record.pattern_id)
    web._append_motion_feedback_history(record, "reset", "settings reset", updated)
    web.settings.save()
    return jsonify({
        "status": "success",
        "message": f"Reset feedback for {updated.name}.",
        "pattern": _pattern_summary(web, updated, include_actions=True),
        "motion_patterns": web._motion_pattern_catalog_payload(),
        "motion_preferences": web._motion_preference_payload(),
    })


@motion_blueprint.route('/motion_training/status')
def motion_training_status_route():
    web = _web()
    return jsonify({"status": "success", "motion_training": web._motion_training_snapshot()})


@motion_blueprint.route('/motion_training/start', methods=['POST'])
def start_motion_training_route():
    web = _web()
    data = web._request_json()
    pattern_id = data.get("pattern_id", "")
    record = web._motion_pattern_record(pattern_id)
    if not record:
        return jsonify({"status": "error", "message": "Pattern not found."}), 404
    return web._start_motion_training_record(record, preview=False)


@motion_blueprint.route('/motion_training/preview', methods=['POST'])
def preview_motion_training_route():
    web = _web()
    data = web._request_json()
    try:
        record = web._training_payload_record(data)
    except web.PatternValidationError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return web._start_motion_training_record(record, preview=True)


@motion_blueprint.route('/motion_training/stop', methods=['POST'])
def stop_motion_training_route():
    web = _web()
    snapshot = web._stop_motion_training()
    return jsonify({"status": "stopped", "motion_training": snapshot})


@motion_blueprint.route('/motion_training/<pattern_id>/feedback', methods=['POST'])
def motion_training_feedback_route(pattern_id):
    web = _web()
    data = web._request_json()
    rating = str(data.get("rating", "")).strip().lower()
    if rating not in {"thumbs_up", "neutral", "thumbs_down"}:
        return jsonify({"status": "error", "message": "Feedback must be thumbs_up, neutral, or thumbs_down."}), 400
    result = web._record_motion_pattern_feedback(pattern_id, rating, source="motion training")
    if not result:
        return jsonify({"status": "error", "message": "Pattern not found."}), 404
    updated = result["pattern"]
    suffix = ""
    if result["auto_disabled"]:
        suffix = f" Disabled after {web.THUMBS_DOWN_DISABLE_THRESHOLD} thumbs down ratings."
    web._set_motion_training_state(
        pattern_id=updated.pattern_id,
        pattern_name=updated.name,
        last_feedback=rating,
        message=f"Saved {rating.replace('_', ' ')} feedback for {updated.name}.{suffix}",
        preview=False,
    )
    return jsonify({
        "status": "success",
        "pattern": _pattern_summary(web, updated, include_actions=True),
        "motion_patterns": result["motion_patterns"],
        "motion_preferences": result["motion_preferences"],
        "motion_training": web._motion_training_snapshot(),
        "auto_disabled": result["auto_disabled"],
    })


@motion_blueprint.route('/nudge', methods=['POST'])
def nudge_route():
    web = _web()
    if web.app_state.calibration_pos_mm == 0.0 and (pos := web.handy.get_position_mm()):
        with web.app_state.lock:
            web.app_state.calibration_pos_mm = pos
    direction = web._request_json().get('direction')
    with web.app_state.lock:
        web.app_state.calibration_pos_mm = web.handy.nudge(direction, 0, 100, web.app_state.calibration_pos_mm)
        calibration_pos_mm = web.app_state.calibration_pos_mm
    return jsonify({"status": "ok", "depth_percent": web.handy.mm_to_percent(calibration_pos_mm)})


@motion_blueprint.route('/test_depth_range', methods=['POST'])
def test_depth_range_route():
    web = _web()
    data = web._request_json()
    depth1 = web._request_int(data, 'min_depth', 5)
    depth2 = web._request_int(data, 'max_depth', 100)
    min_depth = max(0, min(100, min(depth1, depth2)))
    max_depth = max(0, min(100, max(depth1, depth2)))
    if not web.app_state.depth_test_lock.acquire(blocking=False):
        return jsonify({"status": "busy", "min_depth": min_depth, "max_depth": max_depth})
    web.motion.stop()

    def run_depth_test():
        try:
            web.handy.test_depth_range(min_depth, max_depth)
        finally:
            web.app_state.depth_test_lock.release()

    threading.Thread(
        target=run_depth_test,
        daemon=True,
    ).start()
    return jsonify({"status": "testing", "min_depth": min_depth, "max_depth": max_depth})


@motion_blueprint.route('/get_status')
def get_status_route():
    web = _web()
    diagnostics = web.handy.diagnostics()
    motion_observability = web.motion.observability_snapshot(diagnostics)
    motion_observability["diagnostics_level"] = web.settings.motion_diagnostics_level
    active_mode = web._active_mode_snapshot()
    return jsonify({
        "mood": web.app_state.current_mood,
        "speed": diagnostics["physical_speed"],
        "relative_speed": diagnostics["relative_speed"],
        "depth": diagnostics["depth"],
        "range": diagnostics["range"],
        "active_mode": active_mode["active_mode"],
        "active_mode_elapsed_seconds": active_mode["active_mode_elapsed_seconds"],
        "active_mode_paused": active_mode["active_mode_paused"],
        "motion_paused": active_mode["motion_paused"],
        "motion_diagnostics_level": web.settings.motion_diagnostics_level,
        "motion_training": web._motion_training_snapshot(),
        "motion_observability": motion_observability,
    })


@motion_blueprint.route('/set_depth_limits', methods=['POST'])
def set_depth_limits_route():
    web = _web()
    data = web._request_json()
    depth1 = web._request_int(data, 'min_depth', 5)
    depth2 = web._request_int(data, 'max_depth', 100)
    web.settings.min_depth = min(depth1, depth2)
    web.settings.max_depth = max(depth1, depth2)
    web.handy.update_settings(web.settings.min_speed, web.settings.max_speed, web.settings.min_depth, web.settings.max_depth)
    web.settings.save()
    return jsonify({"status": "success"})


@motion_blueprint.route('/set_speed_limits', methods=['POST'])
def set_speed_limits_route():
    web = _web()
    data = web._request_json()
    speed1 = web._request_int(data, 'min_speed', 10)
    speed2 = web._request_int(data, 'max_speed', 80)
    web.settings.min_speed = max(0, min(100, min(speed1, speed2)))
    web.settings.max_speed = max(0, min(100, max(speed1, speed2)))
    web.handy.update_settings(web.settings.min_speed, web.settings.max_speed, web.settings.min_depth, web.settings.max_depth)
    web.settings.save()
    return jsonify({
        "status": "success",
        "min_speed": web.settings.min_speed,
        "max_speed": web.settings.max_speed,
    })


@motion_blueprint.route('/set_motion_backend', methods=['POST'])
def set_motion_backend_route():
    web = _web()
    data = web._request_json()
    web.settings.motion_backend = web.settings._normalize_motion_backend(data.get("motion_backend"))
    web.motion.set_backend(web.settings.motion_backend)
    web.settings.save()
    return jsonify({
        "status": "success",
        "motion_backend": web.settings.motion_backend,
    })


@motion_blueprint.route('/set_llm_edge_permissions', methods=['POST'])
def set_llm_edge_permissions_route():
    web = _web()
    data = web._request_json()
    web.settings.allow_llm_edge_in_freestyle = web._request_bool_value(
        data,
        "allow_llm_edge_in_freestyle",
        web.settings.allow_llm_edge_in_freestyle,
    )
    web.settings.allow_llm_edge_in_chat = web._request_bool_value(
        data,
        "allow_llm_edge_in_chat",
        web.settings.allow_llm_edge_in_chat,
    )
    web.settings.save()
    return jsonify({
        "status": "success",
        "allow_llm_edge_in_freestyle": web.settings.allow_llm_edge_in_freestyle,
        "allow_llm_edge_in_chat": web.settings.allow_llm_edge_in_chat,
        "motion_preferences": web._motion_preference_payload(),
    })


@motion_blueprint.route('/like_last_move', methods=['POST'])
def like_last_move_route():
    web = _web()
    last_speed = web.handy.last_relative_speed
    last_depth = web.handy.last_depth_pos
    current_mood = web.app_state.current_mood
    pattern_name = web.llm.name_this_move(last_speed, last_depth, current_mood)
    sp_range = [max(0, last_speed - 5), min(100, last_speed + 5)]
    dp_range = [max(0, last_depth - 5), min(100, last_depth + 5)]
    new_pattern = {
        "name": pattern_name,
        "sp_range": [int(p) for p in sp_range],
        "dp_range": [int(p) for p in dp_range],
        "moods": [current_mood],
        "score": 1,
    }
    web.settings.session_liked_patterns.append(new_pattern)
    result = web._rate_last_live_motion_pattern("thumbs_up", source="chat thumbs up")
    web.add_message_to_queue(f"(I'll remember that you like '{pattern_name}')", add_to_history=False)
    response = {"status": "boosted", "name": pattern_name}
    if result:
        response.update({
            "pattern": _pattern_summary(web, result["pattern"]),
            "motion_patterns": result["motion_patterns"],
            "motion_preferences": result["motion_preferences"],
        })
    return jsonify(response)


@motion_blueprint.route('/dislike_last_move', methods=['POST'])
def dislike_last_move_route():
    web = _web()
    result = web._rate_last_live_motion_pattern("thumbs_down", source="chat thumbs down")
    if not result:
        return jsonify({
            "status": "no_pattern",
            "message": "No fixed motion pattern is active to rate.",
            "motion_preferences": web._motion_preference_payload(),
        })
    pattern = result["pattern"]
    message = f"Saved thumbs down feedback for {pattern.name}."
    if result["auto_disabled"]:
        message += f" Disabled after {web.THUMBS_DOWN_DISABLE_THRESHOLD} thumbs down ratings."
    web.add_message_to_queue(f"({message})", add_to_history=False)
    return jsonify({
        "status": "success",
        "message": message,
        "pattern": _pattern_summary(web, pattern),
        "motion_patterns": result["motion_patterns"],
        "motion_preferences": result["motion_preferences"],
        "auto_disabled": result["auto_disabled"],
    })


@motion_blueprint.route('/motion_feedback/last', methods=['POST'])
def rate_last_motion_pattern_route():
    web = _web()
    data = web._request_json()
    rating = str(data.get("rating", "")).strip().lower()
    result = web._rate_last_live_motion_pattern(rating, source="chat feedback")
    if not result:
        return jsonify({"status": "error", "message": "No fixed motion pattern is active to rate."}), 400
    pattern = result["pattern"]
    return jsonify({
        "status": "success",
        "pattern": _pattern_summary(web, pattern),
        "motion_patterns": result["motion_patterns"],
        "motion_preferences": result["motion_preferences"],
        "auto_disabled": result["auto_disabled"],
    })
