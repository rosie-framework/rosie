# Rosie

Rosie is a fleet layer and a set of laptop tools for robots that already run ROS 2. The laptop talks Zenoh. A [zenoh-bridge-ros2dds](https://github.com/eclipse-zenoh/zenoh-plugin-ros2dds) on each robot turns that into DDS, so Nav2, the vendor drivers, and the rest of the ROS stack stay as they are.

You do not put ROS on the laptop to drive the fleet. You do not put Rosie firmware on a microcontroller. A robot is a Linux computer running ROS 2 that honours the [fleet contract](docs/conventions.md).

## Why use Rosie

ROS 2 is built to run one robot well. Running several robots from a laptop with plain ROS 2 takes extra work. Rosie handles the parts ROS 2 leaves to you:

| With plain ROS 2 | With Rosie |
|---|---|
| Every laptop that drives a robot needs a matching ROS 2 install. That is hard on macOS. | The laptop runs `pip install`. Only the robots run ROS. |
| DDS discovery runs over Wi-Fi to every robot, and robots on one network see each other's topics unless you split domain IDs or namespaces by hand. | DDS stays on each robot. Only the topics in its profile go over the network, through one Zenoh router, under that robot's name (`lab/bot1/...`). |
| Humble and Jazzy robots are not supported talking to each other over DDS. | Each robot keeps its own distro. The laptop decodes each one with its profile. |
| ROS has no notion of which robots are in the fleet, and no fleet-wide stop. | `rosie fleet list` shows who is present, `fleet wait` holds until the team is up, and `fleet estop` stops every robot. |
| If the laptop or Wi-Fi drops while you are driving, the robot keeps executing the last command unless you wrote a timeout. | A watchdog on each robot stops it when teleop goes stale, the link is lost, or estop is pressed. |
| Teleop, viewing, and recording mean a different ROS tool and launch file per robot. | `rosie teleop`, `rosie viz` (in a browser), and `rosie bag` work on any robot in the fleet. Bags export to MCAP for Foxglove. |

Rosie does not change the robot's stack. Nav2, the vendor drivers, and the launch files stay as they are; Rosie adds the bridge and the watchdog next to them.

If you are working on one robot over a wired link and RViz plus the `ros2` CLI are enough, plain ROS 2 is simpler. Rosie is for a team of robots run from laptops over Wi-Fi, or for laptops that should not need ROS installed. You can still point RViz at a Rosie fleet later; see [ROS on the laptop](docs/robots/laptop-ros.md).

### What Rosie is not

Rosie does not replace Nav2, ros2_control, or a vendor base driver. It does not run on a microcontroller. It does not define its own messages for pose and velocity; those are ROS messages, carried as CDR.

The fleet contract is small on purpose. A robot qualifies if it can be seen, report a pose, accept a velocity, and stop when the fleet says stop. Navigation and a camera are optional. The contract is in [Conventions](docs/conventions.md).

### Rosie and `rmw_zenoh`

`rmw_zenoh` replaces DDS with Zenoh inside ROS 2. That is a choice about the robot's stack. Rosie uses the bridge instead: DDS stays on the robot, and only the topics you allow go onto the fleet network, under the robot's fleet name. Moving a robot you control to `rmw_zenoh` later is possible, but it uses a different key layout, and some bases (the TurtleBot 4's Create 3) run their own DDS and cannot switch the whole robot. [Add a robot](docs/robots/adding-a-robot.md) covers both.

## Install

```bash
pip install -e python
rosie setup
```

`rosie setup` downloads the Zenoh router (`zenohd` 1.9.0) into `~/.rosie/bin`. The laptop install does not need ROS.

## Three commands to a fleet

On the laptop:

```bash
rosie fleet init --fleet lab --secure
rosie router --fleet lab --secure
```

On the robot (a ROS 2 machine, Humble, Jazzy, or Lyrical):

```bash
rosie robot setup --fleet lab --robot bot1 --profile rosmaster_x3 --secure
```

Then, back on the laptop: `rosie fleet list --fleet lab --secure`, `rosie teleop --fleet lab --robot bot1 --profile rosmaster_x3 --secure`, `rosie viz --fleet lab --secure`.

A simulated robot, without hardware, is in [Getting started](docs/getting-started.md).

## What you can do

| Command | What it does |
|---|---|
| `rosie robot setup` | Write the bridge config, download the bridge, install the watchdog |
| `rosie robot doctor` | Check that config |
| `rosie teleop` / `rosie drive` | Drive one robot from the laptop |
| `rosie viz` | Poses and trails in a browser |
| `rosie bag record` / `export` | Record the bus and export MCAP with ROS 2 schemas |
| `rosie topic list` / `echo` | See keys and decode CDR when you pass `--type` |
| `rosie fleet list` / `wait` / `estop` | Who is here, bring-up, and stop the fleet |

Profiles live in `python/rosie/profiles/`. One profile tells the laptop how to encode and decode, and tells `rosie robot setup` what the bridge is allowed to carry.

## Docs

[Getting started](docs/getting-started.md) · [Architecture](docs/architecture.md) · [Fleet contract](docs/conventions.md) · [Add a robot](docs/robots/adding-a-robot.md)
