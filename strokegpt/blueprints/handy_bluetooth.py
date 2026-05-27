from flask import Blueprint, jsonify, request


handy_bluetooth_blueprint = Blueprint("handy_bluetooth", __name__)


def _web():
    from .. import web

    return web


def _request_json():
    return request.get_json(silent=True) or {}


def _client_id_from_request(data=None):
    data = data if isinstance(data, dict) else {}
    return str(data.get("client_id") or request.args.get("client_id") or "").strip()


@handy_bluetooth_blueprint.route("/handy_bluetooth/status", methods=["GET", "POST"])
def handy_bluetooth_status_route():
    web = _web()
    if request.method == "POST":
        data = _request_json()
        client_id = _client_id_from_request(data)
        snapshot = web.handy_bluetooth_bridge.update_client(
            client_id,
            connected=data.get("connected"),
            status=str(data.get("status") or ""),
            message=str(data.get("message") or ""),
            device_name=str(data.get("device_name") or ""),
            error=str(data.get("error") or ""),
        )
        web.handy.apply_bluetooth_status({
            "connected": snapshot.get("connected"),
            "message": snapshot.get("message"),
            "device_name": snapshot.get("device_name"),
            "event_type": data.get("event_type") or "bluetooth_status",
            "hsp_state": data.get("hsp_state"),
        })
    else:
        snapshot = web.handy_bluetooth_bridge.snapshot()
    return jsonify({
        "status": "success",
        "handy_transport": web.settings.handy_transport,
        "runtime_transport": web.handy.transport_mode,
        "bluetooth": snapshot,
    })


@handy_bluetooth_blueprint.route("/handy_bluetooth/connect", methods=["POST"])
def handy_bluetooth_connect_route():
    web = _web()
    data = _request_json()
    client_id = _client_id_from_request(data)
    if not client_id:
        return jsonify({"status": "error", "message": "Missing browser client id."}), 400
    snapshot = web.handy_bluetooth_bridge.connect_client(
        client_id,
        device_name=str(data.get("device_name") or ""),
        message=str(data.get("message") or "Handy Bluetooth connected."),
    )
    web.settings.handy_transport = web.settings._normalize_handy_transport("browser_bluetooth")
    web.settings.handy_firmware_version = web.settings._normalize_handy_firmware_version("fw4")
    web.settings.save()
    web.handy.set_firmware_version(web.settings.handy_firmware_version)
    web.handy.set_transport_mode(web.settings.handy_transport)
    web.handy.apply_bluetooth_status({
        "connected": True,
        "message": snapshot.get("message"),
        "device_name": snapshot.get("device_name"),
        "event_type": "bluetooth_connected",
        "hsp_state": data.get("hsp_state"),
    })
    return jsonify({
        "status": "success",
        "handy_transport": web.settings.handy_transport,
        "handy_firmware_version": web.settings.handy_firmware_version,
        "bluetooth": snapshot,
        "message": snapshot.get("message") or "Handy Bluetooth connected.",
    })


@handy_bluetooth_blueprint.route("/handy_bluetooth/disconnect", methods=["POST"])
def handy_bluetooth_disconnect_route():
    web = _web()
    data = _request_json()
    client_id = _client_id_from_request(data)
    snapshot = web.handy_bluetooth_bridge.disconnect_client(
        client_id,
        message=str(data.get("message") or "Handy Bluetooth disconnected."),
    )
    web.handy.apply_bluetooth_status({
        "connected": False,
        "message": snapshot.get("message"),
        "device_name": snapshot.get("device_name"),
        "event_type": "bluetooth_disconnected",
    })
    return jsonify({
        "status": "success",
        "handy_transport": web.settings.handy_transport,
        "bluetooth": snapshot,
        "message": snapshot.get("message") or "Handy Bluetooth disconnected.",
    })


@handy_bluetooth_blueprint.route("/handy_bluetooth/commands")
def handy_bluetooth_commands_route():
    web = _web()
    client_id = _client_id_from_request()
    if not client_id:
        return jsonify({"status": "error", "message": "Missing browser client id.", "commands": []}), 400
    try:
        wait_seconds = max(0.0, min(10.0, float(request.args.get("wait", "4"))))
    except (TypeError, ValueError):
        wait_seconds = 4.0
    commands = web.handy_bluetooth_bridge.next_commands(client_id, wait_seconds=wait_seconds)
    return jsonify({"status": "success", "commands": commands})


@handy_bluetooth_blueprint.route("/handy_bluetooth/ack", methods=["POST"])
def handy_bluetooth_ack_route():
    web = _web()
    data = _request_json()
    client_id = _client_id_from_request(data)
    if not client_id:
        return jsonify({"status": "error", "message": "Missing browser client id."}), 400
    response = data.get("response") if isinstance(data.get("response"), dict) else {}
    snapshot = web.handy_bluetooth_bridge.acknowledge(
        client_id,
        data.get("id"),
        ok=bool(data.get("ok")),
        elapsed_ms=data.get("elapsed_ms"),
        error=str(data.get("error") or ""),
        response=response,
    )
    hsp_state = response.get("hsp_state") if isinstance(response, dict) else None
    web.handy.apply_bluetooth_status({
        "connected": snapshot.get("connected"),
        "message": snapshot.get("message"),
        "device_name": snapshot.get("device_name"),
        "event_type": "bluetooth_command_ack",
        "hsp_state": hsp_state,
    })
    return jsonify({"status": "success", "bluetooth": snapshot})
