"""Pure envelope parsing (no ROS dependencies).

The LLM answers with an ordered list of steps (constrained by
grammar_schema, see config/grammar/response.json)::

    {"actions": [{"name": "stand_up"},
                 {"name": "speak", "text": "I stood up."},
                 {"name": "sit_down"}]}

Only `speak` texts may ever reach speech. Unknown step names are dropped
(and reported); anything structurally wrong raises EnvelopeError and the
caller drops the whole answer with a warning.
"""

import json
from typing import NamedTuple, Tuple

from nao_agent.motion.actions import HANDLERS, SPEAK_ACTION


class EnvelopeError(ValueError):
    """Raised when the model output is not a valid response envelope."""


class ActionItem(NamedTuple):
    name: str
    text: str


class Response(NamedTuple):
    actions: Tuple[ActionItem, ...]
    dropped: Tuple[str, ...]


def parse_envelope(raw: str) -> Response:
    """Parse a raw model answer into an ordered step list."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        raise EnvelopeError(f"not JSON: {e}") from e
    if not isinstance(data, dict):
        raise EnvelopeError(f"envelope is {type(data).__name__}, expected object")
    if "actions" not in data or not isinstance(data["actions"], list):
        raise EnvelopeError("envelope missing 'actions' list")
    actions: list = []
    dropped: list = []
    for item in data["actions"]:
        if not isinstance(item, dict):
            dropped.append("?")
            continue
        name = item.get("name")
        if name == SPEAK_ACTION:
            text = item.get("text", "")
            if not isinstance(text, str):
                dropped.append(SPEAK_ACTION)
                continue
            actions.append(ActionItem(name=name, text=text.strip()))
        elif isinstance(name, str) and name in HANDLERS:
            actions.append(ActionItem(name=name, text=""))
        else:
            dropped.append(str(name))
    return Response(actions=tuple(actions), dropped=tuple(dropped))
