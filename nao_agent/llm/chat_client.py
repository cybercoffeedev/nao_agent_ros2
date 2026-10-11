"""Adapter for the GenerateChatCompletions action from llama_ros.

Hides llama_msgs fields from the node (Adapter pattern).
Uses non-blocking mode (send_goal_async + callbacks)
to avoid blocking the executor inside the /prompt subscription callback.
Sanitizes model output (BOS/EOS tag leaks) before it reaches speech.
"""

import re

from rclpy.action import ActionClient
from rclpy.node import Node

from llama_msgs.action import GenerateChatCompletions
from llama_msgs.msg import ChatMessage

# Leading/trailing <s> / </s> artifacts: the model sometimes emits the BOS
# token first and it detokenizes to a literal tag. Never speak tags.
_TAG_LEAK = re.compile(r"^(?:\s*</?s>\s*)+|(?:\s*</?s>\s*)+$")


class ChatClient:
    def __init__(self, node: Node, action_name: str) -> None:
        self._node = node
        self._client: ActionClient = ActionClient(
            node, GenerateChatCompletions, action_name
        )

    def wait_for_server(self, timeout_sec: float) -> bool:
        return self._client.wait_for_server(timeout_sec=timeout_sec)

    def destroy(self) -> None:
        self._client.destroy()

    def make_goal(
        self,
        messages: list,
        temp: float = 0.2,
        grammar_schema: str = "",
    ) -> GenerateChatCompletions.Goal:
        goal = GenerateChatCompletions.Goal()
        ros_messages: list = []
        for m in messages:
            cm = ChatMessage()
            cm.role = m["role"]
            cm.content = m["content"]
            ros_messages.append(cm)
        goal.messages = ros_messages
        goal.add_generation_prompt = True
        goal.use_jinja = True
        goal.stream = False
        # TODO: envelope "action" executor covers postures; motion beyond
        # that (walk, gestures) extends the schema + strategies.
        goal.sampling_config.temp = float(temp)
        # JSON schema compiled to GBNF server-side; empty disables it.
        goal.sampling_config.grammar_schema = grammar_schema
        return goal

    def send_async(self, goal: GenerateChatCompletions.Goal, feedback_cb=None):
        return self._client.send_goal_async(goal, feedback_callback=feedback_cb)

    @staticmethod
    def extract_text(result) -> str:
        try:
            choices = result.choices
            if not choices:
                return ""
            text = (choices[0].message.content or "").strip()
        except (AttributeError, IndexError):
            return ""
        return _TAG_LEAK.sub("", text).strip()
