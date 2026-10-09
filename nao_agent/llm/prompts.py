"""Pure prompt logic (no ROS dependencies).

Builds the messages[] list sent to the LLM.

The prompt text itself lives only in config/params.yaml (`system_prompt`);
this module takes it as an argument and stays text-free.
"""


def build_messages(system_prompt: str, user_text: str) -> list:
    """Build a message list in {role, content} format.

    Returns plain dicts; conversion to llama_msgs is done by ChatClient,
    so this function is testable without ROS.
    """
    system = (system_prompt or "").strip()
    user = (user_text or "").strip()
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
