"""Envelope parser matrix (pure logic, no ROS needed)."""

import pytest

from nao_agent.response.parser import EnvelopeError, Response, parse_envelope


def test_sequence_parsed_in_order():
    r = parse_envelope(
        '{"actions": [{"name": "stand_up"}, '
        '{"name": "speak", "text": "Wstałem."}, '
        '{"name": "sit_down"}]}'
    )
    assert isinstance(r, Response)
    assert [(a.name, a.text) for a in r.actions] == [
        ("stand_up", ""), ("speak", "Wstałem."), ("sit_down", ""),
    ]
    assert r.dropped == ()


def test_speak_only():
    r = parse_envelope('{"actions": [{"name": "speak", "text": "Cześć."}]}')
    assert [(a.name, a.text) for a in r.actions] == [("speak", "Cześć.")]


def test_unknown_names_dropped_and_reported():
    r = parse_envelope(
        '{"actions": [{"name": "dance"}, {"name": "speak", "text": "Hi"}, 42]}'
    )
    assert [(a.name, a.text) for a in r.actions] == [("speak", "Hi")]
    assert r.dropped == ("dance", "?")


def test_non_string_text_dropped():
    r = parse_envelope(
        '{"actions": [{"name": "speak", "text": 42}, '
        '{"name": "speak", "text": "Hi"}]}'
    )
    assert [(a.name, a.text) for a in r.actions] == [("speak", "Hi")]
    assert r.dropped == ("speak",)


def test_empty_list_parses():
    assert parse_envelope('{"actions": []}').actions == ()


@pytest.mark.parametrize("raw", [
    "Cześć, jestem NAO.",
    '{"speak": "Hi", "action": "none"}',
    '{"actions": "speak"}',
    '["speak"]',
    '{"actions": [{"name": "speak", "text": "Hi"}',
    "",
])
def test_malformed_raises(raw):
    with pytest.raises(EnvelopeError):
        parse_envelope(raw)
