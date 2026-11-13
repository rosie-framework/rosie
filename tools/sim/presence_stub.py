"""Publish a fleet presence heartbeat so laptop tools can list the sim robot.

The watchdog does this on a real robot. This stub is the stand-in until
``rosie robot setup`` is running inside the container.
"""

from __future__ import annotations

import argparse
import time

from rosie.session import Session


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fleet", default="lab")
    parser.add_argument("--robot", default="bot1")
    parser.add_argument("--profile", default="default_ros2")
    parser.add_argument("--connect", default=None)
    args = parser.parse_args()
    session = Session(robot=args.robot, fleet=args.fleet, connect=args.connect, name="presence-stub")
    try:
        while True:
            session.publish(
                "presence",
                {
                    "robot_id": args.robot,
                    "fleet_id": args.fleet,
                    "status": "ready",
                    "profile": args.profile,
                    "estop": False,
                },
            )
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        session.close()


if __name__ == "__main__":
    main()
