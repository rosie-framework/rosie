#include "rosie/drivers/range/vl53l0x.h"

#include <Wire.h>

namespace rosie {

Vl53l0x::Vl53l0x(const Vl53l0xConfig& cfg) : cfg_(cfg) {}

bool Vl53l0x::begin() {
  ok_ = false;
  if (cfg_.begin_wire) {
    Wire.begin(cfg_.sda, cfg_.scl);
    Wire.setClock(400000);
  }

  if (cfg_.xshut >= 0) {
    pinMode(cfg_.xshut, OUTPUT);
    digitalWrite(cfg_.xshut, LOW);
    delay(10);
    digitalWrite(cfg_.xshut, HIGH);
    delay(10);
  }

  sensor_.setTimeout(500);
  if (!sensor_.init()) {
    return false;
  }

  if (cfg_.addr != 0x29) {
    sensor_.setAddress(cfg_.addr);
  }

  // Long-range-ish: raise signal-rate limit and stretch timing budget.
  sensor_.setSignalRateLimit(0.1);
  sensor_.setMeasurementTimingBudget(cfg_.timing_budget_us);
  sensor_.startContinuous(cfg_.inter_measurement_ms);
  ok_ = true;
  return true;
}

bool Vl53l0x::readRangeM(float* range_m) {
  if (!ok_ || !range_m) return false;
  uint16_t mm = sensor_.readRangeContinuousMillimeters();
  if (sensor_.timeoutOccurred()) return false;
  // Pololu returns 65535 on timeout; treat out-of-range markers as failure.
  if (mm == 0 || mm >= 8190) return false;
  *range_m = static_cast<float>(mm) * 0.001f;
  return true;
}

}  // namespace rosie
