#pragma once

#include <stddef.h>

namespace rosie {

struct VelocityGains {
  float kp = 0.0f;
  float ki = 0.0f;
  float kd = 0.0f;
  float i_clamp = 0.5f;
};

/**
 * Inner-loop strategy: feedforward channels + closed-loop correction from
 * per-wheel velocity error. Zero gains ⇒ out == ff (open-loop passthrough).
 */
class VelocityController {
 public:
  virtual ~VelocityController() = default;
  virtual void configure(const VelocityGains& gains) = 0;
  virtual VelocityGains gains() const = 0;
  /**
   * @param ff     open-loop channels from twistToChannels ([-1,1])
   * @param target per-wheel target velocity (m/s)
   * @param meas   per-wheel measured velocity (m/s)
   * @param n      channel count
   * @param dt     seconds
   * @param out    resulting channels ([-1,1])
   */
  virtual void update(const float* ff, const float* target, const float* meas,
                      size_t n, float dt, float* out) = 0;
  virtual void reset() = 0;
};

/** Per-wheel PID on velocity error, added to feedforward. */
class PidVelocityController : public VelocityController {
 public:
  explicit PidVelocityController(const VelocityGains& gains = {});

  void configure(const VelocityGains& gains) override;
  VelocityGains gains() const override { return gains_; }
  void update(const float* ff, const float* target, const float* meas, size_t n,
              float dt, float* out) override;
  void reset() override;

  static constexpr size_t kMaxChannels = 4;

 private:
  VelocityGains gains_;
  float integ_[kMaxChannels] = {0};
  float prev_err_[kMaxChannels] = {0};
  bool have_prev_[kMaxChannels] = {false};
};

}  // namespace rosie
