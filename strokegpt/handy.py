import json
import os
import re
import sys
import threading
import time
from collections import deque
from urllib.parse import urlencode
import requests

from .settings import DEFAULT_HANDY_API_V3_APPLICATION_ID

_HTTP_SESSION_LOCK = threading.Lock()
_HTTP_SESSION = None


class _ModuleHTTPFallback:
    """Session-shaped proxy for environments without ``requests.Session``.

    Some dependency-free test stubs register a minimal ``requests`` module.
    Production always has the real library, so this proxy only exists to
    keep import-order-sensitive test environments working; it simply
    forwards to the module-level functions without pooling.
    """

    def put(self, url, **kwargs):
        return requests.put(url, **kwargs)

    def get(self, url, **kwargs):
        return requests.get(url, **kwargs)


def _http_retry_config():
    """Connection-level retry policy for pooled keep-alive sockets.

    A reused socket can be closed by the server or a NAT between commands;
    without retries that surfaces as a one-off command failure, and a single
    failed ``hsp/add`` kills the continuous stream by design. Connect errors
    and one read retry are safe here: the Handy command PUTs are idempotent
    (re-sending the same point buffer or mode command yields the same device
    state).
    """
    try:
        from urllib3.util.retry import Retry
    except Exception:
        return None
    try:
        return Retry(
            total=2,
            connect=2,
            read=1,
            status=0,
            backoff_factor=0.15,
            allowed_methods=None,
        )
    except TypeError:
        # Older urllib3 used method_whitelist instead of allowed_methods.
        return Retry(total=2, connect=2, read=1, backoff_factor=0.15)


def _http_session():
    """Shared pooled HTTP session for Handy REST traffic.

    Plain ``requests.put``/``requests.get`` opened a fresh TCP connection and
    paid a full TLS handshake to the Handy cloud on every command. With the
    HSP state poller (4 Hz), the SSE listener, and motion-critical
    ``hsp/add`` appends all issuing commands concurrently, real-device
    command latency compounded to 1-2+ seconds per command and starved
    timed HSP streams. A pooled keep-alive session makes a command cost one
    round trip after the first connection.
    """
    global _HTTP_SESSION
    with _HTTP_SESSION_LOCK:
        if _HTTP_SESSION is None:
            session_factory = getattr(requests, "Session", None)
            if session_factory is None:
                _HTTP_SESSION = _ModuleHTTPFallback()
            else:
                session = session_factory()
                adapters = getattr(requests, "adapters", None)
                adapter_factory = getattr(adapters, "HTTPAdapter", None) if adapters else None
                if callable(adapter_factory):
                    retry_config = _http_retry_config()
                    adapter_kwargs = {"pool_connections": 4, "pool_maxsize": 8}
                    if retry_config is not None:
                        adapter_kwargs["max_retries"] = retry_config
                    try:
                        adapter = adapter_factory(**adapter_kwargs)
                    except TypeError:
                        adapter = adapter_factory(pool_connections=4, pool_maxsize=8)
                    session.mount("https://", adapter)
                    session.mount("http://", adapter)
                _HTTP_SESSION = session
    return _HTTP_SESSION


def _reset_http_session():
    """Discard the pooled session so the next command builds a fresh one.

    A shared session means a poisoned connection pool can persist across
    commands -- the failure mode where every Handy command starts failing
    and motion stops outright with no recovery, because the chat keepalive's
    restart attempts fail through the same poisoned pool. Per-command fresh
    connections never had that persistence, so the pooled variant heals
    itself: any transport-level exception drops the pool and the next
    command reconnects from scratch.
    """
    global _HTTP_SESSION
    with _HTTP_SESSION_LOCK:
        session = _HTTP_SESSION
        _HTTP_SESSION = None
    if session is not None:
        try:
            close = getattr(session, "close", None)
            if callable(close):
                close()
        except Exception:
            pass


def _session_put(url, **kwargs):
    # Patchable seam for tests; production traffic goes through the pooled
    # keep-alive session above. Transport exceptions reset the pool so a
    # poisoned connection cannot persist across commands.
    try:
        return _http_session().put(url, **kwargs)
    except Exception:
        _reset_http_session()
        raise


def _session_get(url, **kwargs):
    # Patchable seam for tests; production traffic goes through the pooled
    # keep-alive session above. Transport exceptions reset the pool so a
    # poisoned connection cannot persist across commands.
    try:
        return _http_session().get(url, **kwargs)
    except Exception:
        _reset_http_session()
        raise


MODE_HAMP = 0
MODE_HDSP = 2
MODE_HSP = 4
HANDY_API_V2_BASE_URL = "https://www.handyfeeling.com/api/handy/v2/"
HANDY_API_V3_BASE_URL = "https://www.handyfeeling.com/api/handy-rest/v3/"
HANDY_TRANSPORT_REST = "rest"
HANDY_TRANSPORT_BROWSER_BLUETOOTH = "browser_bluetooth"
HANDY_TRANSPORTS = {HANDY_TRANSPORT_REST, HANDY_TRANSPORT_BROWSER_BLUETOOTH}
HANDY_API_V3_CONNECTION_KEY_RE = re.compile(r"^[A-Za-z0-9]{1,128}$")
HANDY_COMMAND_HISTORY_LIMIT = 60
HANDY_COMMAND_POINTS_PREVIEW = 12
HSP_POINT_MAX = 100
HSP_SERVER_TIME_SYNC_TTL_SECONDS = 300.0
HSP_STREAM_ID_MAX = 4294967295
HSP_STALE_CLOCK_TOLERANCE_MS = 500
HSP_THRESHOLD_UPDATE_MIN_INTERVAL_SECONDS = 8.0
HSP_STATE_REFRESH_MAX_AGE_SECONDS = 0.25
HSP_STATE_REFRESH_MIN_INTERVAL_SECONDS = 0.25
HSP_STATE_REFRESH_SSE_BACKOFF_SECONDS = 1.0
HSP_STATE_REFRESH_FAILURE_BACKOFF_SECONDS = 2.0
HSP_STATE_REFRESH_TIMEOUT_SECONDS = 0.5
HSP_STATE_SSE_CONNECT_TIMEOUT_SECONDS = 5.0
HSP_STATE_SSE_READ_TIMEOUT_SECONDS = 45.0
HSP_STATE_SSE_RECONNECT_SECONDS = 0.75
HSP_STATE_SSE_FAILURE_BACKOFF_SECONDS = 3.0
HSP_STATE_SSE_EVENTS = (
    "device_status",
    "device_connected",
    "device_disconnected",
    "device_error",
    "mode_changed",
    "hamp_state_changed",
    "hdsp_state_changed",
    "hsp_state_changed",
    "hsp_threshold_reached",
    "hsp_starving",
    "hsp_looping",
    "hsp_paused_on_starving",
    "hsp_resumed_on_not_starving",
    "stroke_changed",
    "slider_blocked",
    "slider_unblocked",
    "temp_high",
    "temp_ok",
    "low_memory_error",
    "low_memory_warning",
)
HSP_STATE_SSE_STATE_EVENTS = frozenset(
    (
        "hsp_state_changed",
        "hsp_threshold_reached",
        "hsp_starving",
        "hsp_looping",
        "hsp_paused_on_starving",
        "hsp_resumed_on_not_starving",
        "hsp_resumed_on_non_starving",
    )
)
HSP_STATE_STARVING_EVENTS = frozenset(("hsp_starving", "hsp_paused_on_starving"))
HANDY_SSE_RECENT_EVENTS_LIMIT = 20
HANDY_SSE_SECRET_KEYS = frozenset(
    (
        "apikey",
        "api_key",
        "authorization",
        "ck",
        "connection_key",
        "connectionkey",
        "token",
        "x-api-key",
        "xapikey",
        "x-connection-key",
        "xconnectionkey",
    )
)
# Handy position transports use absolute velocity/duration math. The app's
# saved speed limits remain 0-100 percent-style controls, so timed position
# and HSP guards convert those percentages onto this mm/s device scale.
HANDY_MAX_ABSOLUTE_VELOCITY_MM_S = 400.0

