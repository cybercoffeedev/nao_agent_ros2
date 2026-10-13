"""Posture executor and action registry tests (no robot needed)."""

import threading
import time

import pytest

from nao_agent.motion.actions import HANDLERS, SPEAK_ACTION, MotionError, PostureActions
from nao_agent.motion.posture_executor import PostureExecutor


class FakePosture:
    def __init__(self, family="Standing", fail_go=False):
        self.family = family
        self.calls = []
        self.fail_go = fail_go

    def getPostureFamily(self):
        return self.family

    def goToPosture(self, preset, speed):
        self.calls.append((preset, speed))
        if self.fail_go:
            return False
        self.family = {"Sit": "Sitting"}.get(preset, "Standing")
        return True


class FakeMotion:
    def __init__(self):
        self.calls = []

    def angleInterpolation(self, names, angles, times, absolute):
        self.calls.append((names, angles, times, absolute))
        return True


class FakeSession:
    def __init__(self, posture=None, motion=None):
        self.posture = posture or FakePosture()
        self.motion = motion or FakeMotion()

    def service(self, name):
        if name == "ALRobotPosture":
            return self.posture
        if name == "ALMotion":
            return self.motion
        raise RuntimeError(f"no such service: {name}")


def make_executor(session=None):
    return PostureExecutor(lambda: session or FakeSession())


def test_unknown_action_rejected_and_raises():
    executor = make_executor()
    with pytest.raises(MotionError):
        executor.run("dance")
    with pytest.raises(MotionError):
        PostureActions(FakeSession().service).execute("dance")


def test_sit_from_stand_runs_posture():
    session = FakeSession(FakePosture("Standing"))
    executor = make_executor(session)
    assert executor.run("sit_down") == "Sit: done"
    assert session.posture.calls == [("Sit", 0.5)]
    assert session.posture.family == "Sitting"


def test_failed_posture_raises():
    session = FakeSession(FakePosture("Standing", fail_go=True))
    executor = make_executor(session)
    with pytest.raises(MotionError):
        executor.run("sit_down")


def test_already_sitting_skips_motion():
    session = FakeSession(FakePosture("Sitting"))
    executor = make_executor(session)
    assert executor.run("sit_down") == "Already in Sitting."
    assert session.posture.calls == []


def test_wave_calls_angle_interpolation():
    session = FakeSession(FakePosture("Standing"))
    executor = make_executor(session)
    executor.run("wave_right_hand")
    assert len(session.motion.calls) == 1
    names, _, _, absolute = session.motion.calls[0]
    assert names[0] == "RShoulderPitch" and absolute is True


def test_wave_refused_while_sitting():
    actions = PostureActions(FakeSession(FakePosture("Sitting")).service)
    assert "Cannot wave" in actions.execute("wave_right_hand")


def test_second_action_while_moving_rejected():
    class SlowPosture(FakePosture):
        def goToPosture(self, preset, speed):
            time.sleep(0.5)
            return True

    session = FakeSession(SlowPosture("Standing"))
    executor = make_executor(session)
    results = []
    thread = threading.Thread(target=lambda: results.append(executor.run("sit_down")))
    thread.start()
    time.sleep(0.1)
    with pytest.raises(MotionError):
        executor.run("stand_up")
    thread.join(timeout=5.0)
    assert results == ["Sit: done"]


def test_missing_posture_service_raises():
    class NoPosture:
        def service(self, name):
            raise RuntimeError("no ALRobotPosture here")

    executor = PostureExecutor(lambda: NoPosture())
    with pytest.raises(MotionError):
        executor.run("sit_down")
