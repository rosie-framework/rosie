#pragma once

#include "rosie/drivers/motors/dual_hbridge.h"

namespace rosie {

struct L298NPins {
  int ena = -1;
  int in1 = -1;
  int in2 = -1;
  int enb = -1;
  int in3 = -1;
  int in4 = -1;
  int pwm_ch_a = 4;
  int pwm_ch_b = 5;
};

/** Two-channel L298N H-bridge (ENA/IN1/IN2 + ENB/IN3/IN4). */
class L298N : public DualHBridge {
 public:
  L298N(const L298NPins& pins, const PwmShaping& pwm = {})
      : DualHBridge(DualHBridgePins{pins.ena, pins.in1, pins.in2, pins.enb, pins.in3,
                                    pins.in4, pins.pwm_ch_a, pins.pwm_ch_b},
                    pwm) {}
};

}  // namespace rosie
