"""Laptop-side Rosie helpers (teleop, tune, viz).

On-robot processes live in peer packages:
- ``rosie.run`` — Linux-native mobile base (``rosie run``)
- ``rosie.agent`` — ROS 2 bridge (``rosie agent``)

These are imported explicitly (e.g. ``from rosie.tools.teleop_twist import
run_teleop``) so platform-specific dependencies (like ``termios``) are only
loaded when a helper is actually used.

No argparse here — CLI entry points live under ``rosie.cli``.
"""
