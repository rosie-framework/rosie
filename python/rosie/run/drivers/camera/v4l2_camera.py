"""USB / V4L2 webcam via OpenCV."""

from __future__ import annotations

from typing import Any


class V4l2CameraSource:
    """Capture JPEG frames from a V4L2 device (OpenCV)."""

    def __init__(
        self,
        *,
        device: str | int = 0,
        width: int = 640,
        height: int = 480,
        jpeg_quality: int = 70,
        vflip: bool = False,
        hflip: bool = False,
    ) -> None:
        from rosie.run.drivers import require_cv2

        cv2 = require_cv2()
        self._cv2 = cv2
        self._quality = int(jpeg_quality)
        self._vflip = bool(vflip)
        self._hflip = bool(hflip)
        # Accept "/dev/video0" or integer index.
        if isinstance(device, str) and device.isdigit():
            device = int(device)
        self._cap = cv2.VideoCapture(device)
        if not self._cap.isOpened():
            raise RuntimeError(f"failed to open V4L2 device {device!r}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(width))
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(height))

    @classmethod
    def from_config(cls, cam: dict[str, Any]) -> V4l2CameraSource:
        from rosie.run.drivers import camera_jpeg_quality

        return cls(
            device=cam.get("device", 0),
            width=int(cam.get("width", 640)),
            height=int(cam.get("height", 480)),
            jpeg_quality=camera_jpeg_quality(cam),
            vflip=bool(cam.get("vflip", False)),
            hflip=bool(cam.get("hflip", False)),
        )

    def read_jpeg(self) -> bytes | None:
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None
        cv2 = self._cv2
        if self._vflip:
            frame = cv2.flip(frame, 0)
        if self._hflip:
            frame = cv2.flip(frame, 1)
        ok, buf = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), self._quality],
        )
        if not ok:
            return None
        return buf.tobytes()

    def close(self) -> None:
        try:
            self._cap.release()
        except Exception:
            pass
