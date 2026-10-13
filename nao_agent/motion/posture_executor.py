"""Motion execution via a direct qi session (no ROS dependencies).

The ROS driver does not expose ALRobotPosture, so this module opens its
own qi session to the same robot (NAOqi allows concurrent sessions).

Handlers live in actions.py and self-register with @action; the executor
only guards (single writer on ALMotion) and dispatches by name. Calls are
blocking — run them off the ROS executor thread (service server with a
multithreaded executor, or a worker thread).
"""

import threading
from typing import Any, Callable

from nao_agent.motion.actions import MotionError, PostureActions

SERVICE_NAME = "/nao_agent/go_to_posture"


def connect_qi(nao_ip: str, nao_port: int) -> Any:
    """Open a qi session. Import is lazy so unit tests need no qi installed."""
    try:
        import qi
    except ImportError as e:
        raise MotionError(f"libqi-python not installed: {e}") from e
    session = qi.Session()
    try:
        session.connect(f"tcp://{nao_ip}:{nao_port}")
    except RuntimeError as e:
        raise MotionError(f"cannot connect to tcp://{nao_ip}:{nao_port}: {e}") from e
    return session


class PostureExecutor:
    """Runs registered actions in a worker thread with a single-flight guard."""

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect
        self._lock = threading.Lock()
        self._moving = False

    def run(self, action: str) -> str:
        """Run an action synchronously (caller must use a worker thread)."""
        with self._lock:
            if self._moving:
                raise MotionError("motion busy")
            self._moving = True
        try:
            try:
                session = self._connect()
                actions = PostureActions(session.service)
                return actions.execute(action)
            except MotionError:
                raise
            except Exception as e:  # noqa: BLE001 - backend or NAOqi call failed
                raise MotionError(f"{action} failed: {e}") from e
        finally:
            with self._lock:
                self._moving = False
