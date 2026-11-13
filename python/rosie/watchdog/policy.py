"""Pure decisions for the on-robot watchdog. No ROS or Zenoh imports."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WatchdogPolicy:
    """Estop, teleop deadman, and link-loss.

    Non-gate mode only publishes a twist when something must stop the robot.
    Gate mode is the last writer of ``cmd_vel``: it forwards laptop twists
    while they are fresh and publishes zero otherwise. Nav2 then has to be
    remapped through this node; that is a profile option, not the default.
    """

    link_loss: str = "stop_after"
    link_loss_s: float = 2.0
    deadman_s: float = 0.5
    gate: bool = False
    estop: bool = False
    last_cmd_t: float | None = None
    last_router_t: float | None = None
    v: float = 0.0
    w: float = 0.0
    last_was_motion: bool = False

    def on_twist(self, v: float, w: float, now: float) -> None:
        self.v = float(v)
        self.w = float(w)
        self.last_cmd_t = float(now)
        self.last_was_motion = abs(self.v) > 1e-6 or abs(self.w) > 1e-6

    def on_estop(self) -> None:
        self.estop = True
        self.v = 0.0
        self.w = 0.0

    def clear_estop(self) -> None:
        self.estop = False

    def on_router(self, now: float) -> None:
        self.last_router_t = float(now)

    def link_down(self, now: float) -> bool:
        if self.link_loss == "continue":
            return False
        if self.last_router_t is None:
            return False
        return (float(now) - self.last_router_t) > float(self.link_loss_s)

    def tick(self, now: float) -> tuple[float | None, float | None, str]:
        """Return ``(v, w, reason)``.

        ``v`` is ``None`` when this tick should not publish (non-gate, and
        nothing is wrong). ``reason`` is ``ok``, ``forward``, ``deadman``,
        ``estop``, or ``link_loss``.
        """
        now = float(now)
        if self.estop:
            return 0.0, 0.0, "estop"
        if self.link_down(now):
            return 0.0, 0.0, "link_loss"
        fresh = (
            self.last_cmd_t is not None
            and (now - self.last_cmd_t) <= float(self.deadman_s)
        )
        if self.gate:
            if fresh:
                return self.v, self.w, "forward"
            return 0.0, 0.0, "idle"
        if self.last_was_motion and not fresh and self.last_cmd_t is not None:
            self.last_was_motion = False
            self.v = 0.0
            self.w = 0.0
            return 0.0, 0.0, "deadman"
        return None, None, "ok"
