"""Optional, reusable Rosie helpers (app-level, not core transport).

These are imported explicitly (e.g. `from rosie.tools.teleop_twist import
run_teleop`) so platform-specific dependencies (like `termios`) are only
loaded when a helper is actually used.
"""
