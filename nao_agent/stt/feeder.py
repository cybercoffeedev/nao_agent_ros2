"""STT feeder: driver audio -> whisper -> /prompt (thin ROS wrapper).

Flow:
  /audio (naoqi_bridge_msgs/AudioBuffer, NAO mics)
  -> reshape to mono 16 kHz -> /audio/in (audio_common_msgs/AudioStamped)
  -> whisper VAD + STT action -> transcription text
  -> echo gate (deaf while our own /speech may play, checked against the
     recording window, not just the result time) -> /prompt

The listen loop is a single chained STT goal (the server single-flights
itself); it pauses while the bridge reports busy on /agent/busy (no
prompts during inference, no busy-spam).
A failed send is retried by the watchdog so audio forwarding never blocks.
Utterance text selection and shaping live in the pure stt/audio and
stt/gate modules.
"""

import threading

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, QoSPresetProfiles, ReliabilityPolicy
from std_msgs.msg import Bool, String

from audio_common_msgs.msg import AudioStamped
from naoqi_bridge_msgs.msg import AudioBuffer
from naoqi_bridge_msgs.srv import SetString
from whisper_msgs.action import STT

from nao_agent.motion.eyes import EYES_SERVICE
from nao_agent.stt.audio import TARGET_RATE, shape_for_stt
from nao_agent.stt.gate import (
    capture_window,
    inhibit_until,
    is_hallucination,
    is_inhibited,
    overlaps,
)

# portaudio paInt16, as silero_vad_node.cpp expects in info.format.
PA_INT16 = 0x08


