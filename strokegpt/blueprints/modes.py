from flask import Blueprint, jsonify


modes_blueprint = Blueprint("modes", __name__)


def _web():
    from .. import web

    return web


@modes_blueprint.route('/signal_edge', methods=['POST'])
def signal_edge_route():
    web = _web()
    active_task = web.app_state.auto_mode_active_task
    if active_task and active_task.name in {'edging', 'milking', 'freestyle'}:
        web.app_state.user_signal_event.set()
        web.app_state.mode_message_event.set()
        return jsonify({"status": "signaled", "mode": active_task.name})
    return jsonify({"status": "ignored", "message": "Edge, milking, or Freestyle mode not active."}), 400


@modes_blueprint.route('/toggle_motion_pause', methods=['POST'])
def toggle_motion_pause_route():
    web = _web()
    data = web._request_json()
    action = str(data.get("action") or "toggle").strip().lower()
    if action in {"pause", "paused"}:
        paused = True
    elif action in {"resume", "play", "unpause", "running"}:
        paused = False
    else:
        paused = not bool(web.app_state.motion_pause_active or getattr(web.motion, "is_paused", lambda: False)())
    snapshot = web._set_motion_paused(paused)
    return jsonify({
        "status": "success",
        "paused": snapshot["motion_paused"],
        "active_mode": snapshot["active_mode"],
        "active_mode_paused": snapshot["active_mode_paused"],
        "active_mode_elapsed_seconds": snapshot["active_mode_elapsed_seconds"],
    })


@modes_blueprint.route('/set_mode_timings', methods=['POST'])
def set_mode_timings_route():
    web = _web()
    data = web._request_json()
    web.settings.auto_min_time, web.settings.auto_max_time = web._timing_pair(data, 'auto_min', 'auto_max', 4.0, 7.0)
    web.settings.edging_min_time, web.settings.edging_max_time = web._timing_pair(data, 'edging_min', 'edging_max', 5.0, 8.0)
    web.settings.milking_min_time, web.settings.milking_max_time = web._timing_pair(data, 'milking_min', 'milking_max', 2.5, 4.5)
    web.settings.save()
    return jsonify({
        "status": "success",
        "timings": {
            "auto_min": web.settings.auto_min_time,
            "auto_max": web.settings.auto_max_time,
            "edging_min": web.settings.edging_min_time,
            "edging_max": web.settings.edging_max_time,
            "milking_min": web.settings.milking_min_time,
            "milking_max": web.settings.milking_max_time,
        },
    })


@modes_blueprint.route('/start_edging_mode', methods=['POST'])
def start_edging_route():
    web = _web()
    web.start_background_mode(web.edging_mode_logic, "Let's play an edging game...", mode_name='edging')
    return jsonify({"status": "edging_started"})


@modes_blueprint.route('/start_milking_mode', methods=['POST'])
def start_milking_route():
    web = _web()
    web.start_background_mode(web.milking_mode_logic, "You're so close... I'm taking over completely now.", mode_name='milking')
    return jsonify({"status": "milking_started"})


@modes_blueprint.route('/start_freestyle_mode', methods=['POST'])
def start_freestyle_route():
    web = _web()
    web.start_background_mode(web.freestyle_mode_logic, "Starting adaptive Freestyle.", mode_name='freestyle')
    return jsonify({"status": "freestyle_started"})


@modes_blueprint.route('/stop_auto_mode', methods=['POST'])
def stop_auto_route():
    web = _web()
    web._clear_motion_pause_state()
    active_task = web.app_state.auto_mode_active_task
    if active_task:
        active_task.stop()
    return jsonify({"status": "auto_mode_stopped"})
