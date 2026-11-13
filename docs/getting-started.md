# Getting started

Rosie runs on the laptop. ROS 2 runs on the robot. The bridge in between is `zenoh-bridge-ros2dds` 1.9.0, the same Zenoh series as the router.

## Laptop

```bash
pip install -e python
rosie setup
rosie doctor
```

`rosie doctor` checks that the router binary is present and that the local listen port answers. It does not need a robot.

## One simulated robot

Start the router:

```bash
rosie fleet init --fleet lab
rosie router --fleet lab
```

In another terminal, from the repo root, start the headless robot. Pick one image tag. Humble, Jazzy, and Lyrical use the same compose file:

```bash
ROS_IMAGE=ros:humble ROS_DISTRO=humble docker compose -f tools/sim/docker-compose.yml up
```

The robot container publishes `/odom`, `/amcl_pose`, a tiny JPEG, and a `NavigateToPose` action server. The bridge container connects to `host.docker.internal:7447` and exposes those topics as `lab/bot1/...`.

In a third terminal, publish presence (the watchdog does this on a real robot):

```bash
python tools/sim/presence_stub.py --fleet lab --robot bot1 --profile default_ros2
```

Then:

```bash
rosie fleet list --fleet lab
rosie topic echo --fleet lab --key bot1/odom --type nav_msgs/msg/Odometry --count 1
rosie teleop --fleet lab --robot bot1 --profile default_ros2
rosie viz --fleet lab
```

`default_ros2` commands `geometry_msgs/msg/TwistStamped` on `/cmd_vel`. Pass the profile that matches the robot. Some profiles use `Twist` instead. The list is in [Add a ROS 2 robot](robots/adding-a-robot.md).

Record and export:

```bash
rosie bag record --fleet lab --robot bot1 --profile default_ros2 -o /tmp/lab.rosiebag --duration 5
rosie bag export /tmp/lab.rosiebag -o /tmp/lab.mcap
```

## One real robot

### Before you start

- The robot runs Linux and ROS 2 (Humble, Jazzy, or Lyrical). Its driver already publishes a pose and accepts velocity commands.
- You can SSH into the robot, and it is on the same network as the laptop.
- `rosie router --fleet lab` is running on the laptop. `LAPTOP_IP` below is the laptop's address on that network.
- `PROFILE` below is the profile for this robot. The list is in [Add a ROS 2 robot](robots/adding-a-robot.md). Use `default_ros2` if none matches.

Rosie adds two processes to the robot. Both run the whole time it is on the fleet:

| Command | What it does |
|---|---|
| `rosie robot run` | Starts `zenoh-bridge-ros2dds`, which carries the robot's ROS topics to the laptop |
| `rosie robot watchdog` | Publishes presence, and stops the robot on estop, a stale teleop command, or a lost link |

You set these up once per robot. After that, systemd starts them at boot.

### 1. Copy Rosie to the robot

On the laptop, from the repo root:

```bash
rsync -a --exclude .venv ./ USER@ROBOT:~/rosie/
```

`--exclude .venv` leaves the laptop's virtualenv behind. It is built for the laptop and does not run on the robot.

### 2. Install it on the robot

On the robot. Replace `humble` with the robot's distro:

```bash
export ROS_DISTRO=humble
source /opt/ros/$ROS_DISTRO/setup.bash
python3 -m venv --system-site-packages ~/rosie-venv
source ~/rosie-venv/bin/activate
source /opt/ros/$ROS_DISTRO/setup.bash
pip install -e ~/rosie/python
```

`--system-site-packages` lets the virtualenv see ROS's Python packages. Sourcing ROS again after activating puts `rclpy` back on the path. In any new shell on the robot, run the `activate` line and the second `source` line before using `rosie`.

### 3. Configure it

```bash
cd ~
rosie robot setup --fleet lab --robot bot1 --profile PROFILE --connect tcp/LAPTOP_IP:7447
rosie robot doctor
```

`setup` writes `~/rosie-bridge.json5`, downloads the bridge, and installs two user services, `rosie-bridge` and `rosie-watchdog`. `doctor` checks that file. Run it from the same directory.

`--connect auto` finds the router without its address. It needs multicast to work on the network. If the robot does not appear, use the address.

### 4. Start it

The first time, run the two processes by hand in two SSH sessions, so you can see their output:

```bash
rosie robot run --config ~/rosie-bridge.json5
```

```bash
rosie robot watchdog --fleet lab --robot bot1 --profile PROFILE
```

Once the robot shows up in step 5, stop both with Ctrl-C. Then, still on the robot in that SSH session, run:

```bash
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now rosie-bridge.service rosie-watchdog.service
```

This registers the bridge and the watchdog as services, starts them now, and starts them again at every boot, including after you log out. To follow their logs:

```bash
journalctl --user -u rosie-bridge -u rosie-watchdog -f
```

### 5. Check it from the laptop

```bash
rosie fleet list --fleet lab
rosie teleop --fleet lab --robot bot1 --profile PROFILE
```

`bot1` should appear within a couple of seconds. If it does not, run `ros2 topic list` on the robot and confirm the topics the profile names are there.

### Secure mode

Use secure mode on any network you do not control. Every machine on the fleet then needs the same fleet secret.

1. On the laptop, create the secret and enroll the robot. Secure mode only lists enrolled robots:

   ```bash
   rosie fleet init --fleet lab --secure
   rosie fleet add --fleet lab --robot bot1 --profile PROFILE
   ```

   `fleet init` prints the secret. If `lab` already exists, run `rosie fleet secret --fleet lab --rotate` instead. It prints a new secret and keeps the robot list.

2. Restart the router with `rosie router --fleet lab --secure`.

3. On the robot, store the secret (it prompts for it), then run setup again with `--secure`:

   ```bash
   rosie fleet secret --fleet lab --set
   rosie robot setup --fleet lab --robot bot1 --profile PROFILE --connect tcp/LAPTOP_IP:7447 --secure
   ```

   Add `--secure` to the watchdog command too if you run it by hand.

4. On the laptop, add `--secure` to `fleet list`, `teleop`, `viz`, and the other tools.

More detail: [Security](fleet/security.md).

## Next

- [Add a ROS 2 robot](robots/adding-a-robot.md) — profiles, the bridge, and rmw_zenoh
- [Safety](robots/safety.md) — deadman, estop, link loss
- [Fleet contract](conventions.md) — what a robot must honour
