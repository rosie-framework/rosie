# Fleet

`Fleet` is the laptop view of who is on the bus. It does not require the router announcement. A robot is present when its presence heartbeat is fresh.

```python
from rosie import Fleet

with Fleet("lab", secure=True) as fleet:
    for robot in fleet.robots():
        print(robot.robot_id, robot.status, robot.profile, robot.estop)
    fleet.publish_estop()
```

`robots()` returns `RobotPresence` values (`rosie.fleet_msgs`). `status` is `ready` or `estop` when the watchdog is the publisher. `profile` is how a tool can pick a decoder if the manifest does not name one.

`publish_estop` sends `{"op":"estop"}` on `{fleet}/_fleet/estop` with critical delivery. The watchdog latches it.

`claim_leader` / `get_leader` are the JSON leader claim on `{fleet}/_fleet/coord/leader`. They are a fleet-plane helper, not a Nav2 feature.

In secure mode, pass `secure=True` (or use the CLI `--secure`). The fleet secret is read from the host file. Open mode never reads that file, so a leftover secret does not silently lock a localhost router.

CLI equivalents are in [Management](../fleet/management.md).
