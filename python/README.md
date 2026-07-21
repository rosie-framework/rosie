# Rosie (Python)

```bash
pip install -e .
# MCU tooling (PlatformIO / flash):
pip install -e ".[mcu]"
# Host camera snap / live view in `rosie drive` (OpenCV):
pip install -e ".[camera]"
# both:
pip install -e ".[mcu,camera]"

rosie setup
rosie router
rosie doctor
# MCU boards only (not Pi/Jetson):
# rosie mcu setup && rosie mcu flash
```

See [`../docs/getting-started.md`](../docs/getting-started.md).
