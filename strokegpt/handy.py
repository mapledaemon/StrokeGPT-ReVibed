import sys
import time
import requests

MODE_HAMP = 0
MODE_HDSP = 2

class HandyController:
    def __init__(self, handy_key="", base_url="https://www.handyfeeling.com/api/handy/v2/"):
        self.handy_key = handy_key
        self.base_url = base_url
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
        self._last_slide_bounds = None
        self._last_velocity = None
        self._last_command_result = None

    def set_api_key(self, key):
        if key != self.handy_key:
            self._current_mode = None
            self._hamp_started = False
            self._reset_motion_cache()
        self.handy_key = key

    def update_settings(self, min_speed, max_speed, min_depth, max_depth):
        self.min_user_speed = min_speed
        self.max_user_speed = max_speed
        self.min_handy_depth = min_depth
        self.max_handy_depth = max_depth
        self._reset_motion_cache()

    def _reset_motion_cache(self):
        self._last_slide_bounds = None
        self._last_velocity = None

    def _safe_command_body(self, body):
        if not isinstance(body, dict):
            return {}
        result = {}
        for key in ("mode", "min", "max", "position", "velocity", "stopOnTarget"):
            if key in body:
                result[key] = body[key]
        return result

    def _record_command_result(self, path, body=None, *, ok, status_code=None, elapsed_ms=None, error=""):
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
        if error:
            result["error"] = str(error)[:180]
        self._last_command_result = result

    def last_command_result(self):
        return dict(self._last_command_result) if self._last_command_result else None

    def _send_command(self, path, body=None):
        if not self.handy_key:
            self._record_command_result(path, body, ok=False, error="missing Handy key")
            return False
        headers = {"Content-Type": "application/json", "X-Connection-Key": self.handy_key}
        started_at = time.monotonic()
        response = None
        try:
            response = requests.put(f"{self.base_url}{path}", headers=headers, json=body or {}, timeout=10)
            response.raise_for_status()
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            self._record_command_result(
                path,
                body,
                ok=True,
                status_code=getattr(response, "status_code", None),
                elapsed_ms=elapsed_ms,
            )
            return True
        except requests.exceptions.RequestException as e:
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            error_response = getattr(e, "response", None) or response
            self._record_command_result(
                path,
                body,
                ok=False,
                status_code=getattr(error_response, "status_code", None),
                elapsed_ms=elapsed_ms,
                error=e,
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
        if self._current_mode != MODE_HAMP:
            if not self._send_command("mode", {"mode": MODE_HAMP}):
                return False
            self._current_mode = MODE_HAMP
            self._hamp_started = False
            self._reset_motion_cache()
        if not self._hamp_started:
            if not self._send_command("hamp/start"):
                return False
            self._hamp_started = True
        return True

    def _ensure_hdsp(self):
        if self._hamp_started:
            if not self._send_command("hamp/stop"):
                return False
            self._hamp_started = False
            self._reset_motion_cache()
        if self._current_mode != MODE_HDSP:
            if not self._send_command("mode", {"mode": MODE_HDSP}):
                return False
            self._current_mode = MODE_HDSP
            self._reset_motion_cache()
        return True

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

    def max_velocity_for_relative_speed(self, speed):
        return min(self.max_user_speed, self._relative_speed_to_velocity(speed))

    def _relative_depth_to_mm(self, depth):
        absolute_pos_pct = self._relative_depth_to_physical_percent(depth)
        return self.FULL_TRAVEL_MM * (absolute_pos_pct / 100.0)

    def _relative_depth_to_physical_percent(self, depth):
        relative_pos_pct = self._safe_percent(depth)
        calibrated_width = self.max_handy_depth - self.min_handy_depth
        return self.min_handy_depth + calibrated_width * (relative_pos_pct / 100.0)

    def velocity_for_depth_interval(self, speed, start_depth, end_depth, duration_seconds):
        max_velocity = self.max_velocity_for_relative_speed(speed)
        try:
            duration_seconds = float(duration_seconds)
        except (TypeError, ValueError):
            duration_seconds = 0.0
        if duration_seconds <= 0:
            return max_velocity

        distance_mm = abs(self._relative_depth_to_mm(end_depth) - self._relative_depth_to_mm(start_depth))
        planned_velocity = int(round(distance_mm / duration_seconds))
        planned_velocity = max(self.min_user_speed, planned_velocity)
        return min(max_velocity, planned_velocity)

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

    def move_to_depth(self, speed, depth, *, stop_on_target=True, velocity=None):
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
        relative_pos_pct = self._safe_percent(depth)
        if velocity is None:
            velocity = self.max_velocity_for_relative_speed(relative_speed_pct)
        else:
            velocity = max(
                self.min_user_speed,
                min(self.max_velocity_for_relative_speed(relative_speed_pct), int(round(velocity))),
            )
        position = self._relative_depth_to_mm(relative_pos_pct)
        body = {"position": position, "velocity": velocity, "stopOnTarget": bool(stop_on_target)}
        if not self._send_command("hdsp/xava", body):
            return False

        self._current_mode = MODE_HDSP
        self.last_stroke_speed = velocity
        self.last_relative_speed = relative_speed_pct
        self.last_depth_pos = int(round(relative_pos_pct))
        return True

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
        if self._send_command("slide", {"min": slide_min, "max": slide_max}):
            self._last_slide_bounds = bounds
            return True
        return False

    def _send_velocity(self, velocity):
        if velocity == self._last_velocity:
            return True
        if self._send_command("hamp/velocity", {"velocity": velocity}):
            self._last_velocity = velocity
            return True
        return False

    def stop(self):
        """Stops all movement."""
        if self._current_mode != MODE_HAMP:
            if self._send_command("mode", {"mode": MODE_HAMP}):
                self._current_mode = MODE_HAMP
        stopped = self._send_command("hamp/stop")
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
            "last_command": self.last_command_result(),
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
