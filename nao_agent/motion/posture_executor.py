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

from nao_agent.motion.actions import HANDLERS, MotionError, PostureActions


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

    def __init__(
        self,
        connect: Callable[[], Any],
        logger: Any,
    ) -> None:
        self._connect = connect
        self._logger = logger
        self._lock = threading.Lock()
        self._moving = False

    def run(self, action: str) -> str:
        """Run an action synchronously (caller must use a worker thread)."""
        if action not in HANDLERS:
            raise MotionError(f"Unknown action: {action}")
        with self._lock:
            if self._moving:
                raise MotionError("motion busy")
            self._moving = True
        try:
            return self._perform(action)
        finally:
            with self._lock:
                self._moving = False

    def _perform(self, action: str) -> str:
        try:
            session = self._connect()
        except MotionError:
            raise
        except Exception as e:  # noqa: BLE001
            raise MotionError(f"backend unavailable: {e}") from e
        actions = PostureActions(session.service)
        try:
            return actions.execute(action)
        except MotionError:
            raise
        except Exception as e:  # noqa: BLE001 - NAOqi call failed
            raise MotionError(f"{action} failed: {e}") from e
