# Contributing

1. Shared chips, kinematics, `DiffDriveStack`, and `MobileBase` belong in this
   repository. **Pin maps, Wi‑Fi credentials, and per-robot gains stay in the
   robot’s `robot.yaml`** — not hardcoded in Rosie. To add an MCU driver that
   `DiffDriveStack` can select: implement under
   `firmware/.../drivers/<category>/` (`motors` / `encoders` / `imu` /
   `camera`), register it in `firmware/drivers/registry.yaml`
   (`status: supported`), emit selection macros from
   `python/rosie/robot_config.py` (`gen-config`), add a `DiffDriveStack` `#if`
   branch, and document it in [docs/robots/drivers.md](docs/robots/drivers.md). Linux-only
   drivers need `python/rosie/run/drivers/` + registry. A driver `.cpp` alone
   is not enough for stack selection.
2. After editing `interfaces/std_msgs.yaml`, run `python3 interfaces/gen.py` and commit
   the generated files. Also update [docs/messages.md](docs/messages.md).
3. When bumping the pinned `zenohd` version in `python/rosie/bootstrap.py`, update the
   per-platform SHA256 digests from https://download.eclipse.org/zenoh/zenoh/\<version\>/sha256sums.txt.
4. Prefer small PRs: API, docs, examples, or codegen.

See [docs/motivation.md](docs/motivation.md) for project goals.
