"""Bridge prompt -> llama_ros -> /speech.

Flow:
  /prompt (std_msgs/String, test injection instead of microphone)
  -> action /llama/generate_chat_completions (PL system + user)
  -> /speech (std_msgs/String) -> naoqi_driver -> ALTextToSpeech.say()

Non-blocking: the /prompt callback sends the goal asynchronously,
chained as goal_response -> result -> publish. A single-flight flag
prevents overlapping say() calls (driver does async say with no queue).
"""

import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from nao_agent.llm.chat_client import ChatClient
from nao_agent.llm.prompts import build_messages
from nao_agent.speech.speaker import Speaker


class ChatBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__("chat_bridge_node")

        self.declare_parameter("prompt_topic", "/prompt")
        self.declare_parameter("speech_topic", "/speech")
        self.declare_parameter("llama_action", "/llama/generate_chat_completions")
        # Single source of truth for the prompt text is config/params.yaml
        # (`system_prompt`); an empty value fails fast in _on_prompt.
        self.declare_parameter("system_prompt", "")
        self.declare_parameter("temp", 0.2)
        self.declare_parameter("server_wait_sec", 5.0)

        prompt_topic = self.get_parameter("prompt_topic").value
        speech_topic = self.get_parameter("speech_topic").value
        llama_action = self.get_parameter("llama_action").value
        self._llama_action = llama_action

        self._system_prompt = self.get_parameter("system_prompt").value
        self._temp = float(self.get_parameter("temp").value)
        self._server_wait = float(self.get_parameter("server_wait_sec").value)

        self._speaker = Speaker(self, speech_topic)
        self._llm = ChatClient(self, llama_action)

        self._lock = threading.Lock()
        self._busy = False

        self.create_subscription(String, prompt_topic, self._on_prompt, 10)
        self.get_logger().info(
            f"chat_bridge ready: {prompt_topic} -> {llama_action} -> {speech_topic}"
        )

    def _on_prompt(self, msg: String) -> None:
        text = (msg.data or "").strip()
        if not text:
            self.get_logger().warn("Empty /prompt, ignoring")
            return
        with self._lock:
            if self._busy:
                self.get_logger().warn("LLM busy, dropping prompt (single-flight)")
                return
            self._busy = True

        self.get_logger().info(f"Prompt: {text[:120]}")
        if not self._system_prompt.strip():
            self.get_logger().error(
                "Empty `system_prompt` param, aborting "
                "(set it in config/params.yaml)"
            )
            self._release()
            return
        messages = build_messages(self._system_prompt, text)
        goal = self._llm.make_goal(messages, temp=self._temp)

        if not self._llm.wait_for_server(timeout_sec=self._server_wait):
            self.get_logger().error(
                f"LLM action '{self._llama_action}' unavailable "
                f"after {self._server_wait}s, aborting goal "
                "(check `ros2 action list` and the `llama_action` param)"
            )
            self._release()
            return

        future = self._llm.send_async(goal, feedback_cb=self._on_feedback)
        future.add_done_callback(self._on_goal_response)

    def _on_feedback(self, feedback_msg) -> None:
        try:
            chunk = feedback_msg.feedback.choices[0].delta.content
            if chunk:
                self.get_logger().debug(f"stream: {chunk[:60]}")
        except (AttributeError, IndexError):
            pass

    def _on_goal_response(self, future) -> None:
        try:
            goal_handle = future.result()
        except Exception as e:  # noqa: BLE001
            self.get_logger().error(f"Goal send failed: {e}")
            self._release()
            return
        if not goal_handle.accepted:
            self.get_logger().error("LLM rejected goal")
            self._release()
            return
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._on_result)

    def _on_result(self, future) -> None:
        try:
            result = future.result().result
            text = ChatClient.extract_text(result)
            if not text:
                self.get_logger().warn("LLM returned an empty response")
            else:
                self.get_logger().info(f"LLM: {text[:200]}")
                self._speaker.say(text)
        except Exception as e:  # noqa: BLE001
            self.get_logger().error(f"LLM result failed: {e}")
        finally:
            self._release()

    def _release(self) -> None:
        with self._lock:
            self._busy = False


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ChatBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._llm.destroy()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
