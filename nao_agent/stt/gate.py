"""Pure echo-gate logic for the STT feeder (no ROS dependencies).

The robot is half-duplex: while it speaks, its own TTS would be
transcribed back into /prompt (self-talk loop). The feeder deafens itself
from each /speech message until the utterance plausibly ends. Times are
plain float seconds so this module is testable without ROS.
"""

import re

# Whisper marks non-speech (music, beeps, fan roar) with bracketed tags.
# Publishing those as prompts only churns the bridge for nothing.
_HALLUCINATION_RE = re.compile(r"^\s*(\[[^\]]*\]\s*)+$")


def is_hallucination(text):
    """True when the transcription holds bracketed tags only."""
    clean = (text or "").strip()
    return bool(clean) and _HALLUCINATION_RE.match(clean) is not None


def inhibit_until(now_sec, text, sec_per_char, margin_sec):
    """Return the time until which STT results must be dropped.

    Empty text extends nothing (returns now, never backwards).
    """
    clean = (text or "").strip()
    if not clean:
        return float(now_sec)
    end = float(now_sec) + len(clean) * float(sec_per_char) + float(margin_sec)
    return max(float(now_sec), end)


def is_inhibited(now_sec, until_sec):
    """True while a previous utterance may still be playing."""
    return float(now_sec) < float(until_sec)


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
