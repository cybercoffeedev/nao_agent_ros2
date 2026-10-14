"""Bridge prompt -> llama_ros -> speech + posture actions.

Flow:
  /prompt (std_msgs/String, test injection instead of microphone)
  -> action generate_chat_completions (system + user, ordered steps
     constrained by grammar_schema)
  -> parse [{speak, motion}...] -> speak texts to /speech, motions run
     in order via the motion service (/nao_agent/go_to_posture)

Non-blocking: the /prompt callback sends the goal asynchronously, then a
sequence runner walks the steps (speak publishes, motion blocks per step).
Single-flight covers the whole sequence; motion has its own guard inside
the executor (single writer on ALMotion).
"""

from collections import deque
import os
import threading
import time

import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, String

from nao_agent.llm.chat_client import ChatClient
from nao_agent.llm.prompts import build_messages, clip_text
from nao_agent.motion.actions import SPEAK_ACTION, action_list_fragment
from nao_agent.motion.eyes import EYES_SERVICE
from nao_agent.motion.posture_executor import SERVICE_NAME as MOTION_SERVICE
from nao_agent.response.parser import EnvelopeError, parse_envelope
from nao_agent.speech.speaker import Speaker
from naoqi_bridge_msgs.srv import SetString

MOTION_TIMEOUT_SEC = 120.0


class ChatBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__("chat_bridge_node")

        self.declare_parameter("prompt_topic", "/prompt")
        self.declare_parameter("speech_topic", "/speech")
        self.declare_parameter("llama_action", "/llama/generate_chat_completions")
        # Single source of truth for the prompt text is config/params.yaml
        # (`system_prompt`); an empty value fails fast in _on_prompt.
        self.declare_parameter("system_prompt", "")
        self.declare_parameter("response_schema_file", "")
        self.declare_parameter("motion_service", MOTION_SERVICE)
        self.declare_parameter("temp", 0.2)
        self.declare_parameter("server_wait_sec", 5.0)
        # Watchdog: an LLM goal with no result within this window is
        # cancelled so one dead backend cannot wedge the bridge busy.
        self.declare_parameter("llm_timeout_sec", 300.0)
        # Thinking-eyes animation while the LLM works (via the motion
        # server's eye service; best effort, never blocks the flow).
        self.declare_parameter("thinking_eyes", True)
        self.declare_parameter("eyes_service", EYES_SERVICE)
        # Busy flag for the STT feeder (default namespace topic): true while
        # a prompt is being processed, so the feeder pauses listening.
        self.declare_parameter("busy_topic", "/agent/busy")
        # Conversation memory (in-process only, restart clears it):
        # last `history_turns` exchanges, each message clipped to
        # `history_msg_chars` so one long prompt cannot evict the
        # system prompt from the model's context window.
        self.declare_parameter("history_turns", 6)
        self.declare_parameter("history_msg_chars", 500)

        prompt_topic = self.get_parameter("prompt_topic").value
        speech_topic = self.get_parameter("speech_topic").value
        llama_action = self.get_parameter("llama_action").value
        self._llama_action = llama_action

        raw_prompt = self.get_parameter("system_prompt").value.strip()
        if not raw_prompt:
            raise RuntimeError(
                "Empty `system_prompt` param "
                "(launch with --params-file <.../nao_agent/config/params.yaml>)"
            )
        self._system_prompt = raw_prompt + "\n" + action_list_fragment()
        self._temp = float(self.get_parameter("temp").value)
        self._server_wait = float(self.get_parameter("server_wait_sec").value)
        self._llm_timeout = float(self.get_parameter("llm_timeout_sec").value)
        self._history_turns = max(0, int(self.get_parameter("history_turns").value))
        self._history_chars = max(0, int(self.get_parameter("history_msg_chars").value))
        # (role, text) pairs, oldest first; maxlen evicts oldest automatically.
        # Invariant: only complete (user, assistant) pairs are stored, so the
        # message list always alternates user/assistant after the system
        # prompt (the Mistral template rejects consecutive same-role
        # messages and crashes the LLM node). The current user text is held
        # in _pending_user until the assistant reply arrives; failed turns
        # are discarded and never enter the history.
        self._history: deque = deque(maxlen=2 * self._history_turns)
        self._pending_user: str | None = None
        self._grammar_schema = self._load_schema(
            self.get_parameter("response_schema_file").value
        )

        self._speaker = Speaker(self, speech_topic)
        self._llm = ChatClient(self, llama_action)
        self._motion_service = self.get_parameter("motion_service").value
        self._motion = self.create_client(SetString, self._motion_service)
        self._thinking_eyes = bool(self.get_parameter("thinking_eyes").value)
        self._eyes = self.create_client(
            SetString, self.get_parameter("eyes_service").value
        )

        self._lock = threading.Lock()
        self._busy = False
        self._turn = 0
        self._goal_handle = None
        self._goal_deadline = 0.0
        # Latched so a (re)starting feeder sees the current state.
        latched = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self._busy_pub = self.create_publisher(
            Bool, self.get_parameter("busy_topic").value, latched
        )
        self._publish_busy(False)
        # Motion-down cache: fail fast instead of stalling 5 s per step.
        self._motion_down = False

        self.create_subscription(String, prompt_topic, self._on_prompt, 10)
        self.create_timer(5.0, self._on_watchdog)
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
            self._turn += 1
            turn = self._turn
            self._motion_down = False  # fresh turn re-probes the service once
            # Fresh slot: no stale handle/deadline may survive into the turn.
            self._goal_handle = None
            self._goal_deadline = 0.0
        self._publish_busy(True)

        self.get_logger().info(f"Prompt: {text[:120]}")
        clipped = clip_text(text, self._history_chars)
        with self._lock:
            history = list(self._history)
            # Hold the current prompt aside; it enters the history only
            # together with what the sequence actually spoke (see
            # _run_sequence), so an aborted run cannot plant false memories.
            self._pending_user = clipped if self._history_turns > 0 else None
        self._think(True)
        try:
            messages = build_messages(self._system_prompt, clipped, history)
            goal = self._llm.make_goal(
                messages, temp=self._temp, grammar_schema=self._grammar_schema
            )
        except Exception as e:  # noqa: BLE001 - never wedge busy on build errors
            self.get_logger().error(f"LLM goal build failed: {e}")
            self._drop_turn(turn)
            return

        if not self._llm.wait_for_server(timeout_sec=self._server_wait):
            self.get_logger().error(
                f"LLM action '{self._llama_action}' unavailable "
                f"after {self._server_wait}s, aborting goal "
                "(check `ros2 action list` and the `llama_action` param)"
            )
            self._drop_turn(turn)
            return

        try:
            future = self._llm.send_async(goal)
        except Exception as e:  # noqa: BLE001 - never wedge busy on send errors
            self.get_logger().error(f"LLM goal send failed: {e}")
            self._drop_turn(turn)
            return
        try:
            future.add_done_callback(lambda f: self._on_goal_response(f, turn))
        except Exception as e:  # noqa: BLE001 - never wedge busy on callback errors
            self.get_logger().error(f"LLM callback attach failed: {e}")
            self._drop_turn(turn)
            return

    def _on_goal_response(self, future, turn: int) -> None:
        try:
            goal_handle = future.result()
        except Exception as e:  # noqa: BLE001
            self.get_logger().error(f"Goal send failed: {e}")
            self._drop_turn(turn)
            return
        if not goal_handle.accepted:
            self.get_logger().error("LLM rejected goal")
            self._drop_turn(turn)
            return
        stale = None
        with self._lock:
            if turn != self._turn:
                # Superseded while sending: never let a stale handle
                # clobber the current turn's slot.
                stale = goal_handle
            else:
                self._goal_handle = goal_handle
                self._goal_deadline = time.monotonic() + self._llm_timeout
        if stale is not None:
            try:
                stale.cancel_goal_async()
            except Exception as e:  # noqa: BLE001 - best effort
                self.get_logger().debug(f"Stale goal cancel failed: {e}")
            return
        try:
            result_future = goal_handle.get_result_async()
        except Exception as e:  # noqa: BLE001
            self.get_logger().error(f"LLM result watch failed: {e}")
            self._drop_turn(turn)
            return
        try:
            result_future.add_done_callback(lambda f: self._on_result(f, turn))
        except Exception as e:  # noqa: BLE001 - never wedge busy on callback errors
            self.get_logger().error(f"LLM callback attach failed: {e}")
            self._drop_turn(turn)
            return

    def _on_result(self, future, turn: int) -> None:
        with self._lock:
            if turn != self._turn:
                return  # stale: a newer turn already owns the bridge
        try:
            result = future.result().result
            text = ChatClient.extract_text(result)
            if not text:
                self.get_logger().warn("LLM returned an empty response")
                self._drop_turn(turn)
                return
            try:
                response = parse_envelope(text)
            except EnvelopeError as e:
                # Raw JSON must never reach speech.
                self.get_logger().warn(f"Dropping malformed envelope: {e}")
                self._drop_turn(turn)
                return
            if response.dropped:
                self.get_logger().warn(f"Dropping unknown steps: {response.dropped}")
            if not response.actions:
                self.get_logger().warn("LLM returned no actions")
                self._drop_turn(turn)
                return
            with self._lock:
                # Re-validate: a drop may have retired this turn mid-flight
                # (matters under a multithreaded executor; harmless today).
                if turn != self._turn:
                    return
                pending = self._pending_user
                self._pending_user = None
                # Hand off to the sequence: the goal is done, so the
                # watchdog must not mistake it for a hung backend.
                self._goal_handle = None
                self._goal_deadline = 0.0
            self._think(False)
            thread = threading.Thread(
                target=self._run_sequence,
                args=(response, pending, turn),
                daemon=True,
            )
            thread.start()
        except Exception as e:  # noqa: BLE001
            self.get_logger().error(f"LLM result failed: {e}")
            self._drop_turn(turn)

    def _run_sequence(self, response, pending_user: str | None, turn: int) -> None:
        """Walk steps in order; speak publishes, motion goes via service."""
        said: list[str] = []
        try:
            for item in response.actions:
                if item.name == SPEAK_ACTION:
                    if item.text:
                        self._speaker.say(item.text)
                        said.append(item.text.strip())
                    else:
                        self.get_logger().warn("Skipping empty speak step")
                    continue
                if not self._call_motion(item.name):
                    break
        finally:
            # Record only what was actually spoken: an aborted sequence
            # must not plant replies the user never heard.
            spoken = " ".join(said)
            with self._lock:
                if (
                    pending_user
                    and spoken
                    and self._history_turns > 0
                ):
                    self._history.extend(
                        [
                            ("user", pending_user),
                            (
                                "assistant",
                                clip_text(spoken, self._history_chars),
                            ),
                        ]
                    )
            self._release(turn)

    def _on_watchdog(self) -> None:
        """Cancel an LLM goal that outlived its deadline (dead backend)."""
        cancel = None
        turn = None
        with self._lock:
            if (
                self._busy
                and self._goal_handle is not None
                and time.monotonic() > self._goal_deadline
            ):
                cancel = self._goal_handle
                self._goal_handle = None
                self._goal_deadline = 0.0
                turn = self._turn
        if cancel is not None:
            self.get_logger().error(
                f"LLM goal timed out after {self._llm_timeout}s, cancelling"
            )
            try:
                cancel.cancel_goal_async()
            except Exception as e:  # noqa: BLE001 - best effort
                self.get_logger().debug(f"LLM cancel failed: {e}")
            self._drop_turn(turn)

    def _call_motion(self, action: str) -> bool:
        """Call the motion service; main thread keeps spinning for us."""
        with self._lock:
            down = self._motion_down
        if down:
            # Already known down this turn: fail fast, no 5 s stall per step.
            self.get_logger().debug(
                f"Motion service '{self._motion_service}' still down, "
                "skipping motion (speech continues)"
            )
            return True
        if not self._motion.wait_for_service(timeout_sec=self._server_wait):
            self.get_logger().warn(
                f"Motion service '{self._motion_service}' unavailable, "
                "skipping motion (speech continues)"
            )
            with self._lock:
                self._motion_down = True
            return True
        with self._lock:
            self._motion_down = False
        request = SetString.Request()
        request.data = action
        future = self._motion.call_async(request)
        # rclpy futures are not concurrent.futures: poll done() instead.
        # No spinning needed here — the main thread keeps spinning.
        deadline = time.monotonic() + MOTION_TIMEOUT_SEC
        while not future.done():
            if time.monotonic() > deadline:
                self.get_logger().warn(
                    f"Motion {action} timed out, aborting sequence"
                )
                return False
            time.sleep(0.1)
        try:
            ok = future.result().success
        except Exception as e:  # noqa: BLE001
            self.get_logger().warn(f"Motion {action} failed: {e}, aborting sequence")
            return False
        if not ok:
            self.get_logger().warn(f"Motion {action} rejected, aborting sequence")
            return False
        self.get_logger().info(f"Motion {action}: done")
        return True

    def _load_schema(self, path: str) -> str:
        if not path:
            path = os.path.join(
                get_package_share_directory("nao_agent"),
                "config",
                "grammar",
                "response.json",
            )
        try:
            with open(path, encoding="utf-8") as f:
                schema = f.read()
            self.get_logger().info(f"Response schema loaded: {path}")
            return schema
        except OSError as e:
            raise RuntimeError(f"Response schema missing at {path}: {e}") from e

    def _think(self, on: bool) -> None:
        """Start/stop the thinking-eyes animation; best effort, never blocks."""
        if not self._thinking_eyes:
            return
        request = SetString.Request()
        request.data = "thinking" if on else ""
        try:
            future = self._eyes.call_async(request)
            future.add_done_callback(self._on_eyes_done)
        except Exception as e:  # noqa: BLE001 - eyes must not break the flow
            self.get_logger().debug(f"Eyes call failed: {e}")
            return

    @staticmethod
    def _on_eyes_done(future) -> None:
        try:
            future.result()
        except Exception:  # noqa: BLE001 - eyes are best effort
            pass

    def _publish_busy(self, busy: bool) -> None:
        msg = Bool()
        msg.data = bool(busy)
        self._busy_pub.publish(msg)

    def _release(self, turn: int) -> None:
        with self._lock:
            if turn != self._turn:
                return  # stale: a newer turn already owns the bridge
            # Retire the turn: no late callback may resurrect it afterwards.
            self._turn += 1
        self._think(False)
        with self._lock:
            self._busy = False
            self._goal_handle = None
            self._goal_deadline = 0.0
        self._publish_busy(False)

    def _drop_turn(self, turn: int) -> None:
        """Discard a failed turn: forget the pending prompt, stay idle."""
        with self._lock:
            if turn != self._turn:
                return  # stale: a newer turn already owns the bridge
            # Invalidate the turn so any late callback for it dies too.
            self._turn += 1
        self._think(False)
        with self._lock:
            self._pending_user = None
            self._busy = False
            self._goal_handle = None
            self._goal_deadline = 0.0
        self._publish_busy(False)


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
