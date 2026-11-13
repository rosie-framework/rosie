# Fleet management

```bash
rosie fleet init --fleet lab --secure
rosie fleet add --fleet lab --robot bot1 --profile rosmaster_x3
rosie fleet list --fleet lab --secure
rosie fleet wait --fleet lab --expect bot1 --secure
rosie fleet estop --fleet lab --secure
```

`fleet add` writes the robot into the manifest with its profile. Laptop tools that are given only a robot id can read the profile from the manifest, and from presence if the manifest does not name one.

`fleet list` shows robots whose presence is fresh. `fleet wait` blocks until the expected ids are present, which is the bring-up check before a session. `fleet estop` is the stop button. What the robot does with it is in [Safety](../robots/safety.md).

`fleet topics` and `rosie topic list` print the keys heard under the fleet. Add `--profile` and `--robot` to label the profile's keys with ROS types:

```bash
rosie topic list --fleet lab --profile rosmaster_x3 --robot bot1
rosie topic echo --fleet lab --key bot1/odom --type nav_msgs/msg/Odometry
```

Remove a robot from the manifest with `rosie fleet remove`. That does not stop the robot. Shut down the bridge unit on the robot (`systemctl --user stop rosie-bridge.service rosie-watchdog.service`) when it should leave the bus.
