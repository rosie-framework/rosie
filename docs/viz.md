# Rosie viz

Lightweight browser spatial viewer for live fleet poses and offline bags.
Included in the core `pip install`; opens a local page — no npm, no TF, no URDF.

```bash
pip install rosie-framework          # or: pip install -e python from a checkout
rosie viz --fleet lab      # http://127.0.0.1:8765
```

## Modes

| Command | What you see |
|---------|----------------|
| `rosie viz --fleet <id>` | Live 2D map of every robot publishing `pose` under that fleet |
| `rosie viz --robot <id>` | Single-robot session |
| `rosie viz --bag run.rosiebag` | Offline scrub of a `.rosiebag` (same UI schema) |

Optional flags: `--host`, `--port` (default `8765`), `--stale` (seconds before a live pose fades), `--rate` (bag playback), `--no-browser`, `--connect`.

Bag mode also accepts the same slice filters as `rosie bag play`: `--start`, `--end` (seconds from bag t0), and `--key` (topic glob).

## Map

- World frame = robot pose meters (no TF tree).
- Triangle at `(x, y)` rotated by `theta` / `heading_deg`; short trail; label with id.
- Auto-fit / follow (double-click canvas to re-enable). Scroll to zoom; drag to pan.
- Click a triangle or the sidebar list to select a robot (mode, `dist`, `goal_id`, …).
- Live robots older than `--stale` (default 3s) fade, then drop.

## Camera

With a robot selected in **live** mode, viz subscribes to that robot’s
`camera/compressed` and shows JPEG frames in the sidebar (~8 Hz). It also
publishes `camera_enable` on `cmd` when possible (same idea as
`MobileRobot.camera_live`). In **bag** mode, frames already in the bag for the
selected robot appear the same way.

## Bag scrub

`rosie viz --bag path.rosiebag` loads records via the same reader/filters as
`rosie bag play` (`bag.load_records`). Use Play / Pause, rate, and the timeline
slider. Fleet id comes from the bag header, `--fleet`, or `ROSIE_FLEET`.


See also: [Getting started](getting-started.md) · [Architecture](architecture.md) · [Conventions](conventions.md).
