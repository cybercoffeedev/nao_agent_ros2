"""ROS service front for posture actions (thin ROS wrapper).

Exposes PostureExecutor (direct qi session) as
`/nao_agent/go_to_posture` (naoqi_bridge_msgs/srv/SetString: action name
in, success out), plus the thinking-eyes animation as
`/nao_agent/set_eyes` (SetString: "thinking"/"" in, success out).
Runs on a single-threaded executor and keeps one qi session referenced:
proxies die with their session (GC closes the socket, later writes fail),
so the session must be born on the main thread and stay alive as long as
its proxies are used; a long motion briefly stalls other callbacks.
"""

import threading

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node

from naoqi_bridge_msgs.srv import SetString

from nao_agent.motion.eyes import EYES_SERVICE, Eyes
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
        self._qi_connect = lambda: connect_qi(nao_ip, nao_port)
        self._eyes = None
        # Owns the eyes qi session: proxies die with it (GC closes the
        # socket, then every later write fails), so it must stay referenced
        # as long as self._eyes is used.
        self._qi_session = None
        self._eyes_lock = threading.Lock()
        self.create_service(
            SetString,
            SERVICE_NAME,
            self._on_request,
        )
        self.create_service(
            SetString,
            EYES_SERVICE,
            self._on_eyes,
        )
        self.get_logger().info(f"motion service ready: {SERVICE_NAME}")
        self.get_logger().info(f"eyes service ready: {EYES_SERVICE}")

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

    def _get_eyes(self):
        """Lazily build the animator on the shared qi session."""
        with self._eyes_lock:
            if self._eyes is not None:
                return self._eyes
            try:
                session = self._qi_connect()
                leds = session.service("ALLeds")
                try:
                    blinking = session.service("ALAutonomousBlinking")
                except Exception:  # noqa: BLE001 - sim may lack the service
                    blinking = None
                self._eyes = Eyes(leds, blinking, on_error=self.get_logger().warn)
                # Keep the session referenced: dropping it closes the socket
                # under the still-cached proxies (every later write then
                # fails with "Socket is not connected").
                self._qi_session = session
            except Exception as e:  # noqa: BLE001 - robot unreachable
                self.get_logger().warn(f"Eyes unavailable: {e}")
                return None
            return self._eyes

    def _on_eyes(self, request: SetString.Request, response: SetString.Response):
        mode = (request.data or "").strip()
        eyes = self._get_eyes()
        if eyes is None:
            response.success = False
            return response
        try:
            response.success = eyes.set(mode)
        except Exception as e:  # noqa: BLE001 - NAOqi call failed
            self.get_logger().warn(f"Eyes {mode!r} failed: {e}")
            response.success = False
        return response


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MotionServerNode()
    executor = SingleThreadedExecutor()
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
