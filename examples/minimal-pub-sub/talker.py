#!/usr/bin/env python3
"""Publish a JSON note on a user key. Robot data uses ROS types, not this."""

from __future__ import annotations

import time

from rosie import Session


def main() -> None:
    with Session(robot="demo", fleet="lab", name="talker") as session:
        key = session.resolve_name("notes")
        print(f"Publishing on {key} (Ctrl-C to stop)")
        i = 0
        while True:
            session.publish("notes", {"text": "hello", "n": i})
            print(f"  sent {i}")
            i += 1
            time.sleep(1.0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
