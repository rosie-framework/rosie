# Running a fleet

## Networking

One Zenoh router (`rosie router`) is the normal bus. Robots connect out to it. DDS does not leave the robot.

```text
laptop:  rosie router  listens on tcp/0.0.0.0:7447
robot:   bridge + watchdog  connect to tcp/<laptop>:7447
```

`rosie robot setup --connect auto` does not bake an address. When the service starts, `rosie robot run` looks for a router that announces this fleet and connects to it. That works when the laptop and the robot are on the same LAN and multicast scout is not blocked. If it is blocked, pass the locator.

### Modes

| Mode | When |
|---|---|
| `client` | Default. The robot dials the router. |
| `peer` | No fleet router. The laptop session uses `mode="peer"` and the bridge listens as well as connects. |
| `router` | This robot is the router for a small group. Other robots connect to it. |

Pass `--mode` to `rosie robot setup`. A `Session` takes the same `mode`.

### Ports

The router listens on 7447 unless you change it. Zenoh locators look like `tcp/192.168.1.10:7447` (one slash, not a URL).

The bridge namespace does not change the port. It only changes Zenoh keys: `/lab/bot1` in front of every ROS name the bridge is allowed to carry, including `/tf` if you allow it. Leave `/tf` off the allow list unless you need it. It is a lot of traffic.

### Loss

Presence is a 1 Hz heartbeat from the watchdog. A few lost packets should not drop the robot from `fleet list` (the laptop TTL is about 3 seconds). To see how presence and liveliness behave under loss, run `tools/sim/presence_netem.sh` on Linux. The script prints the `tc netem` commands; it does not pick a result for you.

## Security

Use secure mode on any network you do not control. Open mode is still there for a laptop and a sim on localhost.

| Mode | Who can use the bus | What `fleet list` shows |
|---|---|---|
| Open | Anyone who can reach the router | Every presence publisher |
| Secure (`--secure`) | Peers that know the fleet secret (Zenoh usrpwd) | Enrolled robot ids only |

```bash
# laptop
rosie fleet init --fleet lab --secure
rosie fleet add --fleet lab --robot bot1 --profile rosmaster_x3
rosie router --fleet lab --secure

# robot
rosie fleet secret --fleet lab --set
rosie robot setup --fleet lab --robot bot1 --profile rosmaster_x3 --secure --connect tcp/192.168.1.10:7447

# laptop
rosie fleet list --fleet lab --secure
```

The secret is a file under `~/.rosie` on each machine. It is not sent on the bus; copy it to the robot yourself with `fleet secret --set`. `rosie secret apply --config rosie-bridge.json5 --fleet lab` writes the user and password hash into a bridge config that was created without `--secure`.

Holding the secret still lets a peer publish as any robot id. The allowlist filters what the laptop tools display; it is not a per-key ACL. Treat the secret like a password for the whole fleet.

Network isolation still matters. Put the robots and the router on a network that strangers are not on.

## Management

```bash
rosie fleet init --fleet lab --secure
rosie fleet add --fleet lab --robot bot1 --profile rosmaster_x3
rosie fleet list --fleet lab --secure
rosie fleet wait --fleet lab --expect bot1 --secure
rosie fleet estop --fleet lab --secure
```

`fleet add` writes the robot into the manifest with its profile. Laptop tools that are given only a robot id can read the profile from the manifest, and from presence if the manifest does not name one.

`fleet list` shows robots whose presence is fresh. `fleet wait` blocks until the expected ids are present, which is the bring-up check before a session. `fleet estop` is the stop button. What the robot does with it is in [Safety](robots/safety.md).

`fleet topics` and `rosie topic list` print the keys heard under the fleet. Add `--profile` and `--robot` to label the profile's keys with ROS types:

```bash
rosie topic list --fleet lab --profile rosmaster_x3 --robot bot1
rosie topic echo --fleet lab --key bot1/odom --type nav_msgs/msg/Odometry
```

Remove a robot from the manifest with `rosie fleet remove`. That does not stop the robot. Shut down the bridge unit on the robot (`systemctl --user stop rosie-bridge.service rosie-watchdog.service`) when it should leave the bus.
