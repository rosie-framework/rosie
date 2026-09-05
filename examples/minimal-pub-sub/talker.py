#!/usr/bin/env python3
"""Minimal Rosie talker — publish Twist on demo/cmd_vel."""

from __future__ import annotations

import time

from rosie import Session, topics
from rosie.std_msgs import Twist


def main() -> None:
    with Session(robot="demo", fleet="lab", name="talker") as session:
        print(f"Publishing on {session.resolve_name(topics.CMD_VEL)} (Ctrl-C to stop)")
        i = 0
        while True:
            session.publish_msg(topics.CMD_VEL, Twist(v=0.1, w=0.0))
            print(f"  sent tick {i}")
            i += 1
            time.sleep(1.0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
