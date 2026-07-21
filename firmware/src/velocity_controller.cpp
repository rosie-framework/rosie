#include "rosie/velocity_controller.h"

namespace rosie {

PidVelocityController::PidVelocityController(const VelocityGains& gains)
    : gains_(gains) {}

void PidVelocityController::configure(const VelocityGains& gains) {
  gains_ = gains;
  reset();
}

void PidVelocityController::reset() {
  for (size_t i = 0; i < kMaxChannels; i++) {
    integ_[i] = 0;
    prev_err_[i] = 0;
    have_prev_[i] = false;
  }
}

void PidVelocityController::update(const float* ff, const float* target,
                                   const float* meas, size_t n, float dt,
                                   float* out) {
  if (!ff || !out) return;
  if (n > kMaxChannels) n = kMaxChannels;
  if (dt <= 0.0f || dt > 0.2f) dt = 0.02f;

  const bool closed =
      (gains_.kp != 0.0f || gains_.ki != 0.0f || gains_.kd != 0.0f);

  for (size_t i = 0; i < n; i++) {
    float u = ff[i];
    if (closed && target && meas) {
      float err = target[i] - meas[i];
      integ_[i] += err * dt;
      float ic = gains_.i_clamp;
      if (ic < 0.0f) ic = 0.0f;
      if (integ_[i] > ic) integ_[i] = ic;
      if (integ_[i] < -ic) integ_[i] = -ic;

      float deriv = 0.0f;
      if (have_prev_[i]) {
        deriv = (err - prev_err_[i]) / dt;
      }
      prev_err_[i] = err;
      have_prev_[i] = true;

      u += gains_.kp * err + gains_.ki * integ_[i] + gains_.kd * deriv;
    }
    if (u > 1.0f) u = 1.0f;
    if (u < -1.0f) u = -1.0f;
    out[i] = u;
  }
}

}  // namespace rosie
