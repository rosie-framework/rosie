"""Generic keyboard teleop → publishes ``std_msgs/Twist`` on ``cmd_vel``.

This is the reusable *mechanism* (raw-terminal key loop, fixed-rate publish,
deadman zero on stop/exit). Robot-specific *policy* — speeds, key mapping,
robot/fleet identity, and any extra deadman command — is supplied by the caller.

Example (robot wrapper)::

    from rosie import Session, topics
    from rosie.tools.teleop_twist import run_teleop

    with Session(robot="car1", name="teleop") as session:
        run_teleop(session, v_fwd=0.25, v_turn=1.2,
                   on_stop=lambda: session.publish(topics.CMD, b'{"op":"stop"}'))
"""

from __future__ import annotations

import select
import sys
import termios
import time
import tty
from collections.abc import Callable

from .. import topics
from ..session import Session
from ..std_msgs import Twist


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
    v_fwd: float = 0.25,
    v_turn: float = 1.0,
    pub_hz: float = 10.0,
    keymap: dict[str, tuple[float, float]] | None = None,
    stop_keys: str = " x",
    quit_keys: str = "q",
    on_stop: Callable[[], None] | None = None,
    verbose: bool = True,
) -> None:
    """Run a blocking keyboard teleop loop until a quit key is pressed.

    Publishes ``Twist(v, w)`` on relative ``cmd_vel`` (resolved via the
    session's robot/fleet) at ``pub_hz`` while a motion key is active, and a
    zero ``Twist`` on stop/exit (deadman).

    Pass an existing ``session`` to reuse a connection (its identity wins);
    otherwise a temporary Session is opened and closed here. ``on_stop`` runs
    when a stop key is pressed and once on exit, for robot-specific deadman
    policy.
    """
    owns_session = session is None
    if session is None:
        session = Session(robot=robot, fleet=fleet, name="teleop")
    topic = topics.CMD_VEL
    resolved = session.resolve_name(topic)
    if keymap is None:
        keymap = default_keymap(v_fwd, v_turn)

    def publish_twist(v: float, w: float) -> None:
        session.publish_msg(topic, Twist(v=v, w=w))

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
