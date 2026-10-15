"""Speech-done monitor: ALTextToSpeech/TextDone -> /speech_done.

The echo gate must close exactly when synthesis ends, not when a time
estimate says so. This node subscribes the ALMemory TextDone event over
its own qi session and publishes one Empty per utterance end on
`/speech_done` for the feeder (hardware fires twice per utterance;
only the truthy end-firing closes the gate).
The qi session stays referenced as long as the subscriber is used
(proxies die with their session). Without the event (simulator, dropped
link) the feeder still gates on its time-window fallback cap.
"""

import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.node import Node
from std_msgs.msg import Empty

from nao_agent.stt.gate import is_done_event

TEXT_DONE_KEY = "ALTextToSpeech/TextDone"


class SpeechDoneNode(Node):
    def __init__(self) -> None:
        super().__init__("speech_done_node")

        self.declare_parameter("nao_ip", "127.0.0.1")
        # Untyped (dynamic) on purpose: launch passes strings ("9559"),
        # CLI passes ints (9559); both coerce below.
        self.declare_parameter(
            "nao_port", descriptor=ParameterDescriptor(dynamic_typing=True)
        )
        self.declare_parameter("done_topic", "/speech_done")
        nao_ip = str(self.get_parameter("nao_ip").value)
        try:
            nao_port = int(self.get_parameter("nao_port").value)
        except (TypeError, ValueError) as e:
            raise RuntimeError(
                f"Bad `nao_port` param (need e.g. 9559): {e}"
            ) from e
        done_topic = self.get_parameter("done_topic").value

        self._pub = self.create_publisher(Empty, done_topic, 10)
        self._qi_session = None
        self._qi_subscriber = None
        try:
            from nao_agent.motion.posture_executor import connect_qi

            session = connect_qi(nao_ip, nao_port)
            subscriber = session.service("ALMemory").subscriber(TEXT_DONE_KEY)
            subscriber.signal.connect(self._on_done)
            self._qi_session = session
            self._qi_subscriber = subscriber
        except Exception as e:  # noqa: BLE001 - degraded, fallback cap covers
            self.get_logger().warn(
                f"TextDone unavailable ({e}); gate runs on time estimate only"
            )
        self.get_logger().info(
            f"speech_done ready: {TEXT_DONE_KEY} -> {done_topic}"
        )

    def _on_done(self, value) -> None:
        # Hardware fires twice per utterance (falsy at start, truthy at
        # end); only the end closes the gate.
        if is_done_event(value):
            self._pub.publish(Empty())


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SpeechDoneNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
