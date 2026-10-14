"""Matrix for the pure prompt builder (no ROS needed)."""

from nao_agent.llm.prompts import (
    TRUNCATION_MARKER,
    build_messages,
    clip_text,
    sanitize_history,
)


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
    msgs = build_messages(
        "  sys  ", "  hi  ", [("user", "  q  "), ("assistant", "  a  ")]
    )
    assert [m["content"] for m in msgs] == ["sys", "q", "a", "hi"]


def test_dangling_user_dropped():
    assert sanitize_history([("user", "q1")]) == []
    msgs = build_messages("sys", "q2", [("user", "q1")])
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("system", "sys"),
        ("user", "q2"),
    ]


def test_consecutive_users_repaired():
    history = [("user", "q1"), ("user", "q2"), ("assistant", "a2")]
    assert sanitize_history(history) == [("user", "q1"), ("assistant", "a2")]
    roles = [m["role"] for m in build_messages("sys", "q3", history)]
    assert roles == ["system", "user", "assistant", "user"]


def test_leading_assistant_and_unknown_roles_skipped():
    history = [
        ("assistant", "stray"),
        ("unknown", "x"),
        ("user", "q1"),
        ("assistant", "a1"),
    ]
    assert sanitize_history(history) == [("user", "q1"), ("assistant", "a1")]


def test_valid_pairs_untouched():
    history = [("user", "q1"), ("assistant", "a1"), ("user", "q2")]
    # Trailing user is dangling (no reply yet); the completed pair stays.
    assert sanitize_history(history) == [("user", "q1"), ("assistant", "a1")]
    history_ok = [("user", "q1"), ("assistant", "a1")]
    assert sanitize_history(history_ok) == history_ok


def test_built_roles_always_alternate():
    histories = [
        None,
        [],
        [("user", "q1")],
        [("user", "q1"), ("user", "q2")],
        [("assistant", "a0"), ("user", "q1"), ("assistant", "a1")],
        [("user", "q1"), ("assistant", "a1"), ("user", "q2")],
    ]
    for history in histories:
        roles = [m["role"] for m in build_messages("sys", "new", history)]
        assert roles[0] == "system"
        assert roles[1] == "user"
        assert roles[-1] == "user"
        for prev, cur in zip(roles[1:], roles[2:]):
            assert (prev, cur) in [("user", "assistant"), ("assistant", "user")]


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
