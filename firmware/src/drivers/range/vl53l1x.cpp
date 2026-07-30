#include "rosie/drivers/range/vl53l1x.h"

#include <Wire.h>

namespace rosie {

Vl53l1x::Vl53l1x(const Vl53l1xConfig& cfg) : cfg_(cfg) {}

bool Vl53l1x::begin() {
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

  sensor_.setDistanceMode(VL53L1X::Long);
  sensor_.setMeasurementTimingBudget(cfg_.timing_budget_us);
  sensor_.startContinuous(cfg_.inter_measurement_ms);
  ok_ = true;
  return true;
}

bool Vl53l1x::readRangeM(float* range_m) {
  if (!ok_ || !range_m) return false;
  uint16_t mm = sensor_.read(true);
  if (sensor_.timeoutOccurred()) return false;
  // 0 / 65535 often indicate no target; still publish but mark via caller ok.
  *range_m = static_cast<float>(mm) * 0.001f;
  return true;
}

}  // namespace rosie