class HandyController:
    def __init__(
        self,
        handy_key="",
        base_url=HANDY_API_V2_BASE_URL,
        *,
        api_v3_key=None,
        api_v3_base_url=HANDY_API_V3_BASE_URL,
        firmware_version="fw4",
        transport_mode=HANDY_TRANSPORT_REST,
        bluetooth_bridge=None,
    ):
        self.handy_key = handy_key
        self.base_url = self._normalize_base_url(base_url)
        self.firmware_version = self._normalize_firmware_version(firmware_version)
        env_api_v3_application_id = (
            os.getenv("STROKEGPT_HANDY_API_V3_APPLICATION_ID", "")
            or os.getenv("STROKEGPT_HANDY_API_KEY", "")
        )
        self.api_v3_key = (
            str(api_v3_key if api_v3_key is not None else env_api_v3_application_id or "").strip()
            or DEFAULT_HANDY_API_V3_APPLICATION_ID
        )
        self.api_v3_base_url = self._normalize_base_url(
            os.getenv("STROKEGPT_HANDY_API_V3_BASE_URL", api_v3_base_url) or HANDY_API_V3_BASE_URL
        )
        self.transport_mode = self._normalize_transport_mode(transport_mode)
        self.bluetooth_bridge = bluetooth_bridge
        self.last_stroke_speed = 0
        self.last_depth_pos = 50
        self.last_stroke_range = 50
        self.last_relative_speed = 50
        self.min_user_speed = 10
        self.max_user_speed = 80
        self.max_handy_depth = 100
        self.min_handy_depth = 0
        self.FULL_TRAVEL_MM = 110.0
        self._current_mode = None
        self._hamp_started = False
        self._hsp_streaming = False
        self._last_hsp_threshold_update_at = 0.0
        self._last_hsp_threshold_value = None
        self._last_slide_bounds = None
        self._last_v3_stroke_bounds = None
        self._last_velocity = None
        self._last_command_result = None
        self._command_history = deque(maxlen=HANDY_COMMAND_HISTORY_LIMIT)
        self._api_v3_auth_failed = False
        self._api_v3_auth_error = ""
        self._api_v3_auth_failed_path = ""
        self._hsp_stream_id = 0
        self._last_hsp_state = None
        self._last_hsp_state_observed_at = None
        self._last_hsp_state_source = ""
        self._hsp_state_cache_lock = threading.Lock()
        self._last_hsp_state_refresh_attempt_at = 0.0
        self._last_hsp_state_refresh_attempt_wall_at = None
        self._last_hsp_state_refresh_success_at = None
        self._last_hsp_state_refresh_error = ""
        self._last_hsp_state_refresh_failures = 0
        self._hsp_state_refresh_thread = None
        self._hsp_state_refresh_thread_lock = threading.Lock()
        self._hsp_state_sse_thread = None
        self._hsp_state_sse_thread_lock = threading.Lock()
        self._hsp_state_sse_generation = 0
        self._hsp_state_sse_response = None
        self._last_hsp_state_sse_attempt_at = None
        self._last_hsp_state_sse_connected_at = None
        self._last_hsp_state_sse_event_at = None
        self._last_hsp_state_sse_event_type = ""
        self._last_hsp_state_sse_error = ""
        self._last_hsp_state_sse_failures = 0
        self._last_hsp_state_sse_events = 0
        self._last_handy_sse_event = None
        self._last_handy_sse_event_at = None
        self._handy_sse_recent_events = deque(maxlen=HANDY_SSE_RECENT_EVENTS_LIMIT)
        self._device_connection_status = "unknown"
        self._device_connection_message = ""
        self._device_connection_observed_at = None
        self._device_connection_event_type = ""
        self._server_time_offset_ms = None
        self._server_time_synced_at = 0.0
        self._server_time_refresh_thread = None
        self._server_time_refresh_thread_lock = threading.Lock()

    def _normalize_base_url(self, value):
        cleaned = str(value or "").strip() or HANDY_API_V2_BASE_URL
        return cleaned if cleaned.endswith("/") else f"{cleaned}/"

    def _normalize_firmware_version(self, value):
        cleaned = str(value or "").strip().lower().replace("-", "").replace("_", "")
        if cleaned in {"3", "v3", "fw3", "firmware3", "firmwarev3"}:
            return "fw3"
        if cleaned in {"4", "v4", "fw4", "firmware4", "firmwarev4"}:
            return "fw4"
        return "fw4"

    def _normalize_transport_mode(self, value):
        cleaned = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        if cleaned in {"bluetooth", "ble", "browser_ble", "web_bluetooth", "local_bluetooth"}:
            return HANDY_TRANSPORT_BROWSER_BLUETOOTH
        if cleaned in HANDY_TRANSPORTS:
            return cleaned
        return HANDY_TRANSPORT_REST

    def set_transport_mode(self, mode):
        normalized = self._normalize_transport_mode(mode)
        if normalized != self.transport_mode:
            self._current_mode = None
            self._hamp_started = False
            self._hsp_streaming = False
            self._hsp_stream_id = 0
            self._clear_hsp_state_cache()
            self._server_time_offset_ms = None
            self._server_time_synced_at = 0.0
            self._reset_motion_cache()
        self.transport_mode = normalized

    def set_bluetooth_bridge(self, bridge):
        self.bluetooth_bridge = bridge

    def _using_browser_bluetooth(self):
        return self.transport_mode == HANDY_TRANSPORT_BROWSER_BLUETOOTH

    def _bluetooth_ready(self):
        bridge = self.bluetooth_bridge
        return bool(bridge is not None and getattr(bridge, "is_ready", lambda: False)())

    def _has_control_connection(self):
        if self._using_browser_bluetooth():
            return self._bluetooth_ready()
        return bool(self.handy_key)

    def _control_connection_error(self):
        if self._using_browser_bluetooth():
            return "Handy Bluetooth is not connected in the active browser"
        return "missing Handy key"

    def set_api_key(self, key):
        cleaned = str(key or "").strip()
        if cleaned != self.handy_key or self._api_v3_auth_failed:
            self._current_mode = None
            self._hamp_started = False
            self._hsp_streaming = False
            self._api_v3_auth_failed = False
            self._api_v3_auth_error = ""
            self._api_v3_auth_failed_path = ""
            self._hsp_stream_id = 0
            self._clear_hsp_state_cache()
            self._server_time_offset_ms = None
            self._server_time_synced_at = 0.0
            self._reset_motion_cache()
        self.handy_key = cleaned

    def set_handy_api_key(self, key):
        # Compatibility shim - do not extend. The persisted setting name says
        # "key", but API v3 HSP uses a public Application ID in X-Api-Key.
        cleaned = str(key or "").strip() or DEFAULT_HANDY_API_V3_APPLICATION_ID
        if cleaned != self.api_v3_key or self._api_v3_auth_failed:
            self._current_mode = None
            self._hamp_started = False
            self._hsp_streaming = False
            self._api_v3_auth_failed = False
            self._api_v3_auth_error = ""
            self._api_v3_auth_failed_path = ""
            self._hsp_stream_id = 0
            self._clear_hsp_state_cache()
            self._server_time_offset_ms = None
            self._server_time_synced_at = 0.0
            self._reset_motion_cache()
        self.api_v3_key = cleaned

    def set_firmware_version(self, version):
        normalized = self._normalize_firmware_version(version)
        if normalized != self.firmware_version:
            self._current_mode = None
            self._hamp_started = False
            self._hsp_streaming = False
            self._api_v3_auth_failed = False
            self._api_v3_auth_error = ""
            self._api_v3_auth_failed_path = ""
            self._hsp_stream_id = 0
            self._clear_hsp_state_cache()
            self._server_time_offset_ms = None
            self._server_time_synced_at = 0.0
            self._reset_motion_cache()
        self.firmware_version = normalized

    def update_settings(self, min_speed, max_speed, min_depth, max_depth):
        self.min_user_speed = min_speed
        self.max_user_speed = max_speed
        self.min_handy_depth = min_depth
        self.max_handy_depth = max_depth
        self._reset_motion_cache()

    def _reset_motion_cache(self):
        self._last_slide_bounds = None
        self._last_v3_stroke_bounds = None
        self._last_velocity = None

    def _safe_points_preview(self, points):
        preview = []
        for point in points[:HANDY_COMMAND_POINTS_PREVIEW]:
            if not isinstance(point, dict):
                continue
            safe_point = {}
            for key in ("t", "x", "at", "pos"):
                if key in point:
                    safe_point[key] = point[key]
            if safe_point:
                preview.append(safe_point)
        return preview

    def _safe_points_tail_preview(self, points):
        tail = []
        for point in points[-3:]:
            if not isinstance(point, dict):
                continue
            safe_point = {}
            for key in ("t", "x", "at", "pos"):
                if key in point:
                    safe_point[key] = point[key]
            if safe_point:
                tail.append(safe_point)
        return tail

    def _safe_command_body(self, body):
        if not isinstance(body, dict):
            return {}
        result = {}
        for key in (
            "mode",
            "min",
            "max",
            "position",
            "velocity",
            "duration",
            "duration_ms",
            "stopOnTarget",
            "xa",
            "va",
            "vp",
            "xp",
            "t",
            "stop_on_target",
            "immediate_rsp",
            "start_time",
            "server_time",
            "playback_rate",
            "pause_on_starving",
            "loop",
            "stream_id",
            "flush",
            "tail_point_stream_index",
            "tail_point_threshold",
            "current_time",
            "filter",
        ):
            if key in body:
                result[key] = body[key]
        if "points" in body and isinstance(body["points"], list):
            result["points"] = len(body["points"])
            result["points_preview"] = self._safe_points_preview(body["points"])
            if len(body["points"]) > HANDY_COMMAND_POINTS_PREVIEW:
                result["points_tail_preview"] = self._safe_points_tail_preview(body["points"])
                result["points_truncated"] = True
        if "add" in body and isinstance(body["add"], dict):
            add = body["add"]
            safe_add = {}
            if "points" in add and isinstance(add["points"], list):
                safe_add["points"] = len(add["points"])
                safe_add["points_preview"] = self._safe_points_preview(add["points"])
                if len(add["points"]) > HANDY_COMMAND_POINTS_PREVIEW:
                    safe_add["points_tail_preview"] = self._safe_points_tail_preview(add["points"])
                    safe_add["points_truncated"] = True
            for key in ("flush", "tail_point_stream_index", "tail_point_threshold"):
                if key in add:
                    safe_add[key] = add[key]
            if safe_add:
                result["add"] = safe_add
        return result

    def _payload_candidates(self, payload):
        if not isinstance(payload, dict):
            return []
        candidates = []
        seen = set()

        def add_candidate(value, depth=0):
            if not isinstance(value, dict):
                return
            marker = id(value)
            if marker in seen:
                return
            seen.add(marker)
            candidates.append(value)
            for response_key in (
                "responseHspSetup",
                "responseHspAdd",
                "responseHspFlush",
                "responseHspPlay",
                "responseHspStop",
                "responseHspPause",
                "responseHspResume",
                "responseHspStateGet",
            ):
                response = value.get(response_key)
                if isinstance(response, dict):
                    candidates.append(response)
                    state = response.get("state")
                    if isinstance(state, dict):
                        candidates.append(state)
            if depth >= 3:
                return
            for nested_key in ("result", "data", "state", "hsp_state", "hspState"):
                nested = value.get(nested_key)
                if isinstance(nested, dict):
                    add_candidate(nested, depth + 1)

        for key in ("result", "data", "state", "hsp_state", "hspState"):
            add_candidate(payload.get(key))
        add_candidate(payload)
        return candidates

    def _safe_hsp_value(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            if isinstance(value, float) and not value.is_integer():
                return round(value, 3)
            return int(value)
        if isinstance(value, str):
            return value.strip()[:80]
        return None

    def _read_hsp_state_value(self, payload, *keys):
        if not isinstance(payload, dict):
            return None
        for key in keys:
            if key in payload:
                return self._safe_hsp_value(payload[key])
        return None

    def _extract_hsp_state(self, payload):
        field_map = (
            ("play_state", ("play_state", "playState")),
            ("current_time_ms", ("current_time", "currentTime", "current_time_ms", "currentTimeMs")),
            ("first_point_time_ms", ("first_point_time", "firstPointTime", "first_point_time_ms", "firstPointTimeMs")),
            ("last_point_time_ms", ("last_point_time", "lastPointTime", "last_point_time_ms", "lastPointTimeMs")),
            ("points", ("points", "point_count", "pointCount")),
            ("max_points", ("max_points", "maxPoints")),
            ("current_point", ("current_point", "currentPoint")),
            ("stream_id", ("stream_id", "streamId")),
            (
                "tail_point_stream_index",
                ("tail_point_stream_index", "tailPointStreamIndex"),
            ),
            (
                "tail_point_stream_index_threshold",
                (
                    "tail_point_stream_index_threshold",
                    "tailPointStreamIndexThreshold",
                    "tail_point_threshold",
                    "tailPointThreshold",
                ),
            ),
            ("pause_on_starving", ("pause_on_starving", "pauseOnStarving")),
            ("playback_rate", ("playback_rate", "playbackRate")),
        )
        for candidate in self._payload_candidates(payload):
            state = {}
            for normalized, keys in field_map:
                value = self._read_hsp_state_value(candidate, *keys)
                if value is not None:
                    state[normalized] = value
            if state:
                return state
        return None

    def _safe_response_body(self, payload):
        state = self._extract_hsp_state(payload)
        if state:
            return {"hsp_state": state}
        error_detail = self._response_error_detail(payload)
        if error_detail:
            return {"error": error_detail}
        return {}

    def _redact_response_text(self, value):
        text = str(value or "").strip()
        if not text:
            return ""
        for secret in (self.handy_key, self._effective_api_v3_key()):
            secret_text = str(secret or "").strip()
            if secret_text:
                text = text.replace(secret_text, "[redacted]")
        return text[:180]

    def _response_error_detail(self, payload):
        if payload is None:
            return ""
        if isinstance(payload, str):
            return self._redact_response_text(payload)
        if isinstance(payload, (int, float, bool)):
            return self._redact_response_text(payload)
        if isinstance(payload, list):
            parts = [self._response_error_detail(item) for item in payload[:3]]
            return "; ".join(part for part in parts if part)[:180]
        if not isinstance(payload, dict):
            return ""

        parts = []

        def add(value):
            detail = self._response_error_detail(value)
            if detail and detail not in parts:
                parts.append(detail)

        for key in ("name", "code", "errorCode", "title", "type", "message", "detail", "description"):
            if key in payload:
                add(payload.get(key))
        error = payload.get("error")
        if isinstance(error, dict):
            for key in ("name", "code", "errorCode", "title", "type", "message", "detail", "description"):
                if key in error:
                    add(error.get(key))
        elif error is not None:
            add(error)
        errors = payload.get("errors")
        if isinstance(errors, list):
            add(errors)
        return "; ".join(parts)[:180]

    def _safe_rate_limit_headers(self, headers):
        if not headers:
            return {}
        result = {}
        for header, key in (
            ("X-RateLimit-Limit", "limit"),
            ("X-RateLimit-Remaining", "remaining"),
            ("X-RateLimit-Reset", "reset_seconds"),
        ):
            value = None
            try:
                value = headers.get(header)
            except AttributeError:
                value = None
            if value is None:
                continue
            try:
                result[key] = int(float(value))
            except (TypeError, ValueError):
                result[key] = str(value)[:40]
        return result

    def _record_command_result(
        self,
        path,
        body=None,
        *,
        ok,
        status_code=None,
        elapsed_ms=None,
        error="",
        response_payload=None,
        response_headers=None,
    ):
        result = {
            "path": str(path or ""),
            "ok": bool(ok),
        }
        if status_code is not None:
            try:
                result["status_code"] = int(status_code)
            except (TypeError, ValueError):
                result["status_code"] = str(status_code)
        if elapsed_ms is not None:
            try:
                result["elapsed_ms"] = round(float(elapsed_ms), 1)
            except (TypeError, ValueError):
                pass
        safe_body = self._safe_command_body(body)
        if safe_body:
            result["body"] = safe_body
        safe_response = self._safe_response_body(response_payload)
        if safe_response:
            result["response"] = safe_response
            hsp_state = safe_response.get("hsp_state")
            if isinstance(hsp_state, dict):
                self._update_hsp_state_cache(hsp_state, source="command")
        rate_limit = self._safe_rate_limit_headers(response_headers)
        if rate_limit:
            result["rate_limit"] = rate_limit
        if error:
            result["error"] = str(error)[:180]
        self._last_command_result = result
        self._command_history.append(result)

    def last_command_result(self):
        return dict(self._last_command_result) if self._last_command_result else None

    def command_history(self):
        return [dict(command) for command in self._command_history]

    def _send_command(self, path, body=None):
        if self._using_browser_bluetooth():
            self._record_command_result(
                path,
                body,
                ok=False,
                error="local Bluetooth transport only supports API v3/HSP commands",
            )
            return False
        if not self.handy_key:
            self._record_command_result(path, body, ok=False, error="missing Handy key")
            return False
        headers = {"Content-Type": "application/json", "X-Connection-Key": self.handy_key}
        return self._send_put(self.base_url, path, body, headers=headers)

    def _send_v3_command(self, path, body=None):
        if self._using_browser_bluetooth():
            return self._send_bluetooth_command(path, body)
        if not self.handy_key:
            self._record_command_result(path, body, ok=False, error="missing Handy key")
            return False
        api_key = self._effective_api_v3_key()
        if not api_key:
            self._record_command_result(path, body, ok=False, error="missing Handy API v3 Application ID")
            return False
        format_error = self._api_v3_connection_key_format_error()
        if format_error:
            self._record_command_result(path, body, ok=False, error=format_error)
            return False
        headers = {
            "Content-Type": "application/json",
            "X-Connection-Key": self.handy_key,
            "X-Api-Key": api_key,
        }
        ok = self._send_put(self.api_v3_base_url, path, body, headers=headers)
        if not ok:
            last_command = self.last_command_result() or {}
            if last_command.get("status_code") == 401:
                self._disable_api_v3_control(
                    path=path,
                    error=last_command.get("error") or "Unauthorized",
                )
        return ok

    def _send_bluetooth_command(self, path, body=None):
        bridge = self.bluetooth_bridge
        if bridge is None:
            self._record_command_result(path, body, ok=False, error="Bluetooth bridge is unavailable")
            return False
        result = bridge.send_command(path, body or {})
        response_payload = result.get("response") if isinstance(result, dict) else None
        self._record_command_result(
            path,
            body,
            ok=bool(isinstance(result, dict) and result.get("ok")),
            elapsed_ms=result.get("elapsed_ms") if isinstance(result, dict) else None,
            error=(result.get("error") if isinstance(result, dict) else "Bluetooth command failed"),
            response_payload=response_payload,
        )
        return bool(isinstance(result, dict) and result.get("ok"))

    def _effective_api_v3_key(self):
        return str(self.api_v3_key or "").strip()

    def _api_v3_connection_key_format_valid(self):
        key = str(self.handy_key or "").strip()
        return bool(HANDY_API_V3_CONNECTION_KEY_RE.fullmatch(key))

    def _api_v3_connection_key_format_error(self):
        if self._api_v3_connection_key_format_valid():
            return ""
        return (
            "The saved WiFi/Cloud REST Handy connection key is malformed for API v3. "
            "This is separate from the Device tab API v3 Application ID. "
            "Re-copy the device connection key from Handy setup and save it in the "
            "WiFi connection-key field."
        )

    def _disable_api_v3_control(self, *, path="", error=""):
        self._api_v3_auth_failed = True
        self._api_v3_auth_error = str(error or "API v3 authentication failed")[:180]
        self._api_v3_auth_failed_path = str(path or "")[:80]
        self._current_mode = None
        self._hamp_started = False
        self._hsp_streaming = False
        self._hsp_stream_id = 0
        self._clear_hsp_state_cache()
        self._server_time_offset_ms = None
        self._server_time_synced_at = 0.0
        self._reset_motion_cache()

    def _clear_hsp_state_cache(self):
        self._close_hsp_state_sse_stream()
        with self._hsp_state_cache_lock:
            self._last_hsp_state = None
            self._last_hsp_state_observed_at = None
            self._last_hsp_state_source = ""
            self._last_hsp_state_refresh_attempt_at = 0.0
            self._last_hsp_state_refresh_attempt_wall_at = None
            self._last_hsp_state_refresh_success_at = None
            self._last_hsp_state_refresh_error = ""
            self._last_hsp_state_refresh_failures = 0
        self._last_hsp_state_sse_attempt_at = None
        self._last_hsp_state_sse_connected_at = None
        self._last_hsp_state_sse_event_at = None
        self._last_hsp_state_sse_event_type = ""
        self._last_hsp_state_sse_error = ""
        self._last_hsp_state_sse_failures = 0
        self._last_hsp_state_sse_events = 0
        self._last_handy_sse_event = None
        self._last_handy_sse_event_at = None
        self._handy_sse_recent_events.clear()
        self._clear_device_connection_status()

    def _clear_device_connection_status(self):
        self._device_connection_status = "unknown"
        self._device_connection_message = ""
        self._device_connection_observed_at = None
        self._device_connection_event_type = ""

    def _record_device_connection_status(self, status, message="", *, event_type=""):
        self._device_connection_status = str(status or "unknown")[:40]
        self._device_connection_message = str(message or "")[:180]
        self._device_connection_observed_at = time.time()
        self._device_connection_event_type = str(event_type or "")[:80]

    def apply_bluetooth_status(self, payload):
        if not isinstance(payload, dict):
            return False
        connected = bool(payload.get("connected"))
        status = "online" if connected else "offline"
        event_type = str(payload.get("event_type") or payload.get("type") or "bluetooth_status")[:80]
        message = str(
            payload.get("message")
            or ("Handy Bluetooth connected." if connected else "Handy Bluetooth disconnected.")
        )[:180]
        self._record_device_connection_status(status, message, event_type=event_type)
        safe_event = {
            "connected": connected,
            "status": status,
            "message": message,
        }
        if payload.get("device_name"):
            safe_event["device_name"] = str(payload.get("device_name"))[:80]
        self._record_handy_sse_event(event_type, {"data": safe_event})
        hsp_state = payload.get("hsp_state")
        if isinstance(hsp_state, dict) and hsp_state:
            self._update_hsp_state_cache(hsp_state, source="bluetooth")
        if not connected:
            self._hsp_streaming = False
            self._hamp_started = False
            self._current_mode = None
            self._reset_motion_cache()
        return True

    def _device_status_payload_data(self, payload):
        if not isinstance(payload, dict):
            return {}
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            return data.get("data") or {}
        return data if isinstance(data, dict) else {}

    def _device_status_message(self, status_data, fallback):
        if isinstance(status_data, dict):
            for key in ("message", "reason", "description", "name", "code"):
                value = status_data.get(key)
                if value not in (None, ""):
                    return str(value)[:180]
        return fallback

    def _hsp_state_clock_ms(self, state):
        if not isinstance(state, dict):
            return None
        try:
            return float(state.get("current_time_ms"))
        except (TypeError, ValueError):
            return None

    def _hsp_state_stream_id(self, state):
        if not isinstance(state, dict):
            return None
        try:
            return int(state.get("stream_id"))
        except (TypeError, ValueError):
            return None

    def _hsp_state_cache_snapshot(self):
        with self._hsp_state_cache_lock:
            return {
                "state": dict(self._last_hsp_state) if isinstance(self._last_hsp_state, dict) else None,
                "observed_at": self._last_hsp_state_observed_at,
                "source": self._last_hsp_state_source,
                "refresh_attempt_at": self._last_hsp_state_refresh_attempt_at,
                "refresh_attempt_wall_at": self._last_hsp_state_refresh_attempt_wall_at,
                "refresh_success_at": self._last_hsp_state_refresh_success_at,
                "refresh_error": self._last_hsp_state_refresh_error,
                "refresh_failures": self._last_hsp_state_refresh_failures,
            }

    def _update_hsp_state_cache(self, state, *, source="command"):
        if not isinstance(state, dict) or not state:
            return False
        now = time.time()
        next_state = dict(state)
        incoming_clock = self._hsp_state_clock_ms(next_state)
        incoming_stream_id = self._hsp_state_stream_id(next_state)
        normalized_source = str(source or "command")[:40]
        with self._hsp_state_cache_lock:
            cached_state = self._last_hsp_state if isinstance(self._last_hsp_state, dict) else None
            cached_clock = self._hsp_state_clock_ms(cached_state)
            cached_stream_id = self._hsp_state_stream_id(cached_state)
            cached_at = self._last_hsp_state_observed_at
            cached_age = now - float(cached_at or 0.0)
            same_stream = (
                incoming_stream_id is not None
                and cached_stream_id is not None
                and incoming_stream_id == cached_stream_id
            ) or (incoming_stream_id is None and cached_stream_id is None)
            if (
                cached_clock is not None
                and incoming_clock is not None
                and incoming_clock < cached_clock
                and cached_age < 0.5
                and (
                    same_stream
                    or (
                        normalized_source == "command"
                        and (incoming_stream_id is None or cached_stream_id is None)
                    )
                )
            ):
                return False
            self._last_hsp_state = next_state
            self._last_hsp_state_observed_at = now
            self._last_hsp_state_source = normalized_source
            if normalized_source == "poll":
                self._last_hsp_state_refresh_success_at = now
            self._last_hsp_state_refresh_error = ""
            self._last_hsp_state_refresh_failures = 0
        return True

    def _record_hsp_state_refresh_failure(self, error):
        with self._hsp_state_cache_lock:
            self._last_hsp_state_refresh_failures += 1
            self._last_hsp_state_refresh_error = str(error or "HSP state refresh failed")[:180]

    def _close_hsp_state_sse_stream(self):
        response = None
        thread = None
        with self._hsp_state_sse_thread_lock:
            self._hsp_state_sse_generation += 1
            response = self._hsp_state_sse_response
            thread = self._hsp_state_sse_thread
            self._hsp_state_sse_response = None
            self._hsp_state_sse_thread = None
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        if thread is not None and thread is not threading.current_thread():
            try:
                if thread.is_alive():
                    thread.join(timeout=0.4)
            except Exception:
                pass

    def _record_hsp_state_sse_failure(self, error):
        self._last_hsp_state_sse_failures += 1
        self._last_hsp_state_sse_error = str(error or "HSP SSE stream failed")[:180]

    def _record_hsp_state_sse_event(self, event_type):
        now = time.time()
        self._last_hsp_state_sse_event_at = now
        self._last_hsp_state_sse_event_type = str(event_type or "message")[:80]
        self._last_hsp_state_sse_events += 1
        self._last_hsp_state_sse_error = ""
        self._last_hsp_state_sse_failures = 0

    def _safe_sse_value(self, value, *, depth=0):
        if depth > 4:
            return None
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, (int, float)):
            if isinstance(value, float) and not value.is_integer():
                return round(value, 4)
            return int(value)
        if isinstance(value, str):
            return value.strip()[:180]
        if isinstance(value, dict):
            result = {}
            for key, nested in value.items():
                safe_key = str(key or "").strip()[:80]
                if not safe_key:
                    continue
                normalized_key = safe_key.lower().replace("_", "").replace("-", "")
                if normalized_key in HANDY_SSE_SECRET_KEYS:
                    continue
                safe_nested = self._safe_sse_value(nested, depth=depth + 1)
                if safe_nested is not None:
                    result[safe_key] = safe_nested
                elif nested is None:
                    result[safe_key] = None
            return result
        if isinstance(value, (list, tuple)):
            result = []
            for item in value[:10]:
                safe_item = self._safe_sse_value(item, depth=depth + 1)
                if safe_item is not None:
                    result.append(safe_item)
            return result
        return None

    def _record_handy_sse_event(self, event_type, payload, *, event_id=None):
        now = time.time()
        record = {
            "type": str(event_type or "message")[:80],
            "at": round(now, 3),
        }
        if event_id:
            record["id"] = str(event_id)[:80]
        safe_payload = self._safe_sse_value(payload)
        if isinstance(safe_payload, dict) and safe_payload:
            record["payload"] = safe_payload
        self._last_handy_sse_event = record
        self._last_handy_sse_event_at = now
        self._handy_sse_recent_events.append(record)
        return record

    def supports_api_v3_control(self):
        if self._using_browser_bluetooth():
            return bool(self.firmware_version == "fw4" and self._bluetooth_ready())
        return bool(
            self.firmware_version == "fw4"
            and self.handy_key
            and self._api_v3_connection_key_format_valid()
            and self._effective_api_v3_key()
            and not self._api_v3_auth_failed
        )

    def api_v3_unavailable_reason(self):
        if self.firmware_version != "fw4":
            return "firmware_v3_legacy"
        if self._using_browser_bluetooth():
            if not self._bluetooth_ready():
                return "bluetooth_not_connected"
            return ""
        if not self.handy_key:
            return "missing_connection_key"
        if not self._api_v3_connection_key_format_valid():
            return "invalid_connection_key_format"
        if not self._effective_api_v3_key():
            return "missing_api_v3_key"
        if self._api_v3_auth_failed:
            return "api_v3_auth_failed"
        return ""

    def _send_put(self, base_url, path, body=None, *, headers):
        started_at = time.monotonic()
        response = None
        try:
            response = _session_put(f"{base_url}{path}", headers=headers, json=body or {}, timeout=10)
            response.raise_for_status()
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            try:
                response_payload = response.json()
            except (TypeError, ValueError, AttributeError):
                response_payload = None
            self._record_command_result(
                path,
                body,
                ok=True,
                status_code=getattr(response, "status_code", None),
                elapsed_ms=elapsed_ms,
                response_payload=response_payload,
                response_headers=getattr(response, "headers", None),
            )
            return True
        except requests.exceptions.RequestException as e:
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            error_response = getattr(e, "response", None) or response
            try:
                response_payload = error_response.json() if error_response is not None else None
            except (TypeError, ValueError, AttributeError):
                response_payload = None
            self._record_command_result(
                path,
                body,
                ok=False,
                status_code=getattr(error_response, "status_code", None),
                elapsed_ms=elapsed_ms,
                error=e,
                response_payload=response_payload,
                response_headers=getattr(error_response, "headers", None),
            )
            print(f"[HANDY ERROR] Problem: {e}", file=sys.stderr)
            return False

    def check_connection(self):
        """Probe the current Handy key without starting motion."""
        if self._using_browser_bluetooth():
            snapshot = (
                self.bluetooth_bridge.snapshot()
                if self.bluetooth_bridge is not None
                else {"connected": False, "message": "Bluetooth bridge is unavailable."}
            )
            if not snapshot.get("connected"):
                self._record_command_result(
                    "bluetooth/status",
                    ok=False,
                    error=snapshot.get("message", "Bluetooth is not connected."),
                )
                return {
                    "status": "error",
                    "connected": False,
                    "message": snapshot.get("message") or "Bluetooth is not connected.",
                    "transport": "browser_bluetooth",
                    "bluetooth": snapshot,
                    "last_command": self.last_command_result(),
                }
            connected = self._send_bluetooth_command("hsp/state", {})
            snapshot = (
                self.bluetooth_bridge.snapshot()
                if self.bluetooth_bridge is not None
                else snapshot
            )
            last_command = self.last_command_result()
            error = (last_command or {}).get("error") or snapshot.get("last_error") or ""
            message = (
                "Handy Bluetooth device answered HSP state check."
                if connected
                else f"Handy Bluetooth device check failed: {error or 'no HSP state response'}"
            )
            return {
                "status": "connected" if connected else "error",
                "connected": connected,
                "message": message,
                "transport": "browser_bluetooth",
                "bluetooth": snapshot,
                "last_command": last_command,
            }
        path = "connected"
        if not self.handy_key:
            self._record_command_result(path, ok=False, error="missing Handy key")
            return {
                "status": "error",
                "connected": False,
                "message": "Handy connection key is missing.",
                "last_command": self.last_command_result(),
            }

        use_api_v3 = bool(self.firmware_version == "fw4" and self.handy_key and self._effective_api_v3_key())
        base_url = self.api_v3_base_url if use_api_v3 else self.base_url
        headers = {"X-Connection-Key": self.handy_key}
        if use_api_v3:
            format_error = self._api_v3_connection_key_format_error()
            if format_error:
                self._record_command_result(path, ok=False, error=format_error)
                return {
                    "status": "error",
                    "connected": False,
                    "message": (
                        "Handy API v3 connection check was not sent. "
                        f"{format_error}"
                    ),
                    "last_command": self.last_command_result(),
                }
            headers["X-Api-Key"] = self._effective_api_v3_key()
        started_at = time.monotonic()
        response = None
        try:
            response = _session_get(f"{base_url}{path}", headers=headers, timeout=10)
            response.raise_for_status()
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            try:
                response_payload = response.json()
            except (TypeError, ValueError, AttributeError):
                response_payload = None
            connected = True
            if isinstance(response_payload, dict) and "connected" in response_payload:
                connected = bool(response_payload.get("connected"))
            self._record_command_result(
                path,
                ok=connected,
                status_code=getattr(response, "status_code", None),
                elapsed_ms=elapsed_ms,
                response_payload=response_payload,
                response_headers=getattr(response, "headers", None),
            )
            return {
                "status": "connected" if connected else "offline",
                "connected": connected,
                "message": "Connected to Handy." if connected else "Handy device is offline.",
                "last_command": self.last_command_result(),
            }
        except requests.exceptions.RequestException as e:
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            error_response = getattr(e, "response", None) or response
            try:
                response_payload = error_response.json() if error_response is not None else None
            except (TypeError, ValueError, AttributeError):
                response_payload = None
            self._record_command_result(
                path,
                ok=False,
                status_code=getattr(error_response, "status_code", None),
                elapsed_ms=elapsed_ms,
                error=e,
                response_payload=response_payload,
                response_headers=getattr(error_response, "headers", None),
            )
            if use_api_v3 and getattr(error_response, "status_code", None) == 401:
                self._disable_api_v3_control(path=path, error=str(e))
            print(f"[HANDY ERROR] Connection check failed: {e}", file=sys.stderr)
            status_code = getattr(error_response, "status_code", None)
            message = f"Handy connection failed: {e}"
            if use_api_v3 and status_code in {400, 401, 403}:
                response_detail = self._response_error_detail(response_payload)
                response_suffix = f" Handy response: {response_detail}." if response_detail else ""
                message = (
                    "Handy API v3 connection check failed. Check the Device tab "
                    f"Application ID and Handy connection key.{response_suffix} ({e})"
                )
            return {
                "status": "error",
                "connected": False,
                "message": message,
                "last_command": self.last_command_result(),
            }

    def _ensure_hamp(self):
        if self._hsp_streaming:
            self._send_v3_command("hsp/stop")
            self._hsp_streaming = False
        if self._current_mode != MODE_HAMP:
            if not self._send_mode_command(MODE_HAMP):
                return False
            self._current_mode = MODE_HAMP
            self._hamp_started = False
            self._reset_motion_cache()
        if not self._hamp_started:
            if not self._send_hamp_start():
                return False
            self._hamp_started = True
        return True

    def _ensure_hdsp(self):
        if self._hsp_streaming:
            self._send_v3_command("hsp/stop")
            self._hsp_streaming = False
        if self._hamp_started:
            if not self._send_hamp_stop():
                return False
            self._hamp_started = False
            self._reset_motion_cache()
        if self._current_mode != MODE_HDSP:
            if not self._send_mode_command(MODE_HDSP):
                return False
            self._current_mode = MODE_HDSP
            self._reset_motion_cache()
        return True

    def supports_continuous_streaming(self):
        return self.supports_api_v3_control()

    def _send_mode_command(self, mode):
        body = {"mode": int(mode)}
        if self.supports_api_v3_control():
            if self._send_v3_command("mode2", body):
                return True
            if not self._api_v3_auth_failed:
                return False
        return self._send_command("mode", body)

    def _send_hamp_start(self):
        if self.supports_api_v3_control():
            if self._send_v3_command("hamp/start"):
                return True
            if not self._api_v3_auth_failed:
                return False
        return self._send_command("hamp/start")

    def _send_hamp_stop(self):
        if self.supports_api_v3_control():
            if self._send_v3_command("hamp/stop"):
                return True
            if not self._api_v3_auth_failed:
                return False
        return self._send_command("hamp/stop")

    def _parse_server_time_ms(self, payload):
        if isinstance(payload, (int, float)):
            return float(payload)
        if isinstance(payload, str):
            try:
                return float(payload)
            except ValueError:
                return None
        if not isinstance(payload, dict):
            return None
        for key in ("server_time", "serverTime", "server_time_ms", "serverTimeMs", "time", "now"):
            if key not in payload:
                continue
            try:
                return float(payload[key])
            except (TypeError, ValueError):
                continue
        return None

    def _refresh_server_time_offset(self):
        started_monotonic = time.monotonic()
        started_wall_ms = time.time() * 1000.0
        response = None
        try:
            response = _session_get(f"{self.api_v3_base_url}servertime", timeout=5)
            response.raise_for_status()
            ended_wall_ms = time.time() * 1000.0
            try:
                payload = response.json()
            except (TypeError, ValueError, AttributeError):
                payload = getattr(response, "text", None)
        except Exception:
            return False

        server_time_ms = self._parse_server_time_ms(payload)
        if server_time_ms is None:
            return False
        local_midpoint_ms = (started_wall_ms + ended_wall_ms) / 2.0
        self._server_time_offset_ms = server_time_ms - local_midpoint_ms
        self._server_time_synced_at = started_monotonic
        return True

    def _server_time_offset_is_stale(self):
        offset_age = time.monotonic() - float(self._server_time_synced_at or 0.0)
        return (
            self._server_time_offset_ms is None
            or offset_age > HSP_SERVER_TIME_SYNC_TTL_SECONDS
        )

    def _refresh_server_time_offset_async(self):
        with self._server_time_refresh_thread_lock:
            thread = self._server_time_refresh_thread
            if thread is not None and thread.is_alive():
                return False
            thread = threading.Thread(
                target=self._refresh_server_time_offset,
                name="StrokeGPT-HSP-Server-Time",
                daemon=True,
            )
            self._server_time_refresh_thread = thread
            thread.start()
        return True

    def _estimated_server_time_ms(self, *, allow_refresh=True):
        if self._server_time_offset_is_stale() and allow_refresh:
            self._refresh_server_time_offset()
        now_ms = time.time() * 1000.0
        if self._server_time_offset_ms is None:
            return int(round(now_ms))
        return int(round(now_ms + self._server_time_offset_ms))

    def _safe_percent(self, p):
        try:
            p = float(p)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(100.0, p))

    def _relative_speed_to_velocity(self, speed):
        # MotionTarget.speed is already a 0-100 app speed percentage. The
        # configured user range is a safety clamp, not a second 0-100 scale.
        relative_speed_pct = self._safe_percent(speed)
        velocity = max(self.min_user_speed, min(self.max_user_speed, relative_speed_pct))
        return int(round(velocity))

    def effective_speed_for_relative(self, speed):
        return self._relative_speed_to_velocity(speed)

    def max_velocity_for_relative_speed(self, speed):
        return min(self.max_user_speed, self._relative_speed_to_velocity(speed))

    def _speed_percent_to_absolute_velocity(self, speed_percent):
        return (self._safe_percent(speed_percent) / 100.0) * HANDY_MAX_ABSOLUTE_VELOCITY_MM_S

    @property
    def min_absolute_user_speed(self):
        return self._speed_percent_to_absolute_velocity(self.min_user_speed)

    @property
    def max_absolute_user_speed(self):
        return self._speed_percent_to_absolute_velocity(self.max_user_speed)

    def absolute_velocity_for_relative_speed(self, speed):
        return int(round(self._speed_percent_to_absolute_velocity(self._relative_speed_to_velocity(speed))))

    def max_absolute_velocity_for_relative_speed(self, speed):
        return min(self.max_absolute_user_speed, self.absolute_velocity_for_relative_speed(speed))

    def _clamp_absolute_velocity(self, velocity, relative_speed=None):
        if relative_speed is None:
            max_velocity = self.max_absolute_user_speed
        else:
            max_velocity = self.max_absolute_velocity_for_relative_speed(relative_speed)
        try:
            requested_velocity = float(velocity)
        except (TypeError, ValueError):
            requested_velocity = max_velocity
        if max_velocity <= 0:
            return 0
        min_velocity = min(self.min_absolute_user_speed, max_velocity)
        return int(round(max(min_velocity, min(max_velocity, requested_velocity))))

    def _velocity_to_v3_ratio(self, velocity):
        try:
            velocity = float(velocity)
        except (TypeError, ValueError):
            velocity = 0.0
        return round(max(0.0, min(1.0, velocity / 100.0)), 4)

    def _relative_depth_to_mm(self, depth):
        absolute_pos_pct = self._relative_depth_to_physical_percent(depth)
        return self.FULL_TRAVEL_MM * (absolute_pos_pct / 100.0)

    def _calibrated_depth_bounds(self):
        min_depth = self._safe_percent(self.min_handy_depth)
        max_depth = self._safe_percent(self.max_handy_depth)
        if min_depth <= max_depth:
            return min_depth, max_depth
        return max_depth, min_depth

    def _relative_depth_to_physical_percent(self, depth):
        relative_pos_pct = self._safe_percent(depth)
        min_depth, max_depth = self._calibrated_depth_bounds()
        calibrated_width = max_depth - min_depth
        return min_depth + calibrated_width * (relative_pos_pct / 100.0)

    def _hamp_window_for_relative_motion(self, depth, stroke_range):
        relative_pos_pct = self._safe_percent(depth)
        relative_range_pct = self._safe_percent(stroke_range)
        min_depth, max_depth = self._calibrated_depth_bounds()
        absolute_center_pct = self._relative_depth_to_physical_percent(relative_pos_pct)
        span_abs = ((max_depth - min_depth) * (relative_range_pct / 100.0)) / 2.0
        min_zone_abs = max(min_depth, absolute_center_pct - span_abs)
        max_zone_abs = min(max_depth, absolute_center_pct + span_abs)
        slide_min, slide_max = self._normalize_slide_bounds(
            round(100 - max_zone_abs),
            round(100 - min_zone_abs),
        )
        stroke_zone = {
            "min": int(round(min_zone_abs)),
            "max": int(round(max_zone_abs)),
        }
        return relative_pos_pct, relative_range_pct, stroke_zone, (slide_min, slide_max)

    def velocity_for_depth_interval(self, speed, start_depth, end_depth, duration_seconds):
        max_velocity = self.max_absolute_velocity_for_relative_speed(speed)
        try:
            duration_seconds = float(duration_seconds)
        except (TypeError, ValueError):
            duration_seconds = 0.0
        if duration_seconds <= 0:
            return max_velocity

        distance_mm = abs(self._relative_depth_to_mm(end_depth) - self._relative_depth_to_mm(start_depth))
        planned_velocity = int(round(distance_mm / duration_seconds))
        planned_velocity = max(self.min_absolute_user_speed, planned_velocity)
        return min(max_velocity, planned_velocity)

    def duration_ms_for_depth_interval(self, velocity, start_depth, end_depth):
        try:
            velocity = max(1.0, float(velocity))
        except (TypeError, ValueError):
            velocity = max(1.0, float(self.min_absolute_user_speed or 1))
        distance_mm = abs(self._relative_depth_to_mm(end_depth) - self._relative_depth_to_mm(start_depth))
        if distance_mm <= 0:
            return 1
        return max(1, int(round((distance_mm / velocity) * 1000.0)))

    def move(self, speed, depth, stroke_range):
        """
        A simpler move function that expects complete instructions from the AI.
        It scales the provided values to the user's calibrated limits.
        """
        if not self._has_control_connection():
            self._record_command_result("hamp/move", ok=False, error=self._control_connection_error())
            return False

        # A speed of 0 is a special command to stop all movement.
        if speed is not None and speed == 0:
            self.stop()
            return True

        # Handle cases where the AI might still send null values
        if speed is None or depth is None or stroke_range is None:
            print("[WARN] Incomplete move received from AI, ignoring.")
            return False

        if not self._ensure_hamp():
            return False

        relative_pos_pct, relative_range_pct, _stroke_zone, slide_bounds = (
            self._hamp_window_for_relative_motion(depth, stroke_range)
        )
        slide_min, slide_max = slide_bounds

        # Calculate and set the final velocity
        relative_speed_pct = self._safe_percent(speed)
        final_physical_speed = self._relative_speed_to_velocity(relative_speed_pct)

        # When redirecting from fast motion into a narrower/deeper range, lower
        # velocity before changing slide bounds so the device does not race to
        # the new focus area using the previous high speed.
        velocity_first = self._last_velocity is not None and final_physical_speed < self._last_velocity
        if velocity_first and not self._send_velocity(final_physical_speed):
            return False

        if not self._send_slide_bounds(slide_min, slide_max):
            return False

        if not velocity_first and not self._send_velocity(final_physical_speed):
            return False

        # Update state variables for the next command
        self.last_stroke_speed = final_physical_speed
        self.last_relative_speed = relative_speed_pct
        self.last_depth_pos = int(round(relative_pos_pct))
        self.last_stroke_range = int(round(relative_range_pct))
        return True

    def move_to_depth(self, speed, depth, *, stop_on_target=True, velocity=None, intent_speed=None, duration_ms=None):
        """Move to a single calibrated depth target for pattern previews."""
        if not self._has_control_connection():
            self._record_command_result("hdsp/xava", ok=False, error=self._control_connection_error())
            return False
        if speed is not None and speed == 0:
            self.stop()
            return True
        if speed is None or depth is None:
            print("[WARN] Incomplete position move received, ignoring.")
            return False

        if not self._ensure_hdsp():
            return False

        relative_speed_pct = self._safe_percent(speed)
        intent_speed_pct = relative_speed_pct if intent_speed is None else self._safe_percent(intent_speed)
        relative_pos_pct = self._safe_percent(depth)
        if velocity is None:
            velocity = self.max_absolute_velocity_for_relative_speed(relative_speed_pct)
        else:
            velocity = self._clamp_absolute_velocity(velocity, relative_speed_pct)
        velocity = int(round(velocity))

        if self.supports_api_v3_control():
            minimum_duration_ms = self.duration_ms_for_depth_interval(velocity, self.last_depth_pos, relative_pos_pct)
            if duration_ms is None:
                duration_ms = minimum_duration_ms
            else:
                try:
                    duration_ms = int(round(float(duration_ms)))
                except (TypeError, ValueError):
                    duration_ms = minimum_duration_ms
                duration_ms = max(1, minimum_duration_ms, duration_ms)
            physical_pos_pct = self._relative_depth_to_physical_percent(relative_pos_pct)
            body = {
                "xp": round(max(0.0, min(1.0, physical_pos_pct / 100.0)), 4),
                "t": duration_ms,
                "stop_on_target": bool(stop_on_target),
                "immediate_rsp": False,
            }
            if not self._send_v3_command("hdsp/xpt", body):
                return False

            self._current_mode = MODE_HDSP
            self._last_velocity = velocity
            self.last_stroke_speed = velocity
            self.last_relative_speed = intent_speed_pct
            self.last_depth_pos = int(round(relative_pos_pct))
            return True

        position = self._relative_depth_to_mm(relative_pos_pct)
        body = {"position": position, "velocity": velocity, "stopOnTarget": bool(stop_on_target)}
        if not self._send_command("hdsp/xava", body):
            return False

        self._current_mode = MODE_HDSP
        self._last_velocity = velocity
        self.last_stroke_speed = velocity
        self.last_relative_speed = intent_speed_pct
        self.last_depth_pos = int(round(relative_pos_pct))
        return True

    def _stream_point_body(self, point):
        if not isinstance(point, dict):
            return None
        try:
            at_ms = max(0, int(round(float(point.get("t", 0)))))
            app_depth = self._safe_percent(point.get("x", point.get("depth", 50)))
        except (TypeError, ValueError):
            return None
        return {
            "t": at_ms,
            "x": max(0, min(HSP_POINT_MAX, int(round(app_depth)))),
        }

    def _stream_points_body(self, points):
        result = []
        for point in points or []:
            body = self._stream_point_body(point)
            if body is not None:
                result.append(body)
        return result

    def _ensure_hsp(self, stream_id=None):
        if not self.supports_continuous_streaming():
            self._record_command_result(
                "hsp/setup",
                ok=False,
                error=(
                    "Handy firmware v4 and local Bluetooth connection required"
                    if self._using_browser_bluetooth()
                    else "Handy firmware v4 and connection key required"
                ),
            )
            return False
        if self._hamp_started:
            if not self._send_hamp_stop():
                return False
            self._hamp_started = False
            self._reset_motion_cache()

        if self._current_mode != MODE_HSP:
            if not self._send_mode_command(MODE_HSP):
                return False
            self._current_mode = MODE_HSP
            self._reset_motion_cache()

        bounds = (
            round(self._safe_percent(self.min_handy_depth) / 100.0, 4),
            round(self._safe_percent(self.max_handy_depth) / 100.0, 4),
        )
        if bounds[0] > bounds[1]:
            bounds = (bounds[1], bounds[0])
        if bounds != self._last_v3_stroke_bounds:
            if not self._send_v3_command("slider/stroke", {"min": bounds[0], "max": bounds[1]}):
                return False
            self._last_v3_stroke_bounds = bounds

        body = None
        if stream_id is not None:
            body = {}
            try:
                body["stream_id"] = max(1, min(4294967295, int(stream_id)))
            except (TypeError, ValueError):
                pass
        if body is not None or not self._hsp_streaming:
            if not self._send_v3_command("hsp/setup", body or {}):
                return False
        self._hsp_streaming = True
        return True

    def _next_hsp_stream_id(self):
        if self._hsp_stream_id >= HSP_STREAM_ID_MAX:
            self._hsp_stream_id = 1
        else:
            self._hsp_stream_id = max(1, int(self._hsp_stream_id or 0) + 1)
        return self._hsp_stream_id

    def _send_hsp_threshold(self, tail_point_threshold, *, force=False):
        if tail_point_threshold is None:
            return True
        try:
            threshold = max(0, int(tail_point_threshold))
        except (TypeError, ValueError):
            return True
        now = time.monotonic()
        if not force and self._last_hsp_threshold_value is not None:
            if now - self._last_hsp_threshold_update_at < HSP_THRESHOLD_UPDATE_MIN_INTERVAL_SECONDS:
                return True
        sent = self._send_v3_command("hsp/threshold", {"tail_point_threshold": threshold})
        if sent:
            self._last_hsp_threshold_update_at = now
            self._last_hsp_threshold_value = threshold
        return sent

    def _hsp_add_body(
        self,
        stream_points,
        *,
        flush,
        tail_point_stream_index,
        tail_point_threshold=None,
    ):
        body = {
            "points": stream_points[:100],
            "flush": bool(flush),
            "tail_point_stream_index": max(1, int(tail_point_stream_index)),
        }
        if self._using_browser_bluetooth() and tail_point_threshold is not None:
            try:
                body["tail_point_threshold"] = max(0, int(tail_point_threshold))
            except (TypeError, ValueError):
                pass
        return body

    def _send_hsp_threshold_after_add(self, tail_point_threshold, *, force=False):
        if self._using_browser_bluetooth():
            return True
        return self._send_hsp_threshold(tail_point_threshold, force=force)

    def _hsp_state_indicates_starved_or_paused(self):
        snapshot = self._hsp_state_cache_snapshot()
        state = snapshot["state"] if isinstance(snapshot, dict) else None
        if isinstance(state, dict):
            play_state = str(state.get("play_state") or "").strip().lower()
            if "starv" in play_state or "pause" in play_state:
                return True
            if play_state:
                return False
        event_type = str(self._last_hsp_state_sse_event_type or "").strip().lower()
        return event_type in HSP_STATE_STARVING_EVENTS

    def _resume_hsp_after_add(self, add_result, *, force=False):
        if (
            not force
            and not self._using_browser_bluetooth()
            and not self._hsp_state_indicates_starved_or_paused()
        ):
            return True
        if not self._send_v3_command("hsp/resume", {"pick_up": False}):
            return False
        if add_result is not None:
            self._last_command_result = add_result
        return True

    def _hsp_point_time_bounds(self, points):
        times = []
        for point in points or ():
            if not isinstance(point, dict):
                continue
            try:
                times.append(int(round(float(point.get("t")))))
            except (TypeError, ValueError):
                continue
        if not times:
            return None
        return min(times), max(times)

    def _hsp_first_point_time_ms(self, points, fallback=0):
        bounds = self._hsp_point_time_bounds(points)
        if bounds:
            return bounds[0]
        try:
            return max(0, int(round(fallback)))
        except (TypeError, ValueError):
            return 0

    def _hsp_state_clock_is_past_points(self, points):
        snapshot = self._hsp_state_cache_snapshot()
        state = snapshot["state"]
        bounds = self._hsp_point_time_bounds(points)
        if not state or not bounds:
            return False
        try:
            current_time = int(state.get("current_time_ms"))
        except (TypeError, ValueError):
            return False
        _first_point_time, last_point_time = bounds
        try:
            state_last_point_time = int(state.get("last_point_time_ms"))
        except (TypeError, ValueError):
            state_last_point_time = last_point_time
        latest_known_point = max(last_point_time, state_last_point_time)
        return current_time > latest_known_point + HSP_STALE_CLOCK_TOLERANCE_MS

    def _send_hsp_play(self, start_time_ms):
        if self._server_time_offset_is_stale():
            self._refresh_server_time_offset_async()
        body = {
            "start_time": max(0, int(round(start_time_ms))),
            "server_time": self._estimated_server_time_ms(allow_refresh=False),
            "playback_rate": 1.0,
            "pause_on_starving": True,
            "loop": False,
        }
        return self._send_v3_command("hsp/play", body)

    def _restart_hsp_if_clock_is_stale(self, stream_points, start_time_ms=None):
        if not self._hsp_state_clock_is_past_points(stream_points):
            return None
        if start_time_ms is None:
            bounds = self._hsp_point_time_bounds(stream_points)
            if not bounds:
                return None
            start_time_ms = bounds[0]
        return bool(self._send_hsp_play(start_time_ms))

    def start_continuous_stream(
        self,
        points,
        *,
        stream_id=None,
        start_time_ms=0,
        tail_point_stream_index=None,
        tail_point_threshold=None,
    ):
        stream_points = self._stream_points_body(points)
        if not stream_points:
            self._record_command_result("hsp/play", ok=False, error="empty HSP point stream")
            return False
        replace_active_stream = self._hsp_streaming and self._current_mode == MODE_HSP
        if stream_id is None and not replace_active_stream:
            stream_id = self._next_hsp_stream_id()
        if not self._ensure_hsp(stream_id=stream_id):
            return False

        tail_index = int(tail_point_stream_index or len(stream_points))
        add = self._hsp_add_body(
            stream_points,
            flush=True,
            tail_point_stream_index=tail_index,
            tail_point_threshold=tail_point_threshold,
        )
        if not self._send_v3_command("hsp/add", add):
            return False
        add_result = self._last_command_result
        if not self._send_hsp_threshold_after_add(tail_point_threshold, force=True) and self._api_v3_auth_failed:
            return False
        if replace_active_stream:
            restarted = self._restart_hsp_if_clock_is_stale(
                stream_points,
                self._hsp_first_point_time_ms(stream_points, fallback=start_time_ms),
            )
            if restarted is False:
                return False
            if restarted is not True and not self._resume_hsp_after_add(add_result):
                return False
            if add_result is not None and restarted is not True:
                self._last_command_result = add_result
            self._hsp_streaming = True
            self._update_stream_state(points[0])
            return True

        if not self._send_hsp_play(start_time_ms):
            return False

        self._hsp_streaming = True
        self._update_stream_state(points[0])
        return True

    def append_continuous_stream(
        self,
        points,
        *,
        tail_point_stream_index,
        tail_point_threshold=None,
        force_resume=False,
    ):
        stream_points = self._stream_points_body(points)
        if not stream_points:
            return True
        body = self._hsp_add_body(
            stream_points,
            flush=False,
            tail_point_stream_index=tail_point_stream_index,
            tail_point_threshold=tail_point_threshold,
        )
        if not self._send_v3_command("hsp/add", body):
            return False
        add_result = self._last_command_result
        if not self._send_hsp_threshold_after_add(tail_point_threshold) and self._api_v3_auth_failed:
            return False
        restarted = self._restart_hsp_if_clock_is_stale(stream_points)
        if restarted is False:
            return False
        if restarted is not True and not self._resume_hsp_after_add(add_result, force=force_resume):
            return False
        if add_result is not None and restarted is not True:
            self._last_command_result = add_result
        self._hsp_streaming = True
        return True

    def sync_continuous_stream_time(self, current_time_ms, *, filter=0.5):
        if not self.supports_continuous_streaming():
            self._record_command_result(
                "hsp/synctime",
                ok=False,
                error=(
                    "Handy firmware v4 and local Bluetooth connection required"
                    if self._using_browser_bluetooth()
                    else "Handy firmware v4 and connection key required"
                ),
            )
            return False
        try:
            current_time = max(0, int(round(float(current_time_ms))))
        except (TypeError, ValueError):
            current_time = 0
        try:
            sync_filter = max(0.0, min(1.0, float(filter)))
        except (TypeError, ValueError):
            sync_filter = 0.5
        body = {
            "current_time": current_time,
            "server_time": self._estimated_server_time_ms(),
            "filter": round(sync_filter, 3),
        }
        return self._send_v3_command("hsp/synctime", body)

    def _hsp_state_sse_url(self):
        api_key = self._effective_api_v3_key()
        query = urlencode(
            {
                "ck": self.handy_key,
                "apikey": api_key,
                "events": ",".join(HSP_STATE_SSE_EVENTS),
            }
        )
        return f"{self.api_v3_base_url}sse?{query}"

    def _same_hsp_state_sse_generation(self, generation):
        return (
            generation == self._hsp_state_sse_generation
            and self.supports_api_v3_control()
            and not self._using_browser_bluetooth()
        )

    def _iter_hsp_state_sse_events(self, response, generation):
        event_id = None
        event_type = None
        data_lines = []
        for raw_line in response.iter_lines(decode_unicode=True):
            if not self._same_hsp_state_sse_generation(generation):
                return
            if raw_line is None:
                continue
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r")
            else:
                line = str(raw_line).rstrip("\r")
            if line == "":
                if data_lines:
                    yield {
                        "id": event_id,
                        "type": event_type or "",
                        "data": "\n".join(data_lines),
                    }
                event_id = None
                event_type = None
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            field, separator, value = line.partition(":")
            if not separator:
                continue
            if value.startswith(" "):
                value = value[1:]
            if field == "id":
                event_id = value
            elif field == "event":
                event_type = value
            elif field == "data":
                data_lines.append(value)
        if data_lines and self._same_hsp_state_sse_generation(generation):
            yield {
                "id": event_id,
                "type": event_type or "",
                "data": "\n".join(data_lines),
            }

    def _handle_hsp_state_sse_event(self, event):
        if not isinstance(event, dict):
            return False
        event_type = str(event.get("type") or "").strip()
        data_text = str(event.get("data") or "").strip()
        if not data_text:
            return False
        try:
            payload = json.loads(data_text)
        except (TypeError, ValueError):
            return False
        if not event_type and isinstance(payload, dict):
            event_type = str(payload.get("type") or payload.get("event") or "").strip()
        if not event_type:
            event_type = "message"
        self._record_hsp_state_sse_event(event_type)
        self._record_handy_sse_event(event_type, payload, event_id=event.get("id"))
        if event_type == "device_disconnected":
            status_data = self._device_status_payload_data(payload)
            self._record_device_connection_status(
                "offline",
                self._device_status_message(status_data, "Handy SSE reports the device disconnected."),
                event_type=event_type,
            )
            self._hsp_streaming = False
            self._hamp_started = False
            self._current_mode = None
            self._reset_motion_cache()
            return True
        if event_type == "device_connected":
            status_data = self._device_status_payload_data(payload)
            self._record_device_connection_status(
                "online",
                self._device_status_message(status_data, "Handy SSE reports the device is online."),
                event_type=event_type,
            )
            return True
        if event_type == "device_error":
            status_data = self._device_status_payload_data(payload)
            self._record_device_connection_status(
                "error",
                self._device_status_message(status_data, "Handy SSE reported a device error."),
                event_type=event_type,
            )
            return True
        if event_type == "device_status":
            status_data = self._device_status_payload_data(payload)
            if isinstance(status_data, dict) and status_data.get("connected") is False:
                self._record_device_connection_status(
                    "offline",
                    self._device_status_message(status_data, "Handy SSE reports the device is offline."),
                    event_type=event_type,
                )
                self._hsp_streaming = False
                self._hamp_started = False
                self._current_mode = None
                self._reset_motion_cache()
            elif isinstance(status_data, dict) and status_data.get("connected") is True:
                self._record_device_connection_status(
                    "online",
                    self._device_status_message(status_data, "Handy SSE reports the device is online."),
                    event_type=event_type,
                )
            return True
        if event_type not in HSP_STATE_SSE_STATE_EVENTS:
            return True
        state = self._extract_hsp_state(payload)
        if not isinstance(state, dict) or not state:
            self._record_hsp_state_sse_failure(f"HSP SSE {event_type} event did not include state")
            return False
        return self._update_hsp_state_cache(state, source="sse")

    def _run_hsp_state_sse_once(self, generation):
        if not self._same_hsp_state_sse_generation(generation):
            return False
        api_key = self._effective_api_v3_key()
        if not self.handy_key or not api_key:
            self._record_hsp_state_sse_failure("missing HSP SSE credentials")
            return False
        self._last_hsp_state_sse_attempt_at = time.time()
        response = None
        try:
            response = _session_get(
                self._hsp_state_sse_url(),
                headers={
                    "Accept": "text/event-stream",
                    "Cache-Control": "no-cache",
                },
                stream=True,
                timeout=(HSP_STATE_SSE_CONNECT_TIMEOUT_SECONDS, HSP_STATE_SSE_READ_TIMEOUT_SECONDS),
            )
            status_code = getattr(response, "status_code", None)
            if status_code == 401:
                self._disable_api_v3_control(path="sse", error="Unauthorized")
                return False
            response.raise_for_status()
            with self._hsp_state_sse_thread_lock:
                if not self._same_hsp_state_sse_generation(generation):
                    return False
                self._hsp_state_sse_response = response
            self._last_hsp_state_sse_connected_at = time.time()
            self._last_hsp_state_sse_error = ""
            self._last_hsp_state_sse_failures = 0
            for event in self._iter_hsp_state_sse_events(response, generation):
                self._handle_hsp_state_sse_event(event)
            return True
        except Exception as exc:
            if self._same_hsp_state_sse_generation(generation):
                self._record_hsp_state_sse_failure(exc)
            return False
        finally:
            with self._hsp_state_sse_thread_lock:
                if self._hsp_state_sse_response is response:
                    self._hsp_state_sse_response = None
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

    def ensure_hsp_state_sse_worker(self):
        if self._using_browser_bluetooth() or not self.supports_api_v3_control():
            return False
        with self._hsp_state_sse_thread_lock:
            thread = self._hsp_state_sse_thread
            if thread is not None and thread.is_alive():
                return True
            generation = self._hsp_state_sse_generation
            thread = threading.Thread(
                target=self._hsp_state_sse_loop,
                args=(generation,),
                name="StrokeGPT-HSP-State-SSE",
                daemon=True,
            )
            self._hsp_state_sse_thread = thread
            thread.start()
        return True

    def _hsp_state_sse_loop(self, generation):
        while self._same_hsp_state_sse_generation(generation):
            ok = self._run_hsp_state_sse_once(generation)
            if not self._same_hsp_state_sse_generation(generation):
                break
            sleep_seconds = (
                HSP_STATE_SSE_RECONNECT_SECONDS
                if ok and not self._last_hsp_state_sse_failures
                else HSP_STATE_SSE_FAILURE_BACKOFF_SECONDS
            )
            time.sleep(max(0.05, float(sleep_seconds)))

    def refresh_hsp_state(self, *, max_age_seconds=0.25):
        if self._using_browser_bluetooth():
            return bool(self._hsp_state_cache_snapshot()["state"])
        if not self._hsp_streaming or not self.supports_continuous_streaming():
            return False
        now = time.time()
        snapshot = self._hsp_state_cache_snapshot()
        if snapshot["observed_at"] is not None:
            try:
                if now - float(snapshot["observed_at"]) < max(0.0, float(max_age_seconds)):
                    return True
            except (TypeError, ValueError):
                pass

        monotonic_now = time.monotonic()
        retry_interval = (
            HSP_STATE_REFRESH_FAILURE_BACKOFF_SECONDS
            if snapshot["refresh_failures"]
            else HSP_STATE_REFRESH_MIN_INTERVAL_SECONDS
        )
        if (
            monotonic_now - float(snapshot["refresh_attempt_at"] or 0.0)
            < retry_interval
        ):
            return False
        with self._hsp_state_cache_lock:
            self._last_hsp_state_refresh_attempt_at = monotonic_now
            self._last_hsp_state_refresh_attempt_wall_at = now

        api_key = self._effective_api_v3_key()
        if not self.handy_key or not api_key:
            self._record_hsp_state_refresh_failure("missing HSP state credentials")
            return False
        headers = {
            "X-Connection-Key": self.handy_key,
            "X-Api-Key": api_key,
        }
        try:
            response = _session_get(
                f"{self.api_v3_base_url}hsp/state",
                headers=headers,
                timeout=HSP_STATE_REFRESH_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except (TypeError, ValueError, AttributeError):
                payload = None
        except Exception as exc:
            self._record_hsp_state_refresh_failure(exc)
            return False

        state = self._extract_hsp_state(payload)
        if not isinstance(state, dict) or not state:
            self._record_hsp_state_refresh_failure("HSP state response did not include state")
            return False
        return self._update_hsp_state_cache(state, source="poll")

    def ensure_hsp_state_refresh_worker(self):
        if self._using_browser_bluetooth():
            return False
        if not self._hsp_streaming or not self.supports_continuous_streaming():
            return False
        with self._hsp_state_refresh_thread_lock:
            thread = self._hsp_state_refresh_thread
            if thread is not None and thread.is_alive():
                return True
            thread = threading.Thread(
                target=self._hsp_state_refresh_loop,
                name="StrokeGPT-HSP-State-Refresh",
                daemon=True,
            )
            self._hsp_state_refresh_thread = thread
            thread.start()
        return True

    def _hsp_state_refresh_loop(self):
        while (
            self._hsp_streaming
            and self.supports_continuous_streaming()
            and not self._using_browser_bluetooth()
        ):
            try:
                self.refresh_hsp_state(max_age_seconds=HSP_STATE_REFRESH_MAX_AGE_SECONDS)
            except Exception as exc:
                self._record_hsp_state_refresh_failure(exc)
            snapshot = self._hsp_state_cache_snapshot()
            if snapshot["refresh_failures"]:
                sleep_seconds = HSP_STATE_REFRESH_FAILURE_BACKOFF_SECONDS
            elif self._hsp_state_sse_stream_healthy():
                # SSE is connected and delivering state pushes; relax the
                # REST poll so motion-critical hsp/add commands are not
                # competing with a 4 Hz state poll for the connection pool.
                sleep_seconds = HSP_STATE_REFRESH_SSE_BACKOFF_SECONDS
            else:
                sleep_seconds = HSP_STATE_REFRESH_MIN_INTERVAL_SECONDS
            time.sleep(max(0.05, float(sleep_seconds)))

    def _hsp_state_sse_stream_healthy(self) -> bool:
        if self._hsp_state_sse_response is None:
            return False
        if self._last_hsp_state_sse_failures:
            return False
        event_at = self._last_hsp_state_sse_event_at
        connected_at = self._last_hsp_state_sse_connected_at
        freshest = max(
            float(event_at or 0.0),
            float(connected_at or 0.0),
        )
        if freshest <= 0.0:
            return False
        return (time.time() - freshest) < HSP_STATE_SSE_READ_TIMEOUT_SECONDS

    def _update_stream_state(self, point):
        if not isinstance(point, dict):
            return
        speed = point.get("intent_speed", point.get("speed"))
        depth = point.get("x", point.get("depth"))
        if speed is not None:
            self.last_relative_speed = self._safe_percent(speed)
        if depth is not None:
            self.last_depth_pos = int(round(self._safe_percent(depth)))
        self.last_stroke_range = int(round(self._safe_percent(point.get("range", self.last_stroke_range))))

    def _normalize_slide_bounds(self, slide_min, slide_max):
        slide_min = max(0, min(100, int(round(slide_min))))
        slide_max = max(0, min(100, int(round(slide_max))))
        if slide_min >= slide_max:
            slide_max = min(100, slide_min + 2)
            if slide_min >= slide_max:
                slide_min = max(0, slide_max - 2)
        return slide_min, slide_max

    def _send_slide_bounds(self, slide_min, slide_max):
        bounds = (slide_min, slide_max)
        if bounds == self._last_slide_bounds:
            return True
        if self.supports_api_v3_control():
            stroke_min = round(max(0.0, min(1.0, (100.0 - slide_max) / 100.0)), 4)
            stroke_max = round(max(0.0, min(1.0, (100.0 - slide_min) / 100.0)), 4)
            ok = self._send_v3_command("hamp/stroke", {"min": stroke_min, "max": stroke_max})
            if not ok and self._api_v3_auth_failed:
                ok = self._send_command("slide", {"min": slide_min, "max": slide_max})
        else:
            ok = self._send_command("slide", {"min": slide_min, "max": slide_max})
        if ok:
            self._last_slide_bounds = bounds
            return True
        return False

    def _send_velocity(self, velocity):
        if velocity == self._last_velocity:
            return True
        if self.supports_api_v3_control():
            ok = self._send_v3_command("hamp/velocity", {"velocity": self._velocity_to_v3_ratio(velocity)})
            if not ok and self._api_v3_auth_failed:
                ok = self._send_command("hamp/velocity", {"velocity": velocity})
        else:
            ok = self._send_command("hamp/velocity", {"velocity": velocity})
        if ok:
            self._last_velocity = velocity
            return True
        return False

    def stop(self):
        """Stops all movement."""
        if self._hsp_streaming or self._current_mode == MODE_HSP:
            self._send_v3_command("hsp/stop")
            self._hsp_streaming = False
        if self._current_mode != MODE_HAMP:
            if self._send_mode_command(MODE_HAMP):
                self._current_mode = MODE_HAMP
        stopped = self._send_hamp_stop()
        self.last_stroke_speed = 0
        self.last_relative_speed = 0
        self._hamp_started = False
        self._reset_motion_cache()
        return stopped

    def diagnostics(
        self,
        *,
        refresh_hsp_state=False,
        include_history=True,
        include_recent_events=True,
    ):
        if refresh_hsp_state:
            try:
                self.ensure_hsp_state_sse_worker()
            except Exception:
                pass
            try:
                self.ensure_hsp_state_refresh_worker()
            except Exception:
                pass
        slide_bounds = None
        stroke_zone = None
        if self._last_slide_bounds:
            slide_bounds = {
                "min": self._last_slide_bounds[0],
                "max": self._last_slide_bounds[1],
            }
            stroke_zone = {
                "min": max(0, min(100, int(round(100 - self._last_slide_bounds[1])))),
                "max": max(0, min(100, int(round(100 - self._last_slide_bounds[0])))),
            }
        if stroke_zone is None:
            _relative_depth, _relative_range, stroke_zone, _slide_bounds = (
                self._hamp_window_for_relative_motion(self.last_depth_pos, self.last_stroke_range)
            )
        physical_depth = self._relative_depth_to_physical_percent(self.last_depth_pos)
        calibrated_min_pct, calibrated_max_pct = self._calibrated_depth_bounds()
        calibrated_min = int(round(calibrated_min_pct))
        calibrated_max = int(round(calibrated_max_pct))
        hsp_state_age_ms = None
        hsp_state_snapshot = self._hsp_state_cache_snapshot()
        if hsp_state_snapshot["observed_at"] is not None:
            hsp_state_age_ms = round(max(0.0, time.time() - hsp_state_snapshot["observed_at"]) * 1000.0, 1)
        handy_sse_event_age_ms = None
        if self._last_handy_sse_event_at is not None:
            handy_sse_event_age_ms = round(max(0.0, time.time() - self._last_handy_sse_event_at) * 1000.0, 1)
        device_connection_age_ms = None
        if self._device_connection_observed_at is not None:
            device_connection_age_ms = round(max(0.0, time.time() - self._device_connection_observed_at) * 1000.0, 1)
        hsp_refresh_thread = self._hsp_state_refresh_thread
        hsp_refresh_active = bool(hsp_refresh_thread is not None and hsp_refresh_thread.is_alive())
        hsp_sse_thread = self._hsp_state_sse_thread
        hsp_sse_active = bool(hsp_sse_thread is not None and hsp_sse_thread.is_alive())
        bluetooth_snapshot = (
            self.bluetooth_bridge.snapshot()
            if self.bluetooth_bridge is not None
            else {
                "transport": HANDY_TRANSPORT_BROWSER_BLUETOOTH,
                "connected": False,
                "status": "unavailable",
                "message": "Bluetooth bridge is unavailable.",
            }
        )
        result = {
            "relative_speed": int(round(self.last_relative_speed)),
            "physical_speed": int(round(self.last_stroke_speed)),
            "depth": int(round(self.last_depth_pos)),
            "physical_depth": int(round(max(0, min(100, physical_depth)))),
            "position_mm": round(self.FULL_TRAVEL_MM * (max(0.0, min(100.0, physical_depth)) / 100.0), 2),
            "range": int(round(self.last_stroke_range)),
            "min_speed": int(round(self.min_user_speed)),
            "max_speed": int(round(self.max_user_speed)),
            "min_depth": int(round(self.min_handy_depth)),
            "max_depth": int(round(self.max_handy_depth)),
            "calibrated_range": {"min": calibrated_min, "max": calibrated_max},
            "stroke_zone": stroke_zone,
            "full_travel_mm": self.FULL_TRAVEL_MM,
            "slide_bounds": slide_bounds,
            "velocity": self._last_velocity,
            "mode": self._current_mode,
            "hamp_started": self._hamp_started,
            "hsp_streaming": self._hsp_streaming,
            "hsp_stream_id": self._hsp_stream_id,
            "hsp_state_observed_at": (
                round(float(hsp_state_snapshot["observed_at"]), 3)
                if hsp_state_snapshot["observed_at"] is not None
                else None
            ),
            "hsp_state_age_ms": hsp_state_age_ms,
            "hsp_state_source": hsp_state_snapshot["source"],
            "hsp_state_refresh_active": hsp_refresh_active,
            "hsp_state_refresh_attempt_at": (
                round(float(hsp_state_snapshot["refresh_attempt_wall_at"]), 3)
                if hsp_state_snapshot["refresh_attempt_wall_at"] is not None
                else None
            ),
            "hsp_state_refresh_success_at": (
                round(float(hsp_state_snapshot["refresh_success_at"]), 3)
                if hsp_state_snapshot["refresh_success_at"] is not None
                else None
            ),
            "hsp_state_refresh_failures": int(hsp_state_snapshot["refresh_failures"]),
            "hsp_state_refresh_error": hsp_state_snapshot["refresh_error"],
            "hsp_state_refresh_min_interval_ms": int(round(HSP_STATE_REFRESH_MIN_INTERVAL_SECONDS * 1000.0)),
            "hsp_state_sse_active": hsp_sse_active,
            "hsp_state_sse_attempt_at": (
                round(float(self._last_hsp_state_sse_attempt_at), 3)
                if self._last_hsp_state_sse_attempt_at is not None
                else None
            ),
            "hsp_state_sse_connected_at": (
                round(float(self._last_hsp_state_sse_connected_at), 3)
                if self._last_hsp_state_sse_connected_at is not None
                else None
            ),
            "hsp_state_sse_event_at": (
                round(float(self._last_hsp_state_sse_event_at), 3)
                if self._last_hsp_state_sse_event_at is not None
                else None
            ),
            "hsp_state_sse_event_type": self._last_hsp_state_sse_event_type,
            "hsp_state_sse_events": int(self._last_hsp_state_sse_events),
            "hsp_state_sse_failures": int(self._last_hsp_state_sse_failures),
            "hsp_state_sse_error": self._last_hsp_state_sse_error,
            "handy_sse_event_at": (
                round(float(self._last_handy_sse_event_at), 3)
                if self._last_handy_sse_event_at is not None
                else None
            ),
            "handy_sse_event_age_ms": handy_sse_event_age_ms,
            "handy_sse_event_type": (
                self._last_handy_sse_event.get("type", "")
                if isinstance(self._last_handy_sse_event, dict)
                else ""
            ),
            "device_connection_status": self._device_connection_status,
            "device_connection_message": self._device_connection_message,
            "device_connection_observed_at": (
                round(float(self._device_connection_observed_at), 3)
                if self._device_connection_observed_at is not None
                else None
            ),
            "device_connection_age_ms": device_connection_age_ms,
            "device_connection_event_type": self._device_connection_event_type,
            "firmware_version": self.firmware_version,
            "transport_mode": self.transport_mode,
            "bluetooth": bluetooth_snapshot,
            "api_v3_enabled": self.supports_api_v3_control(),
            "api_v3_key_configured": bool(self._effective_api_v3_key()),
            "api_v3_auth_failed": self._api_v3_auth_failed,
            "api_v3_auth_error": self._api_v3_auth_error,
            "api_v3_auth_failed_path": self._api_v3_auth_failed_path,
            "api_v3_unavailable_reason": self.api_v3_unavailable_reason(),
            "continuous_streaming_supported": self.supports_continuous_streaming(),
            "hsp_state": hsp_state_snapshot["state"],
            "last_command": self.last_command_result(),
        }
        if include_recent_events:
            result["handy_sse_event"] = (
                dict(self._last_handy_sse_event)
                if isinstance(self._last_handy_sse_event, dict)
                else None
            )
            result["handy_sse_recent_events"] = [dict(event) for event in self._handy_sse_recent_events]
        if include_history:
            result["command_history"] = self.command_history()
        return result

    def nudge(self, direction, min_depth_pct, max_depth_pct, current_pos_mm):
        JOG_STEP_MM = 2.0
        JOG_VELOCITY_MM_PER_SEC = 20.0
        min_mm = self.FULL_TRAVEL_MM * float(min_depth_pct) / 100.0
        max_mm = self.FULL_TRAVEL_MM * float(max_depth_pct) / 100.0
        
        target_mm = current_pos_mm
        if direction == 'up':
            target_mm = min(current_pos_mm + JOG_STEP_MM, max_mm)
        elif direction == 'down':
            target_mm = max(current_pos_mm - JOG_STEP_MM, min_mm)

        if not self._ensure_hdsp():
            return current_pos_mm
        velocity = self._clamp_absolute_velocity(JOG_VELOCITY_MM_PER_SEC)
        self._send_command(
            "hdsp/xava",
            {"position": target_mm, "velocity": velocity, "stopOnTarget": True},
        )
        return target_mm

    def test_depth_range(self, min_depth_pct, max_depth_pct, velocity_mm_per_sec=55.0, pause_seconds=0.2):
        min_depth_pct = self._safe_percent(min_depth_pct)
        max_depth_pct = self._safe_percent(max_depth_pct)
        low_pct, high_pct = sorted((min_depth_pct, max_depth_pct))
        low_mm = self.FULL_TRAVEL_MM * low_pct / 100.0
        high_mm = self.FULL_TRAVEL_MM * high_pct / 100.0
        velocity = self._clamp_absolute_velocity(velocity_mm_per_sec)

        if not self._ensure_hdsp():
            return {"min_depth": int(round(low_pct)), "max_depth": int(round(high_pct))}

        for position in (low_mm, high_mm, low_mm):
            self._send_command(
                "hdsp/xava",
                {"position": position, "velocity": velocity, "stopOnTarget": True},
            )
            travel_seconds = abs(high_mm - low_mm) / max(1.0, velocity) if position in (high_mm, low_mm) else 0
            time.sleep(max(pause_seconds, travel_seconds + pause_seconds))

        return {"min_depth": int(round(low_pct)), "max_depth": int(round(high_pct))}

    def get_position_mm(self):
        if not self.handy_key:
            return None
        headers = {"X-Connection-Key": self.handy_key}
        try:
            resp = _session_get(f"{self.base_url}slide/position/absolute", headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("position", 0))
        except (requests.exceptions.RequestException, TypeError, ValueError) as e:
            print(f"[HANDY ERROR] Problem reading position: {e}", file=sys.stderr)
            return None

    def mm_to_percent(self, val):
        return int(round((float(val) / self.FULL_TRAVEL_MM) * 100))
