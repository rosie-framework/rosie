# Networking

One Zenoh router (`rosie router`) is the normal bus. Robots connect out to it. DDS does not leave the robot.

```text
laptop:  rosie router  listens on tcp/0.0.0.0:7447
robot:   bridge + watchdog  connect to tcp/<laptop>:7447
```

`rosie robot setup --connect auto` does not bake an address. When the service starts, `rosie robot run` looks for a router that announces this fleet and connects to it. That works when the laptop and the robot are on the same LAN and multicast scout is not blocked. If it is blocked, pass the locator.

## Modes

| Mode | When |
|---|---|
| `client` | Default. The robot dials the router. |
| `peer` | No fleet router. The laptop session uses `mode="peer"` and the bridge listens as well as connects. |
| `router` | This robot is the router for a small group. Other robots connect to it. |

Pass `--mode` to `rosie robot setup`. A `Session` takes the same `mode`.

## Ports

The router listens on 7447 unless you change it. Zenoh locators look like `tcp/192.168.1.10:7447` (one slash, not a URL).

The bridge namespace does not change the port. It only changes Zenoh keys: `/lab/bot1` in front of every ROS name the bridge is allowed to carry, including `/tf` if you allow it. Leave `/tf` off the allow list unless you need it. It is a lot of traffic.

## Loss

Presence is a 1 Hz heartbeat from the watchdog. A few lost packets should not drop the robot from `fleet list` (the laptop TTL is about 3 seconds). To see how presence and liveliness behave under loss, run `tools/sim/presence_netem.sh` on Linux. The script prints the `tc netem` commands; it does not pick a result for you.
