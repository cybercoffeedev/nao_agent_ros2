"""Matrix for the pure echo-gate logic (no ROS needed)."""

from nao_agent.stt.gate import (
    SpeechTracker,
    capture_window,
    inhibit_until,
    is_done_event,
    is_hallucination,
    overlaps,
)


def test_speech_extends_inhibit_window():
    assert inhibit_until(10.0, "abc", 1.0, 2.0) == 15.0


def test_empty_text_extends_nothing():
    assert inhibit_until(10.0, "   ", 1.0, 2.0) == 10.0
    assert inhibit_until(10.0, "", 1.0, 2.0) == 10.0


def test_tracker_window_boundary():
    tracker = SpeechTracker(1.0, 2.0, 0.5)
    assert tracker.on_speak(10.0, "abc") == (10.0, 15.0)
    assert tracker.inhibited(14.9) is True
    tracker.on_done(14.0)
    assert tracker.inhibited(14.9) is True  # fallback outlasts the tail
    assert tracker.inhibited(15.0) is False
    assert tracker.inhibited(99.0) is False


def test_longer_text_holds_longer():
    short = inhibit_until(0.0, "hi", 0.1, 0.0)
    long = inhibit_until(0.0, "hello robot, how are you today", 0.1, 0.0)
    assert long > short


def test_capture_window_math():
    # Result at t=10, 1.5 s of audio transcribed in 0.5 s.
    assert capture_window(10.0, 1.5, 0.5) == (8.0, 9.5)
    # Clamped, never negative.
    assert capture_window(1.0, 5.0, 5.0) == (0.0, 0.0)


def test_overlap_cases():
    assert overlaps(8.0, 9.5, 7.0, 8.5) is True
    assert overlaps(8.0, 9.5, 9.0, 12.0) is True
    assert overlaps(1.0, 2.0, 5.0, 6.0) is False
    # Touching edges do not overlap.
    assert overlaps(1.0, 2.0, 2.0, 3.0) is False


def test_self_speech_dropped_by_overlap():
    # Robot spoke 5.0-9.0; utterance recorded 8.0-9.5 overlaps it.
    start, end = capture_window(10.0, 1.5, 0.5)
    assert overlaps(start, end, 5.0, 9.0) is True
    # User spoke 12.0-13.0, robot silent since 9.0: clean.
    assert overlaps(12.0, 13.0, 5.0, 9.0) is False


def test_bracketed_tags_are_hallucinations():
    assert is_hallucination("[muzyka]") is True
    assert is_hallucination("  [cisza] [szum] ") is True
    assert is_hallucination("") is False
    assert is_hallucination("Cześć, jak się masz?") is False
    assert is_hallucination("Rano padał [deszcz] i było zimno") is False


def test_done_event_marks_end_only():
    assert is_done_event(True) is True
    assert is_done_event(1) is True
    assert is_done_event(False) is False
    assert is_done_event(0) is False
    assert is_done_event(None) is False


def test_tracker_closes_exactly_on_done():
    tracker = SpeechTracker(0.01, 0.0, 0.5)
    tracker.on_speak(0.0, "long poem")
    assert tracker.inhibited(5.0) is True
    tracker.on_done(6.0)
    assert tracker.inhibited(6.4) is True  # reverb tail
    assert tracker.inhibited(6.6) is False  # exact close, not fallback


def test_tracker_counts_overlapping_speaks():
    tracker = SpeechTracker(0.01, 0.0, 0.5)
    tracker.on_speak(0.0, "one")
    tracker.on_speak(1.0, "two")
    tracker.on_done(2.0)
    assert tracker.inhibited(2.2) is True  # one still in flight
    tracker.on_done(3.0)
    assert tracker.inhibited(3.4) is True
    assert tracker.inhibited(3.6) is False


def test_tracker_survives_stray_done_and_caps_fallback():
    tracker = SpeechTracker(1.0, 2.0, 0.5)
    tracker.on_done(5.0)  # no speak: ignored, never negative
    assert tracker.inhibited(5.2) is False
    tracker.on_speak(10.0, "abc")
    tracker.on_done(20.0)
    assert tracker.inhibited(99.0) is False  # fallback cap, not forever


def test_tracker_reaps_stuck_count():
    tracker = SpeechTracker(1.0, 2.0, 0.5, stuck_timeout_sec=300.0)
    tracker.on_speak(0.0, "hi")  # done-events lost from here on
    tracker.on_speak(1.0, "yo")
    assert tracker.inhibited(4.9) is True
    assert tracker.inhibited(400.0) is False  # reaped, hears again
    assert tracker.inhibited(401.0) is False  # stays reaped
