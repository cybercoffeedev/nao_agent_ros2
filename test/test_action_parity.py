"""Registry/schema/prompt parity (no ROS needed).

The static response.json enum must match the @action registry plus speak:
adding an action without updating the schema (or vice versa) fails here.
The prompt's action list is composed from the registry at runtime, so it
cannot drift by construction.
"""

import json
import os

from nao_agent.motion.actions import HANDLERS, SPEAK_ACTION


def test_schema_enum_matches_registry():
    path = os.path.join(
        os.path.dirname(__file__), "..", "config", "grammar", "response.json"
    )
    with open(path, encoding="utf-8") as f:
        schema = json.load(f)
    items = schema["properties"]["actions"]["items"]
    assert set(items["properties"]["name"]["enum"]) == {SPEAK_ACTION, *HANDLERS}
    assert set(schema["required"]) == {"actions"}
