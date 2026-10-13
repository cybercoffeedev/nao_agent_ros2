"""Adapter for ALTextToSpeech via the /speech topic.

naoqi_driver2 SpeechSubscriber (speech.cpp) does:
  sub /speech std_msgs/String -> ALTextToSpeech.say(data)
In the naoqi-bin simulator audio will not play, but a message on /speech
proves that the prompt -> LLM -> TTS chain worked.
"""

from rclpy.node import Node
from std_msgs.msg import String


class Speaker:
    def __init__(self, node: Node, topic: str) -> None:
        self._node = node
        self._pub = node.create_publisher(String, topic, 10)

    def say(self, text: str) -> None:
        clean = (text or "").strip()
        if not clean:
            self._node.get_logger().warn("Speaker: empty response, skipping /speech")
            return
        msg = String()
        msg.data = clean
        self._pub.publish(msg)
        self._node.get_logger().info(f"Speaker -> /speech ({len(clean)} chars)")
