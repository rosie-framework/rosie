"""ST VL53L1X ToF over smbus2 (Linux).

Init sequence adapted from Adafruit CircuitPython VL53L1X (MIT):
https://github.com/adafruit/Adafruit_CircuitPython_VL53L1X
"""

from __future__ import annotations

import struct
import time
from typing import Any

from smbus2 import i2c_msg

# Config blob written starting at register 0x002D (Adafruit / ST ULD).
_INIT_SEQ = bytes(
    [
        0x00, 0x00, 0x00, 0x01, 0x02, 0x00, 0x02, 0x08, 0x00, 0x08, 0x10, 0x01,
        0x01, 0x00, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x0F, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x20, 0x0B, 0x00, 0x00, 0x02, 0x0A, 0x21, 0x00, 0x00, 0x05, 0x00,
        0x00, 0x00, 0x00, 0xC8, 0x00, 0x00, 0x38, 0xFF, 0x01, 0x00, 0x08, 0x00,
        0x00, 0x01, 0xCC, 0x0F, 0x01, 0xF1, 0x0D, 0x01, 0x68, 0x00, 0x80, 0x08,
        0xB8, 0x00, 0x00, 0x00, 0x00, 0x0F, 0x89, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x01, 0x0F, 0x0D, 0x0E, 0x0E, 0x00, 0x00, 0x02, 0xC7, 0xFF,
        0x9B, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00,
    ]
)

_I2C_SLAVE__DEVICE_ADDRESS = 0x0001
_VHV_CONFIG__TIMEOUT_MACROP_LOOP_BOUND = 0x0008
_GPIO__TIO_HV_STATUS = 0x0031
_SYSTEM__INTERRUPT_CLEAR = 0x0086
_SYSTEM__MODE_START = 0x0087
_RESULT__RANGE_STATUS = 0x0089
_RESULT__FINAL_CROSSTALK_CORRECTED_RANGE_MM_SD0 = 0x0096
_IDENTIFICATION__MODEL_ID = 0x010F
_DEFAULT_ADDR = 0x29


class Vl53l1xRange:
    """Continuous-ranging VL53L1X; ``read_range()`` returns meters or None."""

    def __init__(
        self,
        *,
        bus: int = 1,
        addr: int = _DEFAULT_ADDR,
        xshut: int | None = None,
        boot_addr: int = _DEFAULT_ADDR,
    ) -> None:
        from rosie.run.drivers import require_smbus2

        smbus2 = require_smbus2()
        self._bus = smbus2.SMBus(int(bus))
        self._addr = int(boot_addr) & 0x7F
        self._xshut = int(xshut) if xshut is not None else None
        self._gpio = None
        self._ok = False

        if self._xshut is not None:
            from rosie.run.drivers import require_lgpio

            lgpio = require_lgpio()
            self._gpio = lgpio.gpiochip_open(0)
            lgpio.gpio_claim_output(self._gpio, self._xshut, 0)
            time.sleep(0.01)
            lgpio.gpio_write(self._gpio, self._xshut, 1)
            time.sleep(0.01)

        info = self._read_reg(_IDENTIFICATION__MODEL_ID, 3)
        if info[0] != 0xEA or info[1] != 0xCC:
            raise RuntimeError(
                f"VL53L1X unexpected id bytes {info[0]:02X}{info[1]:02X}"
            )

        target = int(addr) & 0x7F
        if target != self._addr:
            self._write_reg(_I2C_SLAVE__DEVICE_ADDRESS, bytes([target]))
            self._addr = target
            time.sleep(0.01)

        self._write_reg(0x002D, _INIT_SEQ)
        self._start()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not self._data_ready():
            time.sleep(0.01)
        self._clear_interrupt()
        self._stop()
        self._write_reg(_VHV_CONFIG__TIMEOUT_MACROP_LOOP_BOUND, b"\x09")
        self._write_reg(0x000B, b"\x00")
        self._start()
        self._ok = True

    @classmethod
    def from_config(cls, sens: dict[str, Any]) -> Vl53l1xRange:
        i2c = sens.get("i2c") or {}
        xshut = sens.get("xshut")
        return cls(
            bus=int(i2c.get("bus", 1)),
            addr=int(i2c.get("addr", _DEFAULT_ADDR)),
            xshut=int(xshut) if xshut is not None else None,
        )

    def _write_reg(self, reg: int, data: bytes) -> None:
        payload = struct.pack(">H", reg) + data
        write = i2c_msg.write(self._addr, payload)
        self._bus.i2c_rdwr(write)

    def _read_reg(self, reg: int, length: int = 1) -> bytes:
        write = i2c_msg.write(self._addr, struct.pack(">H", reg))
        read = i2c_msg.read(self._addr, length)
        self._bus.i2c_rdwr(write, read)
        return bytes(read)

    def _start(self) -> None:
        self._write_reg(_SYSTEM__MODE_START, b"\x40")

    def _stop(self) -> None:
        self._write_reg(_SYSTEM__MODE_START, b"\x00")

    def _clear_interrupt(self) -> None:
        self._write_reg(_SYSTEM__INTERRUPT_CLEAR, b"\x01")

    def _data_ready(self) -> bool:
        # Active-low interrupt polarity after Adafruit init (bit4 of mux = 1).
        return (self._read_reg(_GPIO__TIO_HV_STATUS)[0] & 0x01) == 0

    def read_range(self) -> float | None:
        if not self._ok:
            return None
        try:
            deadline = time.monotonic() + 0.2
            while time.monotonic() < deadline and not self._data_ready():
                time.sleep(0.005)
            if not self._data_ready():
                return None
            status = self._read_reg(_RESULT__RANGE_STATUS)[0]
            raw = self._read_reg(_RESULT__FINAL_CROSSTALK_CORRECTED_RANGE_MM_SD0, 2)
            self._clear_interrupt()
            # 0x09 = range valid (Adafruit).
            if status != 0x09:
                return None
            mm = struct.unpack(">H", raw)[0]
            return mm * 0.001
        except Exception:
            return None

    def close(self) -> None:
        try:
            if self._ok:
                self._stop()
        except Exception:
            pass
        try:
            self._bus.close()
        except Exception:
            pass
        if self._gpio is not None and self._xshut is not None:
            try:
                from rosie.run.drivers import require_lgpio

                lgpio = require_lgpio()
                lgpio.gpio_write(self._gpio, self._xshut, 0)
                lgpio.gpiochip_close(self._gpio)
            except Exception:
                pass
        self._gpio = None
        shared = getattr(self, "_rosie_xshut_gpio", None)
        if shared is not None:
            try:
                from rosie.run.drivers import require_lgpio

                require_lgpio().gpiochip_close(shared)
            except Exception:
                pass
            try:
                delattr(self, "_rosie_xshut_gpio")
            except Exception:
                pass
        self._ok = False
