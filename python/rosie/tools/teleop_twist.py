"""Keyboard teleop. Publishes a ROS twist on the profile's velocity topic."""

from __future__ import annotations

import select
import sys
import termios
import time
import tty
from collections.abc import Callable

from ..profiles import RobotProfile, load_profile
from ..ros.keys import qualify_topic
from ..ros.pose import twist_dict
from ..session import Qos, Session


def default_keymap(v_fwd: float, v_turn: float) -> dict[str, tuple[float, float]]:
    """WASD → (v, w). Override to change bindings or add strafing, etc."""
    return {
        "w": (v_fwd, 0.0),
        "s": (-v_fwd, 0.0),
        "a": (0.0, v_turn),
        "d": (0.0, -v_turn),
    }


def run_teleop(
    session: Session | None = None,
    *,
    robot: str = "robot",
    fleet: str | None = None,
    secure: bool = False,
    v_fwd: float = 0.25,
    v_turn: float = 1.0,
    pub_hz: float = 10.0,
    keymap: dict[str, tuple[float, float]] | None = None,
    stop_keys: str = " x",
    quit_keys: str = "q",
    on_stop: Callable[[], None] | None = None,
    publish: Callable[[float, float], None] | None = None,
    profile: str | RobotProfile | None = None,
    verbose: bool = True,
) -> None:
    """Run a blocking keyboard teleop loop until a quit key is pressed.

    ``publish(v, w)`` overrides how twists are sent. Otherwise the profile's
    velocity topic is published as CDR. A zero twist is sent on stop and exit.
    """
    owns_session = session is None
    if session is None:
        session = Session(robot=robot, fleet=fleet, name="teleop", secure=secure)
    prof = profile if isinstance(profile, RobotProfile) else load_profile(profile or "default_ros2")
    topic = qualify_topic(prof.ros_namespace, prof.cmd_vel.topic).lstrip("/")
    resolved = session.resolve_name(topic)
    if keymap is None:
        keymap = default_keymap(v_fwd, v_turn)

    def publish_twist(v: float, w: float) -> None:
        if publish is not None:
            publish(v, w)
            return
        session.publish_ros(
            topic,
            prof.cmd_vel.type,
            twist_dict(prof.cmd_vel.type, v, w),
            distro=prof.distro,
            qos=Qos.STREAM,
            envelope=True,
            ttl_s=1.0,
        )

    def stop() -> None:
        publish_twist(0.0, 0.0)
        if on_stop is not None:
            on_stop()

    if verbose:
        keys = "/".join(sorted(keymap))
        label = stop_keys.replace(" ", "space") or "space"
        print(f"Teleop on {resolved}: {keys} to move, [{label}] stop, [{quit_keys}] quit")

    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except termios.error:
        if verbose:
            print("  (stdin is not a TTY; teleop needs an interactive terminal)")
        if owns_session:
            session.close()
        return

    period = 1.0 / pub_hz
    v, w = 0.0, 0.0
    try:
        tty.setcbreak(fd)
        last = time.time()
        while True:
            r, _, _ = select.select([sys.stdin], [], [], 0)
            if r:
                ch = sys.stdin.read(1)
                if ch in quit_keys or ch == "\x03":
                    break
                if ch in stop_keys:
                    v, w = 0.0, 0.0
                    stop()
                elif ch in keymap:
                    v, w = keymap[ch]
                elif ch.lower() in keymap:
                    v, w = keymap[ch.lower()]

            now = time.time()
            if now - last >= period:
                last = now
                if abs(v) > 1e-6 or abs(w) > 1e-6:
                    publish_twist(v, w)
                    if verbose:
                        print(f"\r  cmd_vel v={v:.2f} w={w:.2f}   ", end="", flush=True)
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        stop()
        if verbose:
            print("\nTeleop stopped (cmd_vel zero).")
        if owns_session:
            session.close()
