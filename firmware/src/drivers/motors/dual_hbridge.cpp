#include "rosie/drivers/motors/dual_hbridge.h"
#include <Arduino.h>
#include <math.h>

namespace rosie {

DualHBridge::DualHBridge(const DualHBridgePins& pins, const PwmShaping& pwm)
    : pins_(pins), pwm_(pwm) {}

void DualHBridge::begin() {
  pinMode(pins_.in1, OUTPUT);
  pinMode(pins_.in2, OUTPUT);
  pinMode(pins_.in3, OUTPUT);
  pinMode(pins_.in4, OUTPUT);
  ledcAttachChannel(pins_.pwm_a, pwm_.freq, pwm_.res, pins_.pwm_ch_a);
  ledcAttachChannel(pins_.pwm_b, pwm_.freq, pwm_.res, pins_.pwm_ch_b);
  stop();
}

void DualHBridge::stop() {
  float z[2] = {0, 0};
  setChannels(z, 2);
}

void DualHBridge::setChannels(const float* cmds, size_t n) {
  float left = (cmds && n > 0) ? cmds[0] : 0.0f;
  float right = (cmds && n > 1) ? cmds[1] : 0.0f;
  if (left > 1.0f) left = 1.0f;
  if (left < -1.0f) left = -1.0f;
  if (right > 1.0f) right = 1.0f;
  if (right < -1.0f) right = -1.0f;
  setMotor_(pins_.pwm_a, pins_.in1, pins_.in2, shapePwm_(left * pwm_.max_pwm));
  setMotor_(pins_.pwm_b, pins_.in3, pins_.in4, shapePwm_(right * pwm_.max_pwm));
}

void DualHBridge::setMotor_(int pwm_pin, int in1, int in2, float pwm_cmd) {
  bool forward = pwm_cmd >= 0;
  int duty = (int)fabsf(pwm_cmd);
  if (duty > 255) duty = 255;
  digitalWrite(in1, forward ? HIGH : LOW);
  digitalWrite(in2, forward ? LOW : HIGH);
  ledcWrite(pwm_pin, duty);
}

float DualHBridge::shapePwm_(float cmd) const {
  float mag = fabsf(cmd);
  if (mag < 1.0f) return 0.0f;
  if (mag < pwm_.min_pwm) mag = pwm_.min_pwm;
  if (mag > pwm_.max_pwm) mag = pwm_.max_pwm;
  return (cmd < 0) ? -mag : mag;
}

}  // namespace rosie
