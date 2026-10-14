"""Matrix for the pure STT audio shaping (no ROS needed)."""

import pytest

from nao_agent.stt.audio import (
    TARGET_RATE,
    decimate,
    select_front_mono,
    shape_for_stt,
)


def test_front_pair_averaged_per_frame():
    # channel_map [rear-L, rear-R, front-L, front-R]: only front pair counts.
    data = [100, 200, 10, 30, 100, 200, 50, 70]
    assert select_front_mono(data, [3, 5, 0, 2]) == [20, 60]


def test_fallback_averages_all_without_front():
    assert select_front_mono([10, 20, 30, 40], [3, 5]) == [15, 35]


def test_empty_and_ragged_input():
    assert select_front_mono([], [0, 2]) == []
    assert select_front_mono([1, 2], []) == []
    # Trailing partial frame is dropped, never fabricated.
    assert select_front_mono([10, 30, 99], [0, 2]) == [20]


def test_decimate_48k_to_16k_boxcar():
    assert decimate([9, 9, 9, 0, 0, 0], 48000, 16000) == [9, 0]
    assert TARGET_RATE == 16000


def test_decimate_rejects_non_integer_ratio():
    with pytest.raises(ValueError):
        decimate([1, 2, 3], 44100, 16000)
    with pytest.raises(ValueError):
        decimate([1, 2], 8000, 16000)


def test_full_path_clamps_int16():
    shaped = shape_for_stt([0, 0, 30000, 30000] * 3, [3, 5, 0, 2], 48000)
    assert shaped == [30000]
    shaped = shape_for_stt([0, 0, 32767, 32767] * 3, [3, 5, 0, 2], 48000)
    assert all(-32768 <= v <= 32767 for v in shaped)
