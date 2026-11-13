# Fleet contract

A robot that joins a Rosie fleet is a Linux computer running ROS 2. It has to honour the following. Profiles declare how each item is named on that robot.

## Required

| Item | What the robot does |
|---|---|
| Presence | Something on the robot publishes `{fleet}/{robot}/presence` about once a second. The watchdog does this. The JSON includes `robot_id`, `fleet_id`, `status`, `profile`, and `estop`. |
| Pose | One of `nav_msgs/msg/Odometry` or `geometry_msgs/msg/PoseWithCovarianceStamped`, on the topic the profile names. `/odom` is the default. Use `/amcl_pose` when you want the map frame and that topic exists. Rosie does not compose TF on the laptop. |
| Velocity | `geometry_msgs/msg/Twist` or `TwistStamped` on the profile's command topic. Humble profiles use `Twist`. `default_ros2` (Jazzy and Lyrical) uses `TwistStamped`. |
| Estop | The robot stops, and cancels navigation, when `{fleet}/_fleet/estop` carries `{"op":"estop"}`. The watchdog latches that until it is cleared. |

## Optional

| Item | Profile field |
|---|---|
| `NavigateToPose` | `nav.action`, `nav.frame_id` |
| Camera | `camera.topic`, type `sensor_msgs/msg/CompressedImage` |

## Keys

Bridge namespace is `/{fleet}/{robot}`. Topic `/cmd_vel` becomes `lab/bot1/cmd_vel`. A robot that already uses a ROS namespace puts that in `ros_namespace`, and the key gains another segment: `lab/bot1/yahboom/cmd_vel`.

`rmw_zenoh` has no place to insert a fleet namespace. For that transport the fleet identity is part of the ROS topic name: `0/lab/bot1/cmd_vel/<dds type>/<hash>`. Humble's hash segment is `TypeHashNotSupported`. Jazzy and Lyrical use `RIHS01_...`.

Action goals, results, cancels, and feedback use `<action>/_action/...` under the same namespace. The goal id is inside the CDR payload. Service and action queries carry a CycloneDDS request-header attachment (`rqh`, 8-byte client id, 8-byte sequence, endian byte).

## Command envelope

Every laptop command that should survive a relay carries an envelope **beside** the payload, as a Zenoh attachment. The CDR bytes stay a normal ROS message, because the bridge forwards them unchanged. The attachment is JSON:

```json
{"id":"<hex>","expiry":1710000000.0,"priority":"interactive"}
```

`expiry` is a wall-clock Unix time. A store-and-forward relay can drop a stale command or reorder by `priority` without decoding CDR. `MobileRobot` and `rosie teleop` set `priority` to `interactive` and a one-second TTL on velocity.

## Link loss and priority

The watchdog's link-loss policy is `continue`, `stop`, or `stop_after`, with `link_loss_s`. It is a field of the profile, so another program on the robot can change it by changing that config. Rate limits for the bridge (`bridge.rates`) live in the same profile.

`{fleet}/{robot}/link` is reserved for a link emulator to record loss and delay into a bag next to the robot data. Rosie does not publish it unless you do.

## Modes

`Session` and the bridge config accept `client` (the default), `peer`, and `router`. Presence and estop use the watchdog's session. `Fleet` membership comes from presence, not from the router announcement. A robot can be seen when it is a peer and the laptop is too, if they can connect to each other.

## Fleet plane keys

| Key | Payload |
|---|---|
| `{fleet}/{robot}/presence` | `RobotPresence` JSON |
| `{fleet}/_fleet/estop` | `{"op":"estop"}` |
| `{fleet}/_fleet/router` | Router announcement (discovery) |
| `{fleet}/_fleet/coord/leader` | `LeaderClaim` JSON |
| `{fleet}/{robot}/link` | Reserved for link conditions |
