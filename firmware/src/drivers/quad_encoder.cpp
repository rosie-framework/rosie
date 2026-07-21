#include "rosie/drivers/quad_encoder.h"

namespace rosie {

void QuadEncoder::begin(int pin_a, int pin_b) {
  ESP32Encoder::useInternalWeakPullResistors = puType::up;
  enc_.attachFullQuad(pin_a, pin_b);
  enc_.clearCount();
  ok_ = true;
}

void QuadEncoder::clear() {
  if (ok_) enc_.clearCount();
}

int32_t QuadEncoder::count() {
  return ok_ ? static_cast<int32_t>(enc_.getCount()) : 0;
}

void DiffDriveEncoders::begin(int left_a, int left_b, int right_a, int right_b) {
  left_.begin(left_a, left_b);
  right_.begin(right_a, right_b);
}

void DiffDriveEncoders::clear() {
  left_.clear();
  right_.clear();
}

void DiffDriveEncoders::read(int32_t* left, int32_t* right) {
  if (left) *left = left_.count();
  if (right) *right = right_.count();
}

}  // namespace rosie
