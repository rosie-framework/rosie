#pragma once

#include "rosie/drivers/motors/dual_hbridge.h"

namespace rosie {

struct TB6612Pins {
  int pwmA = -1;
  int ain1 = -1;
  int ain2 = -1;
  int pwmB = -1;
  int bin1 = -1;
  int bin2 = -1;
  int pwm_ch_a = 4;
  int pwm_ch_b = 5;
};

/** Two-channel TB6612FNG H-bridge (left / right). */
class TB6612 : public DualHBridge {
 public:
  TB6612(const TB6612Pins& pins, const PwmShaping& pwm = {})
      : DualHBridge(
            DualHBridgePins{pins.pwmA, pins.ain1, pins.ain2, pins.pwmB, pins.bin1,
                            pins.bin2, pins.pwm_ch_a, pins.pwm_ch_b},
            pwm) {}
};

}  // namespace rosie
