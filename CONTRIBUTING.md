# Contributing

1. Robot-specific topic names belong in `python/rosie/profiles/`, not in the
   laptop tools. A profile is read both to encode and decode on the laptop
   and to write the bridge config.
2. The Zenoh router and `zenoh-bridge-ros2dds` are pinned together (1.9.0).
   When you bump them, update the SHA256 list in `python/rosie/bootstrap.py`
   from the upstream checksum file or from the zip you downloaded. Do not
   invent a hash.
3. CDR fixtures live in `python/tests/fixtures/`. If a message definition
   changes, regenerate the bytes with `rosie.ros.codec.encode` and commit
   them. Tests compare against those files.
4. The headless robot is `tools/sim/docker-compose.yml`. It is not run in
   the unit tests. `pytest python/tests` must pass without ROS and without
   Docker.

See [docs/motivation.md](docs/motivation.md) for what Rosie is for.
