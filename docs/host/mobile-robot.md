# MobileRobot

`MobileRobot` is the laptop handle for one robot. It reads a profile, subscribes to the pose topic, and publishes velocity as CDR.

```python
from rosie import MobileRobot

bot = MobileRobot("bot1", fleet="lab", profile="rosmaster_x3")
bot.teleop()          # WASD, until you quit
bot.drive_to(1.0, 2.0)
bot.stop()            # zero twist, and cancel the current goal
frame = bot.snap()    # JPEG bytes, if the profile has a camera
bot.close()
```

`drive_to` sends `NavigateToPose` through the bridge action keys and waits for the result. `stop` publishes a zero twist and cancels that goal. There is no `zero`, `set_gains`, or `set_camera_enable`; those belonged to the old native base.

Pose is whatever the profile names. `bot.pose` is `x`, `y`, `theta` in radians, and `heading_deg`. Odometry and `PoseWithCovarianceStamped` both work. Yaw comes from the quaternion.

The profile's `cmd_vel_gate` flag decides the command topic. When it is false (the default), velocity goes to the profile topic and the bridge delivers it. When it is true, velocity goes to `{topic}_teleop` so the watchdog can forward it. See [Safety](../robots/safety.md).

`rosie drive --fleet lab --robot bot1 --profile rosmaster_x3` is a small REPL over the same object: `x y` to `drive_to`, `teleop`, `snap`, `cam`, `stop`, `quit`.

`rosie teleop` does not construct a `MobileRobot`. It publishes the profile velocity directly, with a one-second command envelope.
