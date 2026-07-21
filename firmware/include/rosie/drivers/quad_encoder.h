#pragma once

#include <Arduino.h>
#include <ESP32Encoder.h>
#include <stdint.h>

namespace rosie {

/** One quadrature channel (A/B pair) via ESP32Encoder. */
class QuadEncoder {
 public:
  QuadEncoder() = default;
  void begin(int pin_a, int pin_b);
  void clear();
  int32_t count();

 private:
  mutable ESP32Encoder enc_;
  bool ok_ = false;
};

/** Left + right wheel encoders for a differential base. */
class DiffDriveEncoders {
 public:
  void begin(int left_a, int left_b, int right_a, int right_b);
  void clear();
  void read(int32_t* left, int32_t* right);

 private:
  QuadEncoder left_;
  QuadEncoder right_;
};

}  // namespace rosie
