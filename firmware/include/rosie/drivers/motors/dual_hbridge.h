#pragma once

#include "rosie/motor_driver.h"

namespace rosie {

/** Two-channel GPIO H-bridge: PWM + IN1/IN2 per motor (TB6612, L298N, …). */
struct DualHBridgePins {
  int pwm_a = -1;
  int in1 = -1;
  int in2 = -1;
  int pwm_b = -1;
  int in3 = -1;
  int in4 = -1;
  int pwm_ch_a = 4;
  int pwm_ch_b = 5;
};

class DualHBridge : public MotorDriver {
 public:
  DualHBridge(const DualHBridgePins& pins, const PwmShaping& pwm = {});

  void begin() override;
  void stop() override;
  size_t channelCount() const override { return 2; }
  void setChannels(const float* cmds, size_t n) override;

  float maxPwm() const { return pwm_.max_pwm; }

 private:
  void setMotor_(int pwm_pin, int in1, int in2, float channel);

  DualHBridgePins pins_;
  PwmShaping pwm_;
};

}  // namespace rosie
