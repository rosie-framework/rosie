# Minimal pub/sub example

JSON on a user key. Pose, velocity, and goals are ROS messages on the
robot's profile topics, not this example.

```bash
# terminal 1
rosie fleet init --fleet lab
rosie router --fleet lab

# terminal 2
python talker.py

# terminal 3
python listener.py
```

Install first: `pip install -e ../../python` and `rosie setup` once while online.
