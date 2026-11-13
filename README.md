# Rosie

Rosie is a fleet layer and a set of laptop tools for robots that already run ROS 2. The laptop talks Zenoh. A [zenoh-bridge-ros2dds](https://github.com/eclipse-zenoh/zenoh-plugin-ros2dds) on each robot turns that into DDS, so Nav2, the vendor drivers, and the rest of the ROS stack stay as they are.

You do not put ROS on the laptop to drive the fleet. You do not put Rosie firmware on a microcontroller. A robot is a Linux computer running ROS 2 that honours the [fleet contract](docs/conventions.md).

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

## 0.5.0

Rosie no longer ships a robot stack. These commands are gone:

| Removed | Use instead |
|---|---|
| `rosie mcu` | A ROS 2 driver on the robot. See [Microcontrollers](docs/robots/microcontrollers.md) |
| `rosie run` | The robot's own ROS 2 launch |
| `rosie drivers` / `rosie tune` | The ROS 2 driver's parameters |
| `rosie agent` | `rosie robot setup` and the DDS bridge |
| `robot.yaml` | A profile, plus the bridge config `rosie robot setup` writes |

## Docs

[Getting started](docs/getting-started.md) · [Architecture](docs/architecture.md) · [When to use Rosie](docs/motivation.md) · [Fleet contract](docs/conventions.md) · [Add a robot](docs/robots/adding-a-robot.md)