class SttFeederNode(Node):
    def __init__(self) -> None:
        super().__init__("stt_feeder_node")

        self.declare_parameter("audio_topic", "/audio")
        self.declare_parameter("stamped_topic", "/audio/in")
        self.declare_parameter("stt_action", "/whisper/listen")
        self.declare_parameter("prompt_topic", "/prompt")
        self.declare_parameter("speech_topic", "/speech")
        self.declare_parameter("busy_topic", "/agent/busy")
        self.declare_parameter("eyes_service", EYES_SERVICE)
        self.declare_parameter("sec_per_char", 0.08)
        self.declare_parameter("gate_margin_sec", 2.0)
        self.declare_parameter("server_wait_sec", 5.0)
        self.declare_parameter("retry_sec", 2.0)

        audio_topic = self.get_parameter("audio_topic").value
        self._stamped_topic = self.get_parameter("stamped_topic").value
        stt_action = self.get_parameter("stt_action").value
        self._prompt_topic = self.get_parameter("prompt_topic").value
        speech_topic = self.get_parameter("speech_topic").value
        busy_topic = self.get_parameter("busy_topic").value
        eyes_service = self.get_parameter("eyes_service").value
        self._sec_per_char = float(self.get_parameter("sec_per_char").value)
        self._margin = float(self.get_parameter("gate_margin_sec").value)
        self._server_wait = float(self.get_parameter("server_wait_sec").value)
        self._retry_sec = float(self.get_parameter("retry_sec").value)

        self._lock = threading.Lock()
        self._inhibit_start = 0.0
        self._inhibit_until = 0.0
        self._busy = False
        self._goal_active = False
        self._goal_handle = None

        # SensorDataQoS: silero subscribes sensor-data (best effort);
        # a reliable publisher would never match it (silent DDS drop).
        self._pub_audio = self.create_publisher(
            AudioStamped, self._stamped_topic, QoSPresetProfiles.SENSOR_DATA.value
        )
        self._pub_prompt = self.create_publisher(String, self._prompt_topic, 10)
        self.create_subscription(AudioBuffer, audio_topic, self._on_audio, 10)
        self.create_subscription(String, speech_topic, self._on_speech, 10)
        # Latched to match the bridge publisher: a (re)start mid-inference
        # still sees the current busy state.
        latched = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self.create_subscription(Bool, busy_topic, self._on_busy, latched)
        self._stt = ActionClient(self, STT, stt_action)
        self._eyes = self.create_client(SetString, eyes_service)
        # Watchdog re-arms the listen goal after failures; _send_listen
        # itself no-ops while a goal is active or the bridge is busy.
        self.create_timer(self._retry_sec, self._on_watchdog)
        self.get_logger().info(
            f"stt_feeder ready: {audio_topic} -> {self._stamped_topic} "
            f"+ {stt_action} -> {self._prompt_topic} (gated by {speech_topic})"
        )
        self._send_listen()
        # Clean slate: clear any thinking comet left by a previous run.
        self._set_eyes("")

    def _now(self) -> float:
        return self.get_clock().now().nanoseconds / 1e9

    def _on_audio(self, msg: AudioBuffer) -> None:
        try:
            mono = shape_for_stt(msg.data, msg.channel_map, msg.frequency)
        except ValueError as e:
            self.get_logger().warn(f"Dropping audio with bad format: {e}")
            return
        if not mono:
            return
        out = AudioStamped()
        out.header.stamp = self.get_clock().now().to_msg()
        out.audio.audio_data.int16_data = mono
        out.audio.info.format = PA_INT16
        out.audio.info.channels = 1
        out.audio.info.rate = TARGET_RATE
        out.audio.info.chunk = len(mono)
        self._pub_audio.publish(out)

    def _on_speech(self, msg: String) -> None:
        now = self._now()
        with self._lock:
            self._inhibit_start = now
            self._inhibit_until = inhibit_until(
                now, msg.data, self._sec_per_char, self._margin
            )

    def _on_busy(self, msg: Bool) -> None:
        busy = bool(msg.data)
        cancel = None
        with self._lock:
            if busy == self._busy:
                return
            self._busy = busy
            if busy:
                if self._goal_handle is not None:
                    cancel = self._goal_handle
                    self._goal_handle = None
                    self._goal_active = False
        if cancel is not None:
            # Free the server-side goal; the bridge overwrites the eyes
            # with thinking itself, so no eye call here (ordering race).
            # NOTE: cancel goes through the goal handle; ActionClient has
            # no cancel_goal_async (calling it kills this node).
            self.get_logger().debug("Bridge busy, cancelling listen goal")
            try:
                cancel.cancel_goal_async()
            except Exception as e:  # noqa: BLE001 - best effort
                self.get_logger().debug(f"STT cancel failed: {e}")
        else:
            # Back to idle: listen again.
            self._send_listen()

    def _set_eyes(self, mode: str) -> None:
        """Best-effort eye mode switch; never blocks the flow."""
        request = SetString.Request()
        request.data = mode
        try:
            self._eyes.call_async(request)
        except Exception as e:  # noqa: BLE001 - eyes must not break the flow
            self.get_logger().debug(f"Eyes call failed: {e}")

    def _send_listen(self, server_wait: float | None = None) -> None:
        with self._lock:
            if self._goal_active or self._busy:
                return
            self._goal_active = True
        wait = self._server_wait if server_wait is None else server_wait
        if not self._stt.wait_for_server(timeout_sec=wait):
            self.get_logger().warn(
                "STT action unavailable, watchdog will retry "
                "(check `ros2 action list` for the listen server)"
            )
            with self._lock:
                self._goal_active = False
            return
        goal = STT.Goal()
        goal.prompt = ""
        future = self._stt.send_goal_async(goal)
        future.add_done_callback(self._on_goal_response)

    def _on_goal_response(self, future) -> None:
        try:
            handle = future.result()
        except Exception as e:  # noqa: BLE001
            self.get_logger().warn(f"STT goal send failed: {e}")
            self._release_goal()
            return
        if not handle.accepted:
            self.get_logger().warn("STT goal rejected, watchdog will retry")
            self._release_goal()
            return
        with self._lock:
            self._goal_handle = handle
        handle.get_result_async().add_done_callback(self._on_result)

    def _on_result(self, future) -> None:
        try:
            result = future.result().result.transcription
            text = (result.text or "").strip()
            audio_time = float(result.audio_time or 0.0)
            transcription_time = float(result.transcription_time or 0.0)
        except Exception as e:  # noqa: BLE001
            self.get_logger().warn(f"STT result failed: {e}")
            text = ""
            audio_time = transcription_time = 0.0
        now = self._now()
        with self._lock:
            busy = self._busy
            self._goal_active = False
            self._goal_handle = None
            start, end = capture_window(now, audio_time, transcription_time)
            # Drop when the recording overlapped our own speech (the result
            # alone arriving later proves nothing: VAD may have cut TTS).
            echo = overlaps(
                start, end, self._inhibit_start, self._inhibit_until
            ) or is_inhibited(now, self._inhibit_until)
        if not text:
            self.get_logger().debug("STT returned empty text, listening on")
        elif is_hallucination(text):
            self.get_logger().info(f"Dropping non-speech tag: {text[:40]}")
        elif busy:
            # Slipped through the busy barrier (goal sent just before the
            # flag arrived): never feed inference-time speech back in.
            self.get_logger().debug("Dropping transcription while bridge busy")
        elif echo:
            self.get_logger().info("Dropping own-speech transcription (echo gate)")
        else:
            msg = String()
            msg.data = text
            self._pub_prompt.publish(msg)
            self.get_logger().info(f"STT -> /prompt: {text[:80]}")
        self._send_listen()

    def _release_goal(self) -> None:
        with self._lock:
            self._goal_active = False

    def _on_watchdog(self) -> None:
        # Zero-wait probe so a missing server never stalls audio shaping.
        if self._stt.wait_for_server(timeout_sec=0.0):
            self._send_listen(server_wait=0.0)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SttFeederNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
