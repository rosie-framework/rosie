#!/bin/sh
# Resident memory and CPU of the bridge and the watchdog, next to Nav2.
# Run on the robot (or the Linux machine running the sim). Do not treat
# a laptop number as the board minimum.
set -eu
echo "Nav2's published floor is a Raspberry Pi 4 with 4 GB."
echo "On the robot, while Nav2 is up:"
ps -C zenoh-bridge-ros2dds,python3 -o pid,rss,pcpu,comm
echo "rss is kilobytes. Add the bridge and the rosie-watchdog rows."
