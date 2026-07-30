#pragma once

#include <Arduino.h>
#include <VL53L1X.h>
#include <stdint.h>

namespace rosie {

struct Vl53l1xConfig {
  uint8_t addr = 0x29;
  int xshut = -1;           // GPIO, or -1 if unused
  bool begin_wire = false;  // true only for the first device on a fresh bus
  int sda = 1;
  int scl = 2;
  uint32_t timing_budget_us = 50000;
  uint32_t inter_measurement_ms = 50;
};

/** Thin wrapper around Pololu VL53L1X (continuous ranging, meters). */
class Vl53l1x {
 public:
  explicit Vl53l1x(const Vl53l1xConfig& cfg = {});

  /**
   * Bring up the sensor. When ``xshut`` is set, caller should hold other
   * sensors' XSHUT low before calling so address assignment is unique.
   */
  bool begin();
  bool ok() const { return ok_; }
  void configure(const Vl53l1xConfig& cfg) { cfg_ = cfg; }
  /** Distance in meters, or false on timeout / failure. */
  bool readRangeM(float* range_m);

 private:
  Vl53l1xConfig cfg_;
  VL53L1X sensor_;
  bool ok_ = false;
};

}  // namespace rosie
