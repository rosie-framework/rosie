# Camera

Rosie carries camera data as a **stream of independent JPEG frames**, not a video
codec stream. Each sample on `camera/compressed` is one complete JPEG — there is
no H.264/MJPEG container, no keyframes, and no stream negotiation.

Camera works on **both platforms**: MCU (`esp32s3_eye` / `custom` DVP boards) and
Linux (`picamera2` / `v4l2` / BYO). Inventory: [Drivers](drivers.md#camera).

## Wire format

| Property | Value |
|----------|-------|
| Topic | `camera/compressed` (`topics.CAMERA_COMPRESSED`), robot → host |
| Payload | Raw JPEG bytes — not JSON, no `stamp` field |
| Framing | One whole frame per sample |
| Delivery class | **BULK** (DROP, `DATA_LOW`) |

Because frames are independent, a dropped sample costs exactly one frame. That
is why camera is the one standard topic published as raw bytes
([Conventions → Binary vs JSON](../conventions.md#binary-vs-json-topics)) and
demoted to BULK, which keeps large frames out of the same priority queue as
commands ([Conventions → Delivery and validity](../conventions.md#delivery-and-validity)).

Publishing `camera/compressed` is a **MAY** in the fleet robot contract: a robot
is a full fleet member without a camera.

## `jpeg_quality` scale

`camera.jpeg_quality` is always **0–100, higher = better** (standard JPEG), on
both MCU and Linux. Default is `70`.

MCU firmware uses esp_camera's opposite scale (0–63, **lower** = better).
`rosie mcu gen-config` translates at codegen time:

```text
esp_q = clamp(round(63 - q * 63 / 100), 10..63)
```

So `jpeg_quality: 70` becomes esp ≈ 19 — the same picture the old default of
`18` produced. Values below `30` still validate, but `gen-config` warns that
they look like the pre-unification esp scale; prefer ~70.

## `robot.yaml`

### MCU

```yaml
camera:
  board: esp32s3_eye     # or: custom (+ camera.pins)
  jpeg_quality: 70       # 0–100, higher = better (codegen maps to esp_camera)
  pub_hz: 2              # frames per second published
  enable_default: true   # stream on boot, or wait for camera_enable
```

| Key | Default | Meaning |
|-----|---------|---------|
| `board` | `esp32s3_eye` | Board preset; alias `freenove_esp32s3_cam`. Use `custom` to supply your own DVP pins |
| `pins` | preset | Required when `board: custom` — `xclk`, `siod`, `sioc`, `y2`–`y9`, `vsync`, `href`, `pclk` (+ optional `pwdn`, `reset`) |
| `jpeg_quality` | `70` | 0–100, higher = better; mapped to esp_camera at codegen |
| `pub_hz` | `2` | Publish rate in Hz |
| `enable_default` | `true` | Whether the camera streams immediately after boot |

MCU values are baked into firmware by `rosie mcu gen-config` (as `ROSIE_CAMERA_*`
in `src/generated/robot_config.h`), so changing them means regenerate and
reflash. Frame size is fixed at QVGA (320×240) with frames buffered in PSRAM.

### Linux (`rosie run`)

```yaml
camera:
  driver: picamera2      # or: v4l2 | python
  width: 640
  height: 480
  jpeg_quality: 70       # 0–100, higher = better
  pub_hz: 2
  enable_default: true
  vflip: false
  # device: /dev/video0  # v4l2 only
  # class: mypkg:MyCam   # python only (read_jpeg / close)
```

| Key | Default | Meaning |
|-----|---------|---------|
| `driver` | `picamera2` | Capture backend |
| `width` / `height` | `640` / `480` | Capture size (larger frames cost more bandwidth) |
| `jpeg_quality` | `70` | 0–100, higher = better |
| `pub_hz` | `2` | Publish rate in Hz |
| `enable_default` | `true` | Stream on start, or wait for `camera_enable` |
| `vflip` / `hflip` | `false` | Optional flips |
| `device` | `0` | V4L2 path or index (`/dev/video0` or `0`) |
| `class` | — | Required when `driver: python` |

Omit the whole `camera:` section for no camera. Linux picks up YAML changes on
the next `rosie run` restart (no reflash).

#### Linux install notes

| Driver | Install |
|--------|---------|
| `v4l2` | `pip install "rosie-framework[camera]"` (OpenCV) |
| `picamera2` | **Not pip.** On Raspberry Pi OS: `sudo apt install -y python3-picamera2`. If `rosie run` lives in a venv, create it with `--system-site-packages` so the apt package is visible. |
| `python` | Your own module; no extra required |

Capture runs on a **daemon thread**, not the control tick — JPEG encode on a Pi
can take tens of milliseconds and must not stall `control.dt_ms`.

## Frame rate

`camera.pub_hz` **is** the frame rate on the bus. The capture loop publishes a
frame then sleeps `1 / pub_hz` seconds. Captures do not queue: if one runs long,
the next simply happens later, so the actual rate is a ceiling rather than a
guarantee.

Bandwidth is roughly `frame_bytes × pub_hz`, and it shares the robot's link with
control traffic. Raising `pub_hz` (or Linux `width`/`height`) for a smoother
picture costs airtime that `cmd_vel` and `pose` also need. BULK means a
congested link sheds camera frames before commands, so the failure mode is a
stuttery picture rather than sluggish driving — but the airtime is still spent.
Prefer a lower `pub_hz` (or a lower `jpeg_quality`) on a busy fleet.

Host viewers apply their own display throttle on top of this: `rosie viz` renders
about 8 Hz regardless of how fast frames arrive.

## Enabling and disabling

`enable_default` sets the boot/start state. At runtime, the `camera_enable` op
on the `cmd` topic toggles streaming:

```python
bot.set_camera_enable(False)   # stop publishing frames
bot.set_camera_enable(True)    # resume
```

Both platforms register the handler only when a camera is attached; if the
sensor fails to initialize, the robot logs and continues without a camera.
Disabled means no frames are published — the capture loop idles.

`snap()`, `camera_live()`, and the viz camera panel all publish `camera_enable`
themselves, so you rarely call `set_camera_enable` directly.

## Host tools

| Tool | What it does |
|------|--------------|
| `MobileRobot.snap(...)` | Grab one JPEG, save under `captures/`, open it in a viewer |
| `MobileRobot.camera_live(...)` | Live preview window; prints frame sizes if OpenCV is missing |
| `rosie drive` → `snap` / `cam` | Same two, from the REPL |
| `rosie viz` | Camera panel for the selected robot, live or from a bag |
| `rosie bag record` | Frames are recorded like any other topic |

The OpenCV viewers are an optional host-side extra (same extra Linux `v4l2`
uses on-robot):

```bash
pip install "rosie-framework[camera]"
```

Robots publish `camera/compressed` regardless — the extra only affects what the
laptop can display (and the Linux `v4l2` capture backend).

For a raw subscription, camera is a bytes topic, not a JSON one:

```python
session.subscribe_bytes(topics.CAMERA_COMPRESSED, lambda jpeg: ...)
```

## Recording

`rosie bag record` captures camera samples along with everything else,
base64-encoded in the bag; `rosie viz --bag` replays them in the camera panel.
JPEG frames dwarf JSON telemetry, so a long recording with camera enabled gets
large fast. Narrow the selector when you only want motion data:

```bash
rosie bag record --fleet lab --output run.rosiebag --key "*/pose"
```

## Related

- [Drivers](drivers.md#camera) — supported boards / backends
- [Mobile base](mobile-base.md) — `robot.yaml`, topic table, `rosie drive`
- [Linux run](linux-run.md) — Pi / Jetson assembly
- [Firmware](firmware.md) — MCU `DiffDriveStack` assembly
- [MobileRobot](../host/mobile-robot.md#camera) — host camera API
- [Viz](../host/viz.md#camera) — browser camera panel
- [Conventions](../conventions.md#delivery-and-validity) — BULK delivery class
