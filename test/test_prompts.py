"""Matrix for the pure prompt builder (no ROS needed)."""

from nao_agent.llm.prompts import TRUNCATION_MARKER, build_messages, clip_text


def test_no_history_backward_compatible():
    assert build_messages("sys", "hi") == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ]


def test_history_order_system_then_oldest_first():
    history = [("user", "old q"), ("assistant", "old a")]
    assert build_messages("sys", "new q", history) == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old q"},
        {"role": "assistant", "content": "old a"},
        {"role": "user", "content": "new q"},
    ]


def test_empty_history_same_as_none():
    assert build_messages("sys", "hi", []) == build_messages("sys", "hi")


def test_inputs_are_stripped():
    msgs = build_messages("  sys  ", "  hi  ", [("user", "  q  ")])
    assert [m["content"] for m in msgs] == ["sys", "q", "hi"]


def test_clip_short_text_unchanged():
    assert clip_text("hello", 500) == "hello"
    assert clip_text("  hello  ", 500) == "hello"


def test_clip_long_text_marked():
    assert clip_text("abcdef", 4) == "abcd" + TRUNCATION_MARKER


def test_clip_non_positive_limit_disables():
    assert clip_text("abcdef", 0) == "abcdef"
    assert clip_text("abcdef", -1) == "abcdef"


def test_clip_empty():
    assert clip_text("", 500) == ""
    assert clip_text(None, 500) == ""
