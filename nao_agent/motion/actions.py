"""Robot actions as decorated handlers (no ROS dependencies).

Adding an action means writing one method with @action: the registry
collects handler + description, and everything else derives from it:
  - parser's allowed set = registry keys (unknown steps are dropped),
  - prompt's action list = registry descriptions (composed by the bridge),
  - response.json enum = covered by the parity test.

Handlers return short status strings for the logs; spoken text always
comes from the LLM's `speak` field, never from here.
"""

from typing import Any, Callable, Dict

HANDLERS: Dict[str, Callable] = {}
DESCRIPTIONS: Dict[str, str] = {}

SPEAK_ACTION = "speak"
SPEAK_DESCRIPTION = "say the text from the text field"


class MotionError(Exception):
    """Raised when the motion backend is unavailable or an action fails."""


def action(description: str) -> Callable:
    """Mark a method as an LLM-invokable robot action.

    The registry name is the method name automatically.
    """

    def decorator(func: Callable) -> Callable:
        HANDLERS[func.__name__] = func
        DESCRIPTIONS[func.__name__] = description
        return func

    return decorator


def action_list_fragment() -> str:
    """Prompt fragment enumerating actions (bridge appends it to prose)."""
    items = "; ".join(
        [f"{SPEAK_ACTION}: {SPEAK_DESCRIPTION}"]
        + [f"{name}: {DESCRIPTIONS[name]}" for name in HANDLERS]
    )
    return f"Available actions (name in the \"name\" field): {items}."


class PostureActions:
    """Posture and gesture handlers. Services are injected for testability."""

    def __init__(self, get_service: Callable[[str], Any], speed: float = 0.5) -> None:
        self._svc = get_service
        self._speed = speed

    def _go_to_posture(
        self, preset: str, family: str, restore_autonomy: bool
    ) -> str:
        posture = self._svc("ALRobotPosture")
        if posture.getPostureFamily() == family:
            return f"Already in {family}."
        self._set_autonomy(False)
        try:
            ok = posture.goToPosture(preset, self._speed)
        finally:
            self._set_autonomy(restore_autonomy)
        if not ok:
            raise MotionError(f"{preset} failed")
        return f"{preset}: done"

    def _set_autonomy(self, enabled: bool) -> None:
        for name in (
            "ALBackgroundMovement",
            "ALListeningMovement",
            "ALBasicAwareness",
        ):
            try:
                self._svc(name).setEnabled(enabled)
            except Exception:  # noqa: BLE001 - best effort, may not exist in sim
                continue

    @action("sit down")
    def sit_down(self) -> str:
        """Make the robot sit down."""
        return self._go_to_posture("Sit", "Sitting", True)

    @action("stand up")
    def stand_up(self) -> str:
        """Make the robot stand up."""
        return self._go_to_posture("StandInit", "Standing", True)

    @action("lie on stomach")
    def lie_on_stomach(self) -> str:
        """Make the robot lie on its stomach."""
        return self._go_to_posture("LyingBelly", "LyingBelly", False)

    @action("lie on back")
    def lie_on_back(self) -> str:
        """Make the robot lie on its back."""
        return self._go_to_posture("LyingBack", "LyingBack", False)

    @action("wave the right hand in greeting")
    def wave_right_hand(self) -> str:
        """Wave the robot's right hand."""
        family = self._svc("ALRobotPosture").getPostureFamily()
        if family in ("LyingBelly", "LyingBack", "Sitting"):
            return f"Cannot wave while {family}."
        names = ["RShoulderPitch", "RShoulderRoll", "RElbowRoll", "RWristYaw"]
        time_lists = [[1.5, 1.75, 2, 2.35, 2.75, 3, 4.5] for _ in range(4)]
        angle_lists = [
            [-1, -1, -1, -1, -1, -1, 1.5],
            [-0.5, -0.5, -0.5, -0.5, -0.5, -0.5, -0.3],
            [1.3, 0.2, 1.2, 0.2, 1.2, 0.2, 0.5],
            [0.5, -0.5, 0.5, -0.5, 0.5, -0.5, 0.0],
        ]
        self._svc("ALMotion").angleInterpolation(
            names, angle_lists, time_lists, True
        )
        return "Waved right hand."

    def execute(self, name: str) -> str:
        """Run a registered action by name."""
        if name not in HANDLERS:
            raise MotionError(f"Unknown action: {name}")
        return getattr(self, name)()
