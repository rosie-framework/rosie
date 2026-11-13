"""Pinned versions for the ROS 2 bridge path.

``zenoh-bridge-ros2dds`` 1.9.0 is built against Eclipse Zenoh 1.9.0, which is
the same pin as ``rosie setup`` (``ZENOHD_VERSION`` in ``bootstrap.py``).

Key layout, from the bridge sources (``ros2_name_to_key_expr``), does not
change between Humble, Jazzy, and Lyrical. What changes is ``rmw_zenoh``:
Humble data keys end in ``TypeHashNotSupported``; Jazzy and Lyrical append an
``RIHS01_`` type hash. The two layouts are not interoperable.

Bridge liveliness tokens advertise individual routes
(``@/<zenoh_id>/@ros2_lv/MP/...``), not a robot. Fleet presence stays a 1 Hz
JSON heartbeat from the on-robot watchdog.
"""

ZENOH_BRIDGE_ROS2DDS_VERSION = "1.9.0"

# Distros whose CDR layout for the fleet message set rosbags can encode.
SUPPORTED_DISTROS = ("humble", "jazzy", "lyrical")
