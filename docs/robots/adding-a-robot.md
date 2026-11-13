# Add a ROS 2 robot

The robot needs a Linux computer, ROS 2 (Humble, Jazzy, or Lyrical), and a driver that already publishes a pose and subscribes to a velocity. Rosie does not install that stack.

Rosie never talks to a motor board or microcontroller directly; the fleet only sees the ROS 2 driver on the Linux computer. If your base has no ROS 2 driver, write a small node (or a `ros2_control` hardware interface) that turns the board's serial protocol into `/cmd_vel` and `/odom`. micro-ROS on the board is also fine; the fleet still talks to the Linux topics.

## Setup

Copy the repo onto the robot and install it as in [Getting started](../getting-started.md). Then:

```bash
rosie robot setup --fleet lab --robot bot1 --profile rosmaster_x3 --connect tcp/192.168.1.10:7447
rosie robot doctor
```

Setup downloads `zenoh-bridge-ros2dds` 1.9.0 for this machine (Linux aarch64 or x86_64), writes `rosie-bridge.json5`, and on Linux writes user systemd units. Every robot runs `rosie robot run` (the bridge) and `rosie robot watchdog` (presence, estop, deadman, link loss). The units call those two commands and source `/opt/ros/<distro>/setup.bash` first. The bridge runs as a Zenoh **client** of the laptop router unless you pass `--mode peer` or `--mode router`.

`rosie robot doctor` checks the namespace, the allow list, and the connect mode in that file. It does not start ROS. On the robot, `ros2 topic list` should include the topics in the profile.

`connect: auto` is resolved when the service starts, not when you write the file. The unit runs `rosie robot run`, which scouts for a router advertising this fleet and then execs the bridge.

## Pick a profile

| Profile | Distro | Velocity | Notes |
|---|---|---|---|
| `default_ros2` | Jazzy | `TwistStamped` | Generic robot. Camera on `/camera/image_raw/compressed` |
| `turtlebot3` | Humble | `Twist` | `/odom`, `NavigateToPose` |
| `turtlebot4` | Jazzy | `Twist` | Create 3 still speaks `Twist`. See below |
| `rosmaster_x3` | Humble | `Twist` | Yahboom Rosmaster X3. EKF pose on `/odom` |
| `rosmaster_m3_pro` | Humble | `Twist` | Same topics. The STM32 base is behind the vendor driver |

To change a topic on the laptop side without writing a new profile, pass overrides in Python:

```python
from rosie.profiles import load_profile

profile = load_profile("rosmaster_x3", {
    "pose": {"topic": "/amcl_pose", "type": "geometry_msgs/msg/PoseWithCovarianceStamped"},
})
```

`MobileRobot(..., profile_overrides={...})` takes the same dict, and the manifest can store it on a robot entry (`profile` and `overrides`). `rosie robot setup` has no override flag; if the bridge needs to carry a different topic, write a profile.

To write a profile, copy `python/rosie/profiles/default_ros2.yaml`. You need `cmd_vel` (topic and type), `pose` (topic and type), and a `link_loss` policy. Add `nav` and `camera` if the robot has them. `bridge.allow` is the allow list setup writes: publishers the laptop may hear, subscribers the laptop may command, and action servers. `bridge.rates` is `pub_max_frequencies` (for example a camera at 2 Hz).

## Bridge or rmw_zenoh

**Bridge (default).** DDS stays on the robot. The bridge copies the allowed topics onto Zenoh under `/{fleet}/{robot}`. This is what `rosie robot setup` configures. It works with the vendor's DDS, including Fast DDS, which is what the official ROS images use. The bridge and `rmw_zenoh` are not the same protocol. Do not point one at the other.

**rmw_zenoh.** If you control the whole ROS stack and you want Zenoh instead of DDS on the robot, launch it with `RMW_IMPLEMENTATION=rmw_zenoh_cpp` and put `/{fleet}/{robot}` in the ROS namespace. There is no bridge process and no `rosie robot setup` config. You still run the watchdog for presence, estop, and the deadman. NavigateToPose from the laptop is implemented for the bridge, not for `rmw_zenoh`; send goals with Nav2 on the robot, or keep the bridge.

Humble and Jazzy `rmw_zenoh` participants do not exchange data with each other. The type-hash segment differs (`TypeHashNotSupported` versus `RIHS01_...`).

TurtleBot 4's Create 3 base runs its own DDS. That robot stays on the bridge; switching the Pi to `rmw_zenoh` does not move the base. A Rosmaster's STM32 board speaks to the vendor ROS driver (micro-ROS on the M3 Pro). It is not a fleet member and it does not constrain the Zenoh side of the Pi.

## Board

Nav2's usual minimum is a Raspberry Pi 4 with 4 GB, because of Nav2, not because of the bridge. On the robot, with Nav2 up:

```bash
sh tools/sim/footprint.sh
```

Add the RSS of `zenoh-bridge-ros2dds` and the watchdog. That sum, next to Nav2, is the number to compare. Do not size a board from a laptop measurement.
