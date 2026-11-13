# Laptop tools

These commands run on the laptop. None of them need ROS. For fleet commands (`fleet list`, `wait`, `estop`, `topic list`) see [Running a fleet](fleet.md). For scripting the same things in Python, see [Python API](python-api.md).

## Fleet, robot, and router defaults

Most commands take `--fleet` and `--robot`. Set them once per shell instead:

```bash
export ROSIE_FLEET=lab
export ROSIE_ROBOT=bot1
export ROSIE_CONNECT=tcp/192.168.1.10:7447
```

`ROSIE_CONNECT` is the router the laptop tools dial. It defaults to `tcp/127.0.0.1:7447`, which is `rosie router` on the same laptop, so you only set it when the router runs on another machine. A flag on the command line wins over the variable. Add `--secure` to any command when the fleet is in [secure mode](fleet.md#security).

## Teleop

```bash
rosie teleop --fleet lab --robot bot1 --profile rosmaster_x3
```

| Key | Action |
|---|---|
| `w` / `s` | Forward / back |
| `a` / `d` | Turn left / right |
| `space` or `x` | Stop |
| `q` or Ctrl-C | Quit (sends a zero twist) |

`--v-fwd` sets forward speed in m/s (default 0.25), `--v-turn` the turn rate in rad/s (default 1.0), and `--hz` how often the command repeats (default 10). Each command carries a one-second expiry, and the robot's watchdog stops the robot if commands stop arriving; see [Safety](robots/safety.md). Pass the robot's `--profile` so teleop publishes the right topic and message type.

## Drive

`rosie drive` is a small prompt for one robot:

```bash
rosie drive --fleet lab --robot bot1 --profile rosmaster_x3
```

| Input | Action |
|---|---|
| `x y` | Navigate to that point (Nav2 `NavigateToPose`, in the profile's nav frame, usually `map`) |
| `x1 y1 x2 y2 ...` | Visit each point in turn |
| `teleop` | WASD teleop, as above; `q` returns to the prompt |
| `snap` | Save one camera frame to `./captures/` and open it |
| `cam` | Live camera window (needs `opencv-python`; `q` closes it) |
| `stop` | Zero velocity and cancel the current goal |
| `quit` | Exit |

Navigation needs a profile with `nav` set and Nav2 running on the robot. Ctrl-C during a goal sends stop.

## Viz

`rosie viz` is a browser view of poses and trails for the whole fleet.

```bash
rosie viz --fleet lab
```

Open the URL it prints (port 8765 by default; `--port` changes it, `--no-browser` stops it opening a tab). It listens for `pose`, `odom`, and `amcl_pose` under each robot and decodes JSON or CDR. Odometry and `PoseWithCovarianceStamped` both become a trail. Poses fade after `--stale` seconds without a new sample.

Select a robot to see its camera, if it publishes `camera/compressed` or `camera/image_raw/compressed` as JPEG or as `sensor_msgs/msg/CompressedImage`.

To replay a recording in the same view instead of the live bus:

```bash
rosie viz --bag /tmp/lab.rosiebag --rate 2 --start 10 --end 60
```

## Bags

`rosie bag` records everything under the fleet into a `.rosiebag` file, replays it, and exports it to MCAP for [Foxglove](https://foxglove.dev).

```bash
rosie bag record --fleet lab --robot bot1 --profile rosmaster_x3 -o /tmp/lab.rosiebag
rosie bag info /tmp/lab.rosiebag
rosie bag export /tmp/lab.rosiebag -o /tmp/lab.mcap
rosie bag play /tmp/lab.rosiebag --rate 1
```

`record` runs until Ctrl-C, or for `--duration` seconds. `--key` limits it to a selector under the fleet (for example `'bot1/**'`). A path ending in `.gz` is compressed.

Pass `--profile` and `--robot` when you record. They label that robot's topics with their ROS types, and `export` uses those labels to write `ros2msg` schemas, so Foxglove can decode the messages. A bag recorded without them still exports, but Foxglove shows those topics as raw bytes.

`play` publishes the recorded samples back onto the bus at their original keys, so other tools (or the robots) see them as live traffic. `export`, `play`, and `viz --bag` all take `--start`, `--end` (seconds from the start of the bag), and `--key` to cut the recording.

## Topics

```bash
rosie topic list --fleet lab --profile rosmaster_x3 --robot bot1
rosie topic echo --fleet lab --key bot1/odom --type nav_msgs/msg/Odometry
```

`topic list` prints the keys heard under the fleet, grouped by robot; `--profile` and `--robot` add each key's ROS type. `topic echo` prints samples from one key. Robot data is CDR, so pass `--type` to decode it, and `--distro` to match the robot (default `jazzy`). Fleet keys such as `_fleet/estop` are JSON and print without `--type`.
