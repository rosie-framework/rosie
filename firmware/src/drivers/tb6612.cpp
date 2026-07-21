#include "rosie/drivers/tb6612.h"
#include <Arduino.h>
#include <math.h>

namespace rosie {

TB6612::TB6612(const TB6612Pins& pins, const PwmShaping& pwm)
    : pins_(pins), pwm_(pwm) {}

void TB6612::begin() {
  pinMode(pins_.ain1, OUTPUT);
  pinMode(pins_.ain2, OUTPUT);
  pinMode(pins_.bin1, OUTPUT);
  pinMode(pins_.bin2, OUTPUT);
  ledcAttachChannel(pins_.pwmA, pwm_.freq, pwm_.res, pins_.pwm_ch_a);
  ledcAttachChannel(pins_.pwmB, pwm_.freq, pwm_.res, pins_.pwm_ch_b);
  stop();
}

void TB6612::stop() {
  float z[2] = {0, 0};
  setChannels(z, 2);
}

void TB6612::setChannels(const float* cmds, size_t n) {
  float left = (cmds && n > 0) ? cmds[0] : 0.0f;
  float right = (cmds && n > 1) ? cmds[1] : 0.0f;
  if (left > 1.0f) left = 1.0f;
  if (left < -1.0f) left = -1.0f;
  if (right > 1.0f) right = 1.0f;
  if (right < -1.0f) right = -1.0f;
  setMotor_(pins_.pwmA, pins_.ain1, pins_.ain2, shapePwm_(left * pwm_.max_pwm));
  setMotor_(pins_.pwmB, pins_.bin1, pins_.bin2, shapePwm_(right * pwm_.max_pwm));
}

void TB6612::setMotor_(int pwm_pin, int in1, int in2, float pwm_cmd) {
  bool forward = pwm_cmd >= 0;
  int duty = (int)fabsf(pwm_cmd);
  if (duty > 255) duty = 255;
  digitalWrite(in1, forward ? HIGH : LOW);
  digitalWrite(in2, forward ? LOW : HIGH);
  ledcWrite(pwm_pin, duty);
}

float TB6612::shapePwm_(float cmd) const {
  float mag = fabsf(cmd);
  if (mag < 1.0f) return 0.0f;
  if (mag < pwm_.min_pwm) mag = pwm_.min_pwm;
  if (mag > pwm_.max_pwm) mag = pwm_.max_pwm;
  return (cmd < 0) ? -mag : mag;
}

}  // namespace rosie
