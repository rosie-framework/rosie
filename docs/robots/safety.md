# Safety

The watchdog is a small ROS node on the robot (`rosie robot watchdog`). It has its own Zenoh session, so it still runs if the DDS bridge dies. `rosie robot setup` installs it next to the bridge.

## Deadman

Laptop teleop publishes the profile's velocity topic. If those messages were moving the robot and then stop arriving, the watchdog publishes a zero twist. It does this only after a non-zero command goes stale (about half a second), so it does not fight Nav2 while the laptop is idle.

`cmd_vel_gate: true` in the profile is the stricter option. The laptop publishes `{topic}_teleop` (for example `/cmd_vel_teleop`) and the watchdog is the only node that publishes `/cmd_vel`. Turn that on only after you have remapped Nav2's output through the same gate. The default is off.

## Estop

`rosie fleet estop --fleet lab` publishes `{"op":"estop"}` on `{fleet}/_fleet/estop`. The watchdog latches, publishes zero velocity, and cancels `NavigateToPose` goals until estop is cleared in the watchdog. Restarting the bridge does not clear it. Restarting the watchdog does.

## Link loss

`link_loss` in the profile:

| Value | Behaviour |
|---|---|
| `continue` | Keep the last policy. The robot does not stop because the router vanished |
| `stop` | Zero velocity and cancel goals once the router has been silent for `link_loss_s` |
| `stop_after` | Same as `stop`, the usual choice when a short dropout should not halt a Nav2 plan |

Rosmaster profiles use `stop` and 1 second. The others use `stop_after` and 2 seconds. The watchdog treats router announcements as the link being up. Killing the router is the test: teleop should die, and a `stop` robot should get a zero twist after the timeout.

## Presence

Once a second the watchdog publishes presence with `status` (`ready` or `estop`) and `estop`. It also declares a Zenoh liveliness token at `{fleet}/{robot}/_rosie/watchdog`. Fleet membership follows the heartbeat. Liveliness is a faster hint that the process is gone; it is not the contract, because a single dropped token should not remove a robot that is still publishing. To compare the two under loss, use `tools/sim/presence_netem.sh` on a Linux machine that can run `tc netem`.
