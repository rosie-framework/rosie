"""Raspberry Pi CSI camera via picamera2."""

from __future__ import annotations

import io
from typing import Any


class Picamera2Source:
    """Capture JPEG frames from a Pi CSI camera (picamera2)."""

    def __init__(
        self,
        *,
        width: int = 640,
        height: int = 480,
        jpeg_quality: int = 70,
        vflip: bool = False,
        hflip: bool = False,
    ) -> None:
        from rosie.run.drivers import require_picamera2

        Picamera2 = require_picamera2()
        self._cam = Picamera2()
        kwargs: dict[str, Any] = {"main": {"size": (int(width), int(height))}}
        if hflip or vflip:
            try:
                from libcamera import Transform

                kwargs["transform"] = Transform(
                    hflip=bool(hflip), vflip=bool(vflip)
                )
            except ImportError:
                pass
        config = self._cam.create_video_configuration(**kwargs)
        self._cam.configure(config)
        self._cam.options["quality"] = int(jpeg_quality)
        self._cam.start()

    @classmethod
    def from_config(cls, cam: dict[str, Any]) -> Picamera2Source:
        from rosie.run.drivers import camera_jpeg_quality

        return cls(
            width=int(cam.get("width", 640)),
            height=int(cam.get("height", 480)),
            jpeg_quality=camera_jpeg_quality(cam),
            vflip=bool(cam.get("vflip", False)),
            hflip=bool(cam.get("hflip", False)),
        )

    def read_jpeg(self) -> bytes | None:
        try:
            buf = io.BytesIO()
            self._cam.capture_file(buf, format="jpeg")
            data = buf.getvalue()
            return data if data else None
        except Exception:
            return None

    def close(self) -> None:
        try:
            self._cam.stop()
        except Exception:
            pass
        try:
            self._cam.close()
        except Exception:
            pass
