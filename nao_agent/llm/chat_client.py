"""Adapter for the GenerateChatCompletions action from llama_ros.

Hides llama_msgs fields from the node (Adapter pattern).
Uses non-blocking mode (send_goal_async + callbacks)
to avoid blocking the executor inside the /prompt subscription callback.
"""

from rclpy.action import ActionClient
from rclpy.node import Node

from llama_msgs.action import GenerateChatCompletions
from llama_msgs.msg import ChatMessage


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
        # TODO: wire tools / sampling_config.grammar (GBNF) here.
        goal.sampling_config.temp = float(temp)
        return goal

    def send_async(self, goal: GenerateChatCompletions.Goal, feedback_cb=None):
        return self._client.send_goal_async(goal, feedback_callback=feedback_cb)

    @staticmethod
    def extract_text(result) -> str:
        try:
            choices = result.choices
            if not choices:
                return ""
            return (choices[0].message.content or "").strip()
        except (AttributeError, IndexError):
            return ""
