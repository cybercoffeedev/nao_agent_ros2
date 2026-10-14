"""Matrix for the pure echo-gate logic (no ROS needed)."""

from nao_agent.stt.gate import (
    capture_window,
    inhibit_until,
    is_hallucination,
    is_inhibited,
    overlaps,
)


def test_speech_extends_inhibit_window():
    assert inhibit_until(10.0, "abc", 1.0, 2.0) == 15.0


def test_empty_text_extends_nothing():
    assert inhibit_until(10.0, "   ", 1.0, 2.0) == 10.0
    assert inhibit_until(10.0, "", 1.0, 2.0) == 10.0


def test_inhibit_boundary():
    assert is_inhibited(14.9, 15.0) is True
    assert is_inhibited(15.0, 15.0) is False
    assert is_inhibited(99.0, 0.0) is False


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
