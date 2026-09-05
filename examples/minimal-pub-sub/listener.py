#!/usr/bin/env python3
"""Minimal Rosie listener — subscribe demo/cmd_vel."""

from __future__ import annotations

from rosie import Session, topics


def main() -> None:
    with Session(robot="demo", fleet="lab", name="listener") as session:
        def on_msg(msg: dict) -> None:
            print(f"  got {msg}")

        session.subscribe_json(topics.CMD_VEL, on_msg)
        print(f"Listening on {session.resolve_name(topics.CMD_VEL)} (Ctrl-C to stop)")
        session.spin()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
