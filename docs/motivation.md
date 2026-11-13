# Why Rosie

ROS 2 is the right stack on the robot: drivers, Nav2, simulation, and the vendor's bringup already exist. It is a heavy thing to install on every laptop that only wants to drive, watch, or record a fleet, and it is a poor bus for a room of robots that do not share one DDS domain.

Rosie is the thin layer on the laptop side of that split.

Use Rosie when you want one laptop command to reach several ROS 2 robots, with the same teleop, viz, bags, and estop, without installing ROS on the laptop. Use plain ROS 2 when you are working on one robot and RViz, `ros2 topic`, and the launch files are enough. You can still point RViz at the fleet later; see [ROS on the laptop](robots/laptop-ros.md).

## What Rosie is not

Rosie does not replace Nav2, ros2_control, or a vendor base driver. It does not run on a microcontroller. It does not define a second message catalog for pose and velocity. Those are ROS messages, carried as CDR.

The fleet contract is small on purpose. A robot qualifies if it can be seen, report a pose, accept a velocity, and stop when the fleet says stop. Navigation and a camera are optional. The contract is in [Conventions](conventions.md).

## How this differs from using Zenoh inside ROS

`rmw_zenoh` replaces DDS with Zenoh inside ROS 2. That is a robot-stack choice. The bridge is the other choice: DDS stays on the robot, and only the topics you allow cross onto the fleet bus, under a namespace that is the robot's fleet identity. Rosie speaks the bridge's keys. A later switch to `rmw_zenoh` is possible for robots you control; it is a different key layout, and some bases (TurtleBot 4's Create 3) run their own DDS and cannot make that switch for the whole robot. [Add a robot](robots/adding-a-robot.md) covers both.
