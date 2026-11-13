#!/usr/bin/env python3
"""Subscribe to the JSON note from talker.py."""

from __future__ import annotations

from rosie import Session


def main() -> None:
    with Session(robot="demo", fleet="lab", name="listener") as session:

        def on_msg(msg: dict) -> None:
            print(f"  got {msg}")

        session.subscribe_json("notes", on_msg)
        print(f"Listening on {session.resolve_name('notes')} (Ctrl-C to stop)")
        session.spin()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")
