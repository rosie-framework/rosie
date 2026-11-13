# Rosie (Python)

```bash
pip install -e .          # laptop: Session, CLI, router, viz, bags
pip install -e ".[robot]" # same packages; on a robot, create the venv with
                          #   python3 -m venv --system-site-packages
                          # so the watchdog can import rclpy
pip install -e ".[camera]"

rosie setup
rosie fleet init --fleet lab
rosie router --fleet lab
```

On a robot: `rosie robot setup --fleet lab --robot bot1 --profile rosmaster_x3`.

See [Getting started](../docs/getting-started.md).
