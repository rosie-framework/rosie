#pragma once

#include "rosie/motor_driver.h"

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
class TB6612 : public MotorDriver {
 public:
  TB6612(const TB6612Pins& pins, const PwmShaping& pwm = {});

  void begin() override;
  void stop() override;
  size_t channelCount() const override { return 2; }
  void setChannels(const float* cmds, size_t n) override;

  float maxPwm() const { return pwm_.max_pwm; }

 private:
  void setMotor_(int pwm_pin, int in1, int in2, float pwm_cmd);
  float shapePwm_(float cmd) const;

  TB6612Pins pins_;
  PwmShaping pwm_;
};

}  // namespace rosie
