"""ROS service front for posture actions (thin ROS wrapper).

Exposes PostureExecutor (direct qi session) as
`/nao_agent/go_to_posture` (naoqi_bridge_msgs/srv/SetString: action name
in, success out). Blocking NAOqi calls run on a multithreaded executor so
one motion never stalls discovery, parameters or shutdown.
"""

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from naoqi_bridge_msgs.srv import SetString

from nao_agent.motion.posture_executor import (
    SERVICE_NAME,
    PostureExecutor,
    connect_qi,
)


class MotionServerNode(Node):
    def __init__(self) -> None:
        super().__init__("motion_server_node")
        self.declare_parameter("nao_ip", "127.0.0.1")
        self.declare_parameter("nao_port", 9559)
        nao_ip = self.get_parameter("nao_ip").value
        nao_port = int(self.get_parameter("nao_port").value)
        self._motion = PostureExecutor(lambda: connect_qi(nao_ip, nao_port))
        self.create_service(
            SetString,
            SERVICE_NAME,
            self._on_request,
        )
        self.get_logger().info(f"motion service ready: {SERVICE_NAME}")

    def _on_request(self, request: SetString.Request, response: SetString.Response):
        action = (request.data or "").strip()
        try:
            message = self._motion.run(action)
        except Exception as e:  # noqa: BLE001 - NAOqi call or backend failed
            self.get_logger().warn(f"Motion {action!r} failed: {e}")
            response.success = False
            return response
        self.get_logger().info(f"Motion {action!r}: {message}")
        response.success = True
        return response


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MotionServerNode()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
