"""Pure prompt logic (no ROS dependencies).

Builds the messages[] list sent to the LLM.

The prompt text itself lives only in config/params.yaml (`system_prompt`);
this module takes it as an argument and stays text-free.
"""

TRUNCATION_MARKER = "[...]"


def clip_text(text: str, limit: int) -> str:
    """Clip a history message to `limit` chars (history fuse).

    A non-positive limit disables clipping. Overlong text is cut and
    marked so the model knows it was truncated.
    """
    text = (text or "").strip()
    if limit > 0 and len(text) > limit:
        return text[:limit].rstrip() + TRUNCATION_MARKER
    return text


def build_messages(
    system_prompt: str,
    user_text: str,
    history: "list[tuple[str, str]] | None" = None,
) -> list:
    """Build a message list in {role, content} format.

    `history` holds older ("user" | "assistant", text) exchanges, oldest
    first; they go between the system prompt and the current user text.
    Returns plain dicts; conversion to llama_msgs is done by ChatClient,
    so this function is testable without ROS.
    """
    system = (system_prompt or "").strip()
    user = (user_text or "").strip()
    messages = [{"role": "system", "content": system}]
    for role, content in history or []:
        messages.append({"role": role, "content": (content or "").strip()})
    messages.append({"role": "user", "content": user})
    return messages
