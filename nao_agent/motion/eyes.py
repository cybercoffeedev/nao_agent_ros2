"""Thinking-eyes animation over ALLeds (ported from nao-agent RobotEyes).

Shows a rotating comet over the 8 FaceLeds while the LLM thinks, so the
robot looks alive during the (slow, CPU-only) inference. Stopping
(empty mode) restores full LEDs.

Owns no qi session: constructed with an ALLeds proxy (plus the optional
autonomous-blinking proxy) by the caller, usually motion_server_node.
"""

import threading
import time

EYES_SERVICE = "/nao_agent/set_eyes"

THINKING_MODE = "thinking"
LISTENING_MODE = "listening"
# Turquoise marker while listening (same hue the old nao-agent used).
TURQUOISE_HEX = 0x0000FFFF
TICK_SEC = 0.1
FACE_LEDS_COUNT = 8
LED_INTENSITIES = (1.0, 0.6, 0.2, 0.0)


class Eyes:
    """Background FaceLed animation; at most one mode at a time."""

    def __init__(self, leds, blinking=None, on_error=None) -> None:
        self._leds = leds
        # Called once with the first background write failure (never spams);
        # lets the caller surface silent NAOqi errors in its own logs.
        self._on_error = on_error
        self._error_logged = False
        try:
            if blinking is not None:
                blinking.setEnabled(False)
        except Exception:  # noqa: BLE001 - sim may lack the service
            pass
        self._led_names = [f"FaceLed{i}" for i in range(FACE_LEDS_COUNT)]
        self._lock = threading.Lock()
        self._mode = None
        self._thread = None

    def set(self, mode) -> bool:
        """Switch animation mode; empty/None stops and restores full LEDs."""
        mode = (mode or "").strip() or None
        if mode is not None and mode not in (THINKING_MODE, LISTENING_MODE):
            return False
        with self._lock:
            self._mode = mode
            self._step = 0
            self._applied = False
            if mode is not None and (
                self._thread is None or not self._thread.is_alive()
            ):
                self._thread = threading.Thread(target=self._loop, daemon=True)
                self._thread.start()
        if mode is None:
            self._join()
            try:
                self._leds.setIntensity("FaceLeds", 1.0)
            except Exception:  # noqa: BLE001 - best effort
                pass
        return True

    def _join(self) -> None:
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0 * TICK_SEC)

    def _loop(self) -> None:
        while True:
            with self._lock:
                mode = self._mode
                if mode is None:
                    return
                if mode == THINKING_MODE:
                    step = self._step
                    self._step += 1
                    listening = False
                else:
                    applied = self._applied
                    self._applied = True
                    listening = True
            try:
                if listening:
                    # Solid marker, applied once (fade persists on its own).
                    if not applied:
                        self._leds.fadeRGB("FaceLeds", TURQUOISE_HEX, 0.5)
                else:
                    for i, intensity in enumerate(LED_INTENSITIES):
                        self._leds.setIntensity(
                            self._led_names[(step - i) % FACE_LEDS_COUNT], intensity
                        )
            except Exception as e:  # noqa: BLE001 - keep animating through blips
                if self._on_error is not None and not self._error_logged:
                    self._error_logged = True
                    try:
                        self._on_error(f"Eyes animation write failed: {e}")
                    except Exception:
                        pass
            time.sleep(TICK_SEC)
