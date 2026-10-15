"""Pure echo-gate logic for the STT feeder (no ROS dependencies).

The robot is half-duplex: while it speaks, its own TTS would be
transcribed back into /prompt (self-talk loop). The gate closes exactly
when synthesis ends (ALTextToSpeech TextDone, see `on_done`) plus a short
tail for room reverb; a time-window estimate per utterance remains only
as a fallback cap, so a lost done-event cannot deafen the feeder
forever. Overlapping speaks are counted. Times are plain float seconds
so this module is testable without ROS.
"""

import re

# Whisper marks non-speech (music, beeps, fan roar) with bracketed tags.
# Publishing those as prompts only churns the bridge for nothing.
_HALLUCINATION_RE = re.compile(r"^\s*(\[[^\]]*\]\s*)+$")


def is_hallucination(text):
    """True when the transcription holds bracketed tags only."""
    clean = (text or "").strip()
    return bool(clean) and _HALLUCINATION_RE.match(clean) is not None


def is_done_event(value):
    """True when a TextDone firing marks end-of-speech.

    Hardware raises the event twice per utterance: falsy at start,
    truthy at end. Only the end closes the gate (closing on start
    would open it for the whole speech).
    """
    return bool(value)


def inhibit_until(now_sec, text, sec_per_char, margin_sec):
    """Return the time until which STT results must be dropped.

    Empty text extends nothing (returns now, never backwards).
    """
    clean = (text or "").strip()
    if not clean:
        return float(now_sec)
    end = float(now_sec) + len(clean) * float(sec_per_char) + float(margin_sec)
    return max(float(now_sec), end)


def capture_window(result_now_sec, audio_time_sec, transcription_time_sec):
    """Approximate [start, end] of the recorded utterance.

    The result carries durations only: the utterance ended when
    transcription began, so end = result time minus transcription time
    and start = end minus audio length. Clamped at zero.
    """
    end = max(
        0.0, float(result_now_sec) - max(0.0, float(transcription_time_sec))
    )
    start = max(0.0, end - max(0.0, float(audio_time_sec)))
    return (start, end)


def overlaps(start_a, end_a, start_b, end_b):
    """True when two time windows share more than an edge."""
    return max(start_a, start_b) < min(end_a, end_b)


class SpeechTracker:
    """Event-driven echo gate with a time-window fallback cap.

    `on_speak` opens inhibition per utterance and returns its fallback
    window (for the recording-overlap check); `on_done` closes it exactly
    once the last in-flight utterance ends, plus a reverb tail. Either the
    exact event or the fallback estimate inhibits, whichever lasts longer.
    """

    def __init__(self, sec_per_char, gate_margin_sec, tail_margin_sec,
                 stuck_timeout_sec=300.0):
        self._sec_per_char = float(sec_per_char)
        self._gate_margin = float(gate_margin_sec)
        self._tail_margin = float(tail_margin_sec)
        self._stuck_timeout = float(stuck_timeout_sec)
        self._inflight = 0
        self._tail_until = 0.0
        self._fallback_until = 0.0
        self._last_change = 0.0

    def on_speak(self, now_sec, text):
        """Open inhibition for one utterance; return its fallback window."""
        now = float(now_sec)
        self._inflight += 1
        self._last_change = now
        end = inhibit_until(now, text, self._sec_per_char, self._gate_margin)
        self._fallback_until = max(self._fallback_until, end)
        return (now, end)

    def on_done(self, now_sec):
        """Close inhibition exactly (TextDone); stray dones are ignored."""
        if self._inflight <= 0:
            return
        now = float(now_sec)
        self._inflight -= 1
        self._last_change = now
        if self._inflight == 0:
            self._tail_until = max(self._tail_until, now + self._tail_margin)

    def inhibited(self, now_sec):
        """True while our speech may still be playing.

        A stuck in-flight count (lost done-events) reaps after the stuck
        timeout, so the feeder degrades to bounded silence instead of
        staying deaf forever. Long utterances below the timeout are
        unaffected: only silence past it resets.
        """
        now = float(now_sec)
        if self._inflight > 0 and now - self._last_change > self._stuck_timeout:
            self._inflight = 0
            self._tail_until = 0.0
        return (
            self._inflight > 0
            or now < self._tail_until
            or now < self._fallback_until
        )
