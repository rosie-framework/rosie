# Viz

`rosie viz` is a browser view of poses and trails.

```bash
rosie viz --fleet lab
```

It listens for `pose`, `odom`, and `amcl_pose` under the fleet and decodes JSON or CDR. Odometry and `PoseWithCovarianceStamped` both become a trail. A camera, if you select a robot, is `camera/compressed` or `camera/image_raw/compressed`, as JPEG or as `sensor_msgs/msg/CompressedImage`.

Open the URL it prints (port 8765 by default). Stale poses fade after a few seconds without a new sample.

To replay a bag into the same view, pass the bag path the CLI accepts (`rosie viz --help`). Recording is `rosie bag record`. Export to MCAP with `rosie bag export`. If the bag was recorded with `--profile` and `--robot`, the MCAP channels for those topics use `ros2msg` schemas and CDR, which Foxglove can decode.
