# Robots on a Rosie fleet: native vs bridge

Rosie controls a robot in one of two ways:

- **Native** — the robot runs Rosie directly (MCU firmware, or Linux
  `rosie run` from `robot.yaml`) and publishes/subscribes Rosie topics itself.
- **Bridge** — the robot keeps its existing stack (typically ROS 2) and
  **`rosie agent`** translates between that stack and Rosie topics.

Both look identical to the fleet: every robot is just an id under
`{fleet}/{robot}/…` honoring the [fleet robot contract](../conventions.md#fleet-robot-contract).
`rosie teleop`, `rosie viz`, `rosie bag`, `rosie fleet`, and `MobileRobot` do not
care which path a given robot uses. **A fleet can mix both freely.**

## When to go native vs bridge

The deciding factor is *who already owns the drivers/autonomy*.

| Situation | Approach | Why |
|-----------|----------|-----|
| MCU / bare actuators (ESP32 car), no onboard Linux | **Native** (`robot.yaml` + firmware) | Nothing else exists; Rosie *is* the stack |
| Linux robot Rosie will drive (Pi/Jetson DIY) | **Native** (`robot.yaml` + `rosie run`) | One bus; Rosie owns hardware |
| Commercial robot with a supported vendor/ROS stack (TurtleBot, etc.) | **Bridge** (`rosie agent`) | Reuse tested drivers/Nav2 instead of re-owning them |
| Robot's value is its autonomy stack (SLAM, Nav2, manipulation, perception) | **Bridge** | You want that stack, not to replace it |
| Simple robot where ROS is pure overhead and you control the hardware | **Native** | Drop DDS; run one lighter stack |

Three questions, in order:

1. **Is there an existing, maintained driver stack you'd otherwise reimplement?**
   Yes → **bridge**. No → continue.
2. **Do you need heavy on-robot autonomy (Nav2 / SLAM / perception) from that ecosystem?**
   Yes → **bridge**. No → continue.
3. **Can you reliably produce `pose` and consume `cmd_vel` (+ `presence`) yourself?**
   Yes → **native** is cleaner and lighter. No → bridge (or don't add the robot yet).

> Rule of thumb: **native** when Rosie would be the robot's *first* real software
> stack (MCU, DIY Linux). **Bridge** when the robot already *has* a real stack
> worth keeping (commercial / ROS). Enforce the topic contract, not the
> implementation.

## Value Rosie adds even to ROS robots

Bridging is not a downgrade — Rosie still owns the **fleet + laptop layer**,
which is the gap ROS 2 namespaces and facility managers (Open-RMF / FreeFleet)
do not fill for lab bring-up:

- One brokered bus for a **heterogeneous team** (MCU cars + ROS robots together).
- Fleet-scoped tooling from a laptop (macOS/Windows OK): `rosie fleet list/wait`,
  `rosie topic list`, `rosie viz --fleet`, `rosie bag record` across the whole team.
- Uniform teleop / pose view / bags regardless of each robot's internals.
- No ROS on the laptop; no DDS discovery across the fleet.

ROS keeps owning **on-robot drivers and autonomy**; facility orchestrators can
still own **task/traffic** if you need them. Rosie owns **membership, bus, and
laptop introspection**. Interop at the edge — same philosophy as `rosie bag
export` (MCAP) rather than reimplementing rosbag2. See
[Motivation](../motivation.md).

## Where ROS runs

| Layer | Where | What |
|-------|-------|------|
| Vendor ROS (drivers, optional Nav2) | Robot | Existing stack, unchanged |
| Rosie agent | Robot | `pip install rosie-framework` + `rosie agent run` |
| Rosie tools | Laptop | teleop, viz, bag, fleet — **no ROS** |

You install ROS only on the robot (usually already there from the vendor image).
The laptop stays Rosie-only. See [Getting started](../getting-started.md) for the
host install.

## `rosie agent` (ROS 2 bridge)

Run **on the robot**, after the vendor ROS bring-up so `/cmd_vel` and `/odom`
exist. Rosie is installed **beside** ROS (a venv with `--system-site-packages`
so `rclpy` is importable). Rosie does **not** install ROS.

```bash
# on the robot
python3 -m venv --system-site-packages ~/rosie-venv
source ~/rosie-venv/bin/activate
pip install rosie-framework
# source ROS 2 if not already in the environment
# source /opt/ros/$ROS_DISTRO/setup.bash

rosie agent init --robot turtle1 --fleet lab
# optional: --connect tcp/<router-host-ip>:7447
# optional: --profile turtlebot4 / rosmaster_m3_pro

rosie agent doctor    # config, rclpy, router
rosie agent run       # foreground; Ctrl+C to stop
# optional autostart:
rosie agent install
systemctl --user daemon-reload
systemctl --user enable --now rosie-agent.service
```

`rosie agent init` writes `agent.yaml` (identity + ROS topic map). Profiles
(`default_ros2`, `turtlebot3`, `turtlebot4`, `rosmaster_x3`,
`rosmaster_m3_pro`) fill topic defaults; override with
`--cmd-vel` / `--odom` or edit the file:

```yaml
robot: turtle1
fleet: lab
connect: auto   # or tcp/<router-host-ip>:7447 — see fleet/networking.md
ros2:
  profile: turtlebot4
  cmd_vel: /cmd_vel
  odom: /odom
  # pose: /amcl_pose          # optional; omit to keep odom-based pose
  navigate_to_pose: /navigate_to_pose
  frame_id: map
```

### Mapping

| Direction | ROS | Rosie |
|-----------|-----|-------|
| host → robot | publish `/cmd_vel` (`geometry_msgs/Twist`) | subscribe `cmd_vel` (`v`, `w`) |
| host → robot | `NavigateToPose` (`nav2_msgs`) | subscribe `goto` (`x`, `y`, `goal_id?`) |
| robot → host | action result | publish `nav_result` |
| robot → host | subscribe `/odom` or `ros2.pose` | publish `pose` (`x`, `y`, `theta`) |
| robot → host | timer | publish `presence` (~1 Hz) |

`goto` requires Nav2 (`nav2_msgs` + a running `navigate_to_pose` action server). Teleop, pose, and presence still work if Nav2 is absent; a `goto` then ends with `nav_result` `aborted`. `cmd` `stop` and incoming `cmd_vel` cancel an active Nav2 goal (`canceled`).

Pose and goto share a frame (Rosie has no TF). Default pose is `/odom`. If Nav2 goals use `frame_id: map`, set `ros2.pose` to the localization topic (typically `/amcl_pose`) so `rosie drive` coordinates match viz. `rosie agent doctor` warns when `frame_id` is `map` but pose still comes from odom.

Camera bridging is not in this mapping.

From the laptop (Rosie only):

```bash
rosie fleet list --fleet lab
rosie teleop --robot turtle1 --fleet lab
rosie drive --robot turtle1 --fleet lab   # needs Nav2
rosie viz --fleet lab
```

Keep **units and frames** consistent with [Conventions](../conventions.md#units-and-frames):
`pose` in meters, yaw in radians.

## Config: which file?

| Robot kind | On-robot config | Command |
|------------|-----------------|---------|
| **MCU** (ESP32) | `robot.yaml` | `rosie mcu …` |
| **Linux + ROS** (ROS drives hardware) | `agent.yaml` | `rosie agent` |
| **Linux native** (Rosie drives hardware) | `robot.yaml` (`platform: linux`) | `rosie run --config robot.yaml` |

## Linux native (`rosie run`)

DIY Pi/Jetson robots that Rosie drives use the same `robot.yaml` shape as MCU,
with `platform: linux` and Linux driver pins (BCM / I2C). On the robot:

```bash
pip install "rosie-framework[linux]"   # lgpio + smbus2 for built-in drivers
# or: pip install rosie-framework      # BYO Python MotorDriver only

rosie run --config robot.yaml --dry-run   # validate
rosie run --config robot.yaml             # control loop (foreground)
```

Details and example YAML: [Linux run](linux-run.md).
BYO motors: `motors.driver: python` + `motors.class: mypkg:MyMotorDriver`.

## See also

- [Conventions → Fleet robot contract](../conventions.md#fleet-robot-contract)
- [Fleet networking](../fleet/networking.md)
- [Bring Your Own Robot](byor.md) — native MCU / Linux bring-up
- [Mobile base](mobile-base.md) — shared contract, topics, host tools
- [Linux run](linux-run.md) — `rosie run` assembly
- [Motivation](../motivation.md) — Rosie vs ROS 2
