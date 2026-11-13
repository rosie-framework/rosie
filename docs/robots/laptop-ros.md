# ROS on the laptop

You do not need ROS on the laptop to use Rosie. If you want RViz, add a second bridge on the laptop that subscribes to the fleet and publishes DDS locally.

The robot bridge already places topics at `lab/bot1/odom` and the rest. A laptop bridge in the other direction, with namespace `/`, exposes those names to a local ROS graph. Copy `tools/sim/bridge.json5`, set `namespace` to `/`, point `connect` at `tcp/127.0.0.1:7447`, and set `allow.subscribers` to the topics you want in RViz (`^lab/bot1/odom$` and so on). Then:

```bash
zenoh-bridge-ros2dds -c laptop-bridge.json5
```

```bash
source /opt/ros/$ROS_DISTRO/setup.bash
rviz2
```

Add an Odometry display on `/lab/bot1/odom`. The frames will not line up with a robot TF tree unless you also bridge `/tf`, which is high rate. Prefer `/odom` or `/amcl_pose` from the profile and a fixed frame of `odom` or `map`.

`rmw_zenoh` on the laptop is the other way to see the bus, and only if the robot is also on `rmw_zenoh` in the same distro. A bridge robot and an `rmw_zenoh` laptop do not see each other's topics. Use a bridge on both sides.

The simulated robot in [Getting started](../getting-started.md) is the place to try this once. Start the compose file, start the laptop bridge, and confirm `/lab/bot1/odom` appears in `ros2 topic list` on the laptop.
