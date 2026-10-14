"""Tests for the thinking-eyes animator with fake ALLeds (no robot)."""

import time

from nao_agent.motion.eyes import EYES_SERVICE, Eyes, LED_INTENSITIES


class FakeLeds:
    def __init__(self):
        self.calls = []

    def setIntensity(self, name, value):
        self.calls.append((name, value))

    def fadeRGB(self, name, color, duration):
        self.calls.append((name, color, duration))


class FakeBlink:
    def __init__(self):
        self.enabled_calls = []

    def setEnabled(self, value):
        self.enabled_calls.append(value)


def test_init_disables_autonomous_blinking():
    leds, blink = FakeLeds(), FakeBlink()
    Eyes(leds, blink)
    assert blink.enabled_calls == [False]


def test_thinking_rotates_comet():
    leds = FakeLeds()
    eyes = Eyes(leds)
    assert eyes.set("thinking") is True
    time.sleep(0.35)
    assert eyes.set("") is True
    ticks = [c for c in leds.calls if c[0].startswith("FaceLed")]
    assert len(ticks) >= 2 * len(LED_INTENSITIES)
    first = ticks[: len(LED_INTENSITIES)]
    assert [name for name, _ in first] == [f"FaceLed{(0 - i) % 8}" for i in range(4)]
    assert [value for _, value in first] == list(LED_INTENSITIES)


def test_stop_restores_full_leds_and_ends_thread():
    leds = FakeLeds()
    eyes = Eyes(leds)
    eyes.set("thinking")
    time.sleep(0.15)
    assert eyes.set("") is True
    assert leds.calls[-1] == ("FaceLeds", 1.0)
    thread = eyes._thread
    assert thread is None or not thread.is_alive()


def test_unknown_mode_rejected():
    leds = FakeLeds()
    eyes = Eyes(leds)
    assert eyes.set("rainbow") is False
    assert leds.calls == []
    assert eyes._thread is None


def test_double_start_keeps_single_thread():
    leds = FakeLeds()
    eyes = Eyes(leds)
    eyes.set("thinking")
    first = eyes._thread
    eyes.set("thinking")
    time.sleep(0.15)
    assert eyes._thread is first
    eyes.set("")


def test_eyes_service_name():
    assert EYES_SERVICE == "/nao_agent/set_eyes"


class FailingLeds:
    def setIntensity(self, name, value):
        raise RuntimeError("nope")


def test_loop_reports_first_write_error_once():
    errors = []
    eyes = Eyes(FailingLeds(), on_error=errors.append)
    assert eyes.set("thinking") is True
    time.sleep(0.35)
    assert eyes.set("") is True
    assert len(errors) == 1
    assert "nope" in errors[0]
