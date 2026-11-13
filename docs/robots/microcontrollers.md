# Microcontrollers

Rosie does not run on a microcontroller, and it does not speak to one directly. Motor boards sit behind a ROS 2 driver on the robot's Linux computer. The fleet only sees that driver.

Three ways to get there, in order of effort:

1. **Use a base that already has a ROS 2 driver.** TurtleBot 3, TurtleBot 4, and the Yahboom Rosmaster boards are this case. Install the vendor stack, then [add the robot](adding-a-robot.md). On a Rosmaster M3 Pro the chassis MCU is an STM32 running the vendor's micro-ROS link. That link stays between the MCU and the vendor node. It is not a second robot, and it does not decide whether the Pi uses the DDS bridge or something else.

2. **Write a small ROS 2 driver.** If the board already has a serial protocol, a node (or a `ros2_control` hardware interface) on the Pi translates it to `/cmd_vel` and `/odom`. That node is ordinary ROS. Rosie never parses the serial protocol.

3. **micro-ROS over the serial link**, if you want the board to be a ROS node of its own. This is optional and outside Rosie. The Linux side still runs a micro-ROS agent, and the fleet still talks to the Linux topics.

Putting ROS on the microcontroller, or running Rosie firmware there, is out of scope. So is a flight-stack bridge. If you need a smaller computer than the Pi, shrink the ROS side, not the fleet side.
