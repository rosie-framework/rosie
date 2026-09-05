# Minimal pub/sub example

Requires `pip install -e ../../python` (and `rosie setup` once while online).

```bash
# terminal 1
rosie fleet init --fleet lab   # once
rosie router --fleet lab
# escape hatch: zenohd -c ../../tools/zenoh.json5

# terminal 2
python talker.py

# terminal 3
python listener.py
```
