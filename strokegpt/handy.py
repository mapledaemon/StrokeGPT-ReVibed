import os
import sys
import time
from collections import deque
import requests

MODE_HAMP = 0
MODE_HDSP = 2
MODE_HSP = 4
HANDY_API_V2_BASE_URL = "https://www.handyfeeling.com/api/handy/v2/"
HANDY_API_V3_BASE_URL = "https://www.handyfeeling.com/api/handy-rest/v3/"
HANDY_COMMAND_HISTORY_LIMIT = 60
HANDY_COMMAND_POINTS_PREVIEW = 12
HSP_POINT_MAX = 100
HSP_SERVER_TIME_SYNC_TTL_SECONDS = 300.0
HSP_STREAM_ID_MAX = 4294967295
HSP_STALE_CLOCK_TOLERANCE_MS = 500
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
    ):
        self.handy_key = handy_key
        self.base_url = self._normalize_base_url(base_url)
        self.firmware_version = self._normalize_firmware_version(firmware_version)
        env_api_v3_application_id = (
            os.getenv("STROKEGPT_HANDY_API_V3_APPLICATION_ID", "")
            or os.getenv("STROKEGPT_HANDY_API_KEY", "")
        )
        self.api_v3_key = str(
            api_v3_key if api_v3_key is not None else env_api_v3_application_id or ""
        ).strip()
        self.api_v3_base_url = self._normalize_base_url(
            os.getenv("STROKEGPT_HANDY_API_V3_BASE_URL", api_v3_base_url) or HANDY_API_V3_BASE_URL
        )
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
        self._server_time_offset_ms = None
        self._server_time_synced_at = 0.0

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

    def set_api_key(self, key):
        if key != self.handy_key or self._api_v3_auth_failed:
            self._current_mode = None
            self._hamp_started = False
            self._hsp_streaming = False
            self._api_v3_auth_failed = False
            self._api_v3_auth_error = ""
            self._api_v3_auth_failed_path = ""
            self._hsp_stream_id = 0
            self._last_hsp_state = None
            self._server_time_offset_ms = None
            self._server_time_synced_at = 0.0
            self._reset_motion_cache()
        self.handy_key = key

    def set_handy_api_key(self, key):
        # Compatibility shim - do not extend. The persisted setting name says
        # "key", but API v3 HSP uses a public Application ID in X-Api-Key.
        cleaned = str(key or "").strip()
        if cleaned != self.api_v3_key or self._api_v3_auth_failed:
            self._current_mode = None
            self._hamp_started = False
            self._hsp_streaming = False
            self._api_v3_auth_failed = False
            self._api_v3_auth_error = ""
            self._api_v3_auth_failed_path = ""
            self._hsp_stream_id = 0
            self._last_hsp_state = None
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
            self._last_hsp_state = None
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
        for key in ("result", "data", "state", "hsp_state", "hspState"):
            value = payload.get(key)
            if isinstance(value, dict):
                candidates.append(value)
        candidates.append(payload)
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
        return {}

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
                self._last_hsp_state = dict(hsp_state)
        if error:
            result["error"] = str(error)[:180]
        self._last_command_result = result
        self._command_history.append(result)

    def last_command_result(self):
        return dict(self._last_command_result) if self._last_command_result else None

    def command_history(self):
        return [dict(command) for command in self._command_history]

    def _send_command(self, path, body=None):
        if not self.handy_key:
            self._record_command_result(path, body, ok=False, error="missing Handy key")
            return False
        headers = {"Content-Type": "application/json", "X-Connection-Key": self.handy_key}
        return self._send_put(self.base_url, path, body, headers=headers)

    def _send_v3_command(self, path, body=None):
        if not self.handy_key:
            self._record_command_result(path, body, ok=False, error="missing Handy key")
            return False
        api_key = self._effective_api_v3_key()
        if not api_key:
            self._record_command_result(path, body, ok=False, error="missing Handy API v3 Application ID")
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

    def _effective_api_v3_key(self):
        return str(self.api_v3_key or "").strip()

    def _disable_api_v3_control(self, *, path="", error=""):
        self._api_v3_auth_failed = True
        self._api_v3_auth_error = str(error or "API v3 authentication failed")[:180]
        self._api_v3_auth_failed_path = str(path or "")[:80]
        self._current_mode = None
        self._hamp_started = False
        self._hsp_streaming = False
        self._hsp_stream_id = 0
        self._last_hsp_state = None
        self._server_time_offset_ms = None
        self._server_time_synced_at = 0.0
        self._reset_motion_cache()

    def supports_api_v3_control(self):
        return bool(
            self.firmware_version == "fw4"
            and self.handy_key
            and self._effective_api_v3_key()
            and not self._api_v3_auth_failed
        )

    def api_v3_unavailable_reason(self):
        if self.firmware_version != "fw4":
            return "firmware_v3_legacy"
        if not self.handy_key:
            return "missing_connection_key"
        if not self._effective_api_v3_key():
            return "missing_api_v3_key"
        if self._api_v3_auth_failed:
            return "api_v3_auth_failed"
        return ""

    def _send_put(self, base_url, path, body=None, *, headers):
        started_at = time.monotonic()
        response = None
        try:
            response = requests.put(f"{base_url}{path}", headers=headers, json=body or {}, timeout=10)
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
            )
            print(f"[HANDY ERROR] Problem: {e}", file=sys.stderr)
            return False

    def check_connection(self):
        """Probe the current Handy key without starting motion."""
        path = "slide/position/absolute"
        if not self.handy_key:
            self._record_command_result(path, ok=False, error="missing Handy key")
            return {
                "status": "error",
                "connected": False,
                "message": "Handy connection key is missing.",
                "last_command": self.last_command_result(),
            }

        headers = {"X-Connection-Key": self.handy_key}
        started_at = time.monotonic()
        response = None
        try:
            response = requests.get(f"{self.base_url}{path}", headers=headers, timeout=10)
            response.raise_for_status()
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            self._record_command_result(
                path,
                ok=True,
                status_code=getattr(response, "status_code", None),
                elapsed_ms=elapsed_ms,
            )
            result = {
                "status": "connected",
                "connected": True,
                "message": "Connected to Handy.",
                "last_command": self.last_command_result(),
            }
            try:
                data = response.json()
                if isinstance(data, dict) and data.get("position") is not None:
                    result["position_mm"] = float(data["position"])
            except (TypeError, ValueError, AttributeError):
                pass
            return result
        except requests.exceptions.RequestException as e:
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            error_response = getattr(e, "response", None) or response
            self._record_command_result(
                path,
                ok=False,
                status_code=getattr(error_response, "status_code", None),
                elapsed_ms=elapsed_ms,
                error=e,
            )
            print(f"[HANDY ERROR] Connection check failed: {e}", file=sys.stderr)
            return {
                "status": "error",
                "connected": False,
                "message": f"Handy connection failed: {e}",
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
            response = requests.get(f"{self.api_v3_base_url}servertime", timeout=5)
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

    def _estimated_server_time_ms(self):
        offset_age = time.monotonic() - float(self._server_time_synced_at or 0.0)
        if self._server_time_offset_ms is None or offset_age > HSP_SERVER_TIME_SYNC_TTL_SECONDS:
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
        relative_speed_pct = self._safe_percent(speed)
        speed_range_width = self.max_user_speed - self.min_user_speed
        velocity = self.min_user_speed + (speed_range_width * (relative_speed_pct / 100.0))
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

    def _velocity_to_v3_ratio(self, velocity):
        try:
            velocity = float(velocity)
        except (TypeError, ValueError):
            velocity = 0.0
        return round(max(0.0, min(1.0, velocity / 100.0)), 4)

    def _relative_depth_to_mm(self, depth):
        absolute_pos_pct = self._relative_depth_to_physical_percent(depth)
        return self.FULL_TRAVEL_MM * (absolute_pos_pct / 100.0)

    def _relative_depth_to_physical_percent(self, depth):
        relative_pos_pct = self._safe_percent(depth)
        calibrated_width = self.max_handy_depth - self.min_handy_depth
        return self.min_handy_depth + calibrated_width * (relative_pos_pct / 100.0)

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
        if not self.handy_key:
            self._record_command_result("hamp/move", ok=False, error="missing Handy key")
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

        # Set slide range based on depth and stroke_range
        relative_pos_pct = self._safe_percent(depth)
        absolute_center_pct = self.min_handy_depth + (self.max_handy_depth - self.min_handy_depth) * (relative_pos_pct / 100.0)
        calibrated_range_width = self.max_handy_depth - self.min_handy_depth
        
        relative_range_pct = self._safe_percent(stroke_range)
        span_abs = (calibrated_range_width * (relative_range_pct / 100.0)) / 2.0
        
        min_zone_abs = absolute_center_pct - span_abs
        max_zone_abs = absolute_center_pct + span_abs
        
        clamped_min_zone = max(self.min_handy_depth, min_zone_abs)
        clamped_max_zone = min(self.max_handy_depth, max_zone_abs)
        
        slide_min = round(100 - clamped_max_zone)
        slide_max = round(100 - clamped_min_zone)

        slide_min, slide_max = self._normalize_slide_bounds(slide_min, slide_max)

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
        if not self.handy_key:
            self._record_command_result("hdsp/xava", ok=False, error="missing Handy key")
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
            velocity = max(
                self.min_absolute_user_speed,
                min(self.max_absolute_velocity_for_relative_speed(relative_speed_pct), int(round(velocity))),
            )
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
            self._record_command_result("hsp/setup", ok=False, error="Handy firmware v4 and connection key required")
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

    def _send_hsp_threshold(self, tail_point_threshold):
        if tail_point_threshold is None:
            return True
        try:
            threshold = max(0, int(tail_point_threshold))
        except (TypeError, ValueError):
            return True
        return self._send_v3_command("hsp/threshold", {"tail_point_threshold": threshold})

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

    def _hsp_state_clock_is_past_points(self, points):
        state = self._last_hsp_state if isinstance(self._last_hsp_state, dict) else None
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
        body = {
            "start_time": max(0, int(round(start_time_ms))),
            "server_time": self._estimated_server_time_ms(),
            "playback_rate": 1.0,
            "pause_on_starving": False,
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
        add = {
            "points": stream_points[:100],
            "flush": True,
            "tail_point_stream_index": max(1, tail_index),
        }
        if not self._send_v3_command("hsp/add", add):
            return False
        add_result = self._last_command_result
        if not self._send_hsp_threshold(tail_point_threshold) and self._api_v3_auth_failed:
            return False
        if replace_active_stream:
            restarted = self._restart_hsp_if_clock_is_stale(stream_points, start_time_ms)
            if restarted is False:
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
    ):
        stream_points = self._stream_points_body(points)
        if not stream_points:
            return True
        body = {
            "points": stream_points[:100],
            "flush": False,
            "tail_point_stream_index": max(1, int(tail_point_stream_index)),
        }
        if not self._send_v3_command("hsp/add", body):
            return False
        add_result = self._last_command_result
        if not self._send_hsp_threshold(tail_point_threshold) and self._api_v3_auth_failed:
            return False
        restarted = self._restart_hsp_if_clock_is_stale(stream_points)
        if restarted is False:
            return False
        if add_result is not None and restarted is not True:
            self._last_command_result = add_result
        self._hsp_streaming = True
        return True

    def sync_continuous_stream_time(self, current_time_ms, *, filter=0.5):
        if not self.supports_continuous_streaming():
            self._record_command_result("hsp/synctime", ok=False, error="Handy firmware v4 and connection key required")
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

    def diagnostics(self):
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
            physical_depth = self._relative_depth_to_physical_percent(self.last_depth_pos)
            calibrated_range_width = self.max_handy_depth - self.min_handy_depth
            span = (calibrated_range_width * (self._safe_percent(self.last_stroke_range) / 100.0)) / 2.0
            stroke_zone = {
                "min": int(round(max(self.min_handy_depth, physical_depth - span))),
                "max": int(round(min(self.max_handy_depth, physical_depth + span))),
            }
        physical_depth = self._relative_depth_to_physical_percent(self.last_depth_pos)
        calibrated_min = max(0, min(100, int(round(min(self.min_handy_depth, self.max_handy_depth)))))
        calibrated_max = max(0, min(100, int(round(max(self.min_handy_depth, self.max_handy_depth)))))
        return {
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
            "firmware_version": self.firmware_version,
            "api_v3_enabled": self.supports_api_v3_control(),
            "api_v3_key_configured": bool(self._effective_api_v3_key()),
            "api_v3_auth_failed": self._api_v3_auth_failed,
            "api_v3_auth_error": self._api_v3_auth_error,
            "api_v3_auth_failed_path": self._api_v3_auth_failed_path,
            "api_v3_unavailable_reason": self.api_v3_unavailable_reason(),
            "continuous_streaming_supported": self.supports_continuous_streaming(),
            "hsp_state": dict(self._last_hsp_state) if isinstance(self._last_hsp_state, dict) else None,
            "last_command": self.last_command_result(),
            "command_history": self.command_history(),
        }

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
        self._send_command(
            "hdsp/xava",
            {"position": target_mm, "velocity": JOG_VELOCITY_MM_PER_SEC, "stopOnTarget": True},
        )
        return target_mm

    def test_depth_range(self, min_depth_pct, max_depth_pct, velocity_mm_per_sec=55.0, pause_seconds=0.2):
        min_depth_pct = self._safe_percent(min_depth_pct)
        max_depth_pct = self._safe_percent(max_depth_pct)
        low_pct, high_pct = sorted((min_depth_pct, max_depth_pct))
        low_mm = self.FULL_TRAVEL_MM * low_pct / 100.0
        high_mm = self.FULL_TRAVEL_MM * high_pct / 100.0
        velocity = max(5.0, float(velocity_mm_per_sec))

        if not self._ensure_hdsp():
            return {"min_depth": int(round(low_pct)), "max_depth": int(round(high_pct))}

        for position in (low_mm, high_mm, low_mm):
            self._send_command(
                "hdsp/xava",
                {"position": position, "velocity": velocity, "stopOnTarget": True},
            )
            travel_seconds = abs(high_mm - low_mm) / velocity if position in (high_mm, low_mm) else 0
            time.sleep(max(pause_seconds, travel_seconds + pause_seconds))

        return {"min_depth": int(round(low_pct)), "max_depth": int(round(high_pct))}

    def get_position_mm(self):
        if not self.handy_key:
            return None
        headers = {"X-Connection-Key": self.handy_key}
        try:
            resp = requests.get(f"{self.base_url}slide/position/absolute", headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("position", 0))
        except (requests.exceptions.RequestException, TypeError, ValueError) as e:
            print(f"[HANDY ERROR] Problem reading position: {e}", file=sys.stderr)
            return None

    def mm_to_percent(self, val):
        return int(round((float(val) / self.FULL_TRAVEL_MM) * 100))
