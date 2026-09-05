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
  setMotor_(pins_.pwm_a, pins_.in1, pins_.in2, left);
  setMotor_(pins_.pwm_b, pins_.in3, pins_.in4, right);
}

void DualHBridge::setMotor_(int pwm_pin, int in1, int in2, float channel) {
  if (channel > 1.0f) channel = 1.0f;
  if (channel < -1.0f) channel = -1.0f;
  float mag = fabsf(channel);
  if (mag < 1e-4f) {
    digitalWrite(in1, LOW);
    digitalWrite(in2, LOW);
    ledcWrite(pwm_pin, 0);
    return;
  }
  float pmin = pwm_.min_pwm;
  float pmax = pwm_.max_pwm;
  if (pmin < 0.0f) pmin = 0.0f;
  if (pmax > 1.0f) pmax = 1.0f;
  if (pmin > pmax) pmin = pmax;
  float duty = pmin + mag * (pmax - pmin);
  if (duty < 0.0f) duty = 0.0f;
  if (duty > 1.0f) duty = 1.0f;
  int max_ticks = (1 << pwm_.res) - 1;
  if (max_ticks < 1) max_ticks = 255;
  int ticks = (int)(duty * static_cast<float>(max_ticks) + 0.5f);
  if (ticks > max_ticks) ticks = max_ticks;
  bool forward = channel >= 0.0f;
  digitalWrite(in1, forward ? HIGH : LOW);
  digitalWrite(in2, forward ? LOW : HIGH);
  ledcWrite(pwm_pin, ticks);
}

}  // namespace rosie
