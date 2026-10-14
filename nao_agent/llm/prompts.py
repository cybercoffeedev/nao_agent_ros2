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


def sanitize_history(history: "list[tuple[str, str]] | None") -> list:
    """Return history as valid alternating user/assistant pairs.

    The Mistral chat template used by the model rejects consecutive
    messages with the same role, and llama_ros now fails the whole goal
    (crashing the node) instead of ignoring it. Past turns must therefore
    always form complete pairs: user, assistant, user, assistant, ...
    Entries with an unexpected role are skipped, and a trailing dangling
    user (a prompt with no assistant reply yet) is dropped because the
    current user text is appended separately by build_messages.
    """
    clean: list = []
    expected = "user"
    for role, content in history or []:
        if role not in ("user", "assistant"):
            continue
        if role != expected:
            continue
        clean.append((role, (content or "").strip()))
        expected = "assistant" if expected == "user" else "user"
    if clean and clean[-1][0] == "user":
        clean.pop()
    return clean


def build_messages(
    system_prompt: str,
    user_text: str,
    history: "list[tuple[str, str]] | None" = None,
) -> list:
    """Build a message list in {role, content} format.

    `history` holds older ("user" | "assistant", text) exchanges, oldest
    first; they go between the system prompt and the current user text.
    History is sanitized to alternating pairs so a past failure (a prompt
    with no assistant reply) can never produce two `user` messages in a
    row and crash the LLM backend.
    Returns plain dicts; conversion to llama_msgs is done by ChatClient,
    so this function is testable without ROS.
    """
    system = (system_prompt or "").strip()
    user = (user_text or "").strip()
    messages = [{"role": "system", "content": system}]
    for role, content in sanitize_history(history):
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user})
    return messages
