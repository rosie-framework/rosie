# Rosie (Python)

```bash
pip install -e .                 # host: Session, CLI, router, viz, bags / MCAP export
pip install -e ".[mcu]"          # + MCU build / flash (PlatformIO)
pip install -e ".[linux]"        # + Pi/Jetson GPIO / I2C for `rosie run`
pip install -e ".[camera]"       # + OpenCV for `rosie drive` snap / cam
# or: pip install -e ".[mcu,camera,linux]"

rosie setup
rosie router
rosie doctor
# MCU boards only (not Pi/Jetson):
# rosie mcu setup && rosie mcu flash
# Linux-native base on Pi/Jetson:
# rosie run --config robot.yaml   # requires platform: linux in robot.yaml
```

See [`../docs/getting-started.md`](../docs/getting-started.md).
