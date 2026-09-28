import rclpy
from rclpy.node import Node
from std_msgs.msg import String

class TTSNode(Node):
    def __init__(self, input_topic: str = "/voice/reply", output_topic: str ="/speech"):
        super().__init__('tts_node')
        self.declare_parameter('input_topic', '/voice/reply')
        self.declare_parameter('output_topic', '/speech')
        self.input_topic = self.get_parameter('input_topic').value
        self.output_topic = self.get_parameter('output_topic').value
        self.output_topic = output_topic
        self.pub = self.create_publisher(String, output_topic, 10)
        self.sub = self.create_subscription(String, input_topic, self.callback, 10)

    def callback(self, msg: String):
        self.get_logger().info(f'Forwarding: "{msg.data}"')
        self.pub.publish(msg)

def main():
    rclpy.init()
    tts = TTSNode()
    try:
        rclpy.spin(tts)
    finally:
        tts.destroy_node()
        rclpy.shutdown()