#!/bin/sh
# Compare a 1 Hz presence heartbeat with Zenoh liveliness under loss.
# Linux only (tc netem). Run on the machine that forwards the robot link,
# not on the Mac laptop. This does not invent results: it prints what to
# record (false leaves, rejoin time) for the fleet contract.
set -eu
DEV="${1:-eth0}"
echo "Apply 20% loss on $DEV for 30s, then clear."
echo "  sudo tc qdisc add dev $DEV root netem loss 20%"
echo "  # watch: rosie fleet list --fleet lab"
echo "  # a missed heartbeat should not drop the robot before ~3s"
echo "  sudo tc qdisc del dev $DEV root"
echo "Then repeat with delay 200ms and a 10s blackout (loss 100%)."
echo "Record false leaves and rejoin time for the heartbeat and for"
echo "a liveliness token on {fleet}/{robot}/_rosie/watchdog."
echo "The contract keeps the heartbeat. Liveliness is an extra fast signal."
