#pragma once

#include <stddef.h>
#include <stdint.h>

namespace rosie {

/**
 * Steering-agnostic N-channel actuator interface.
 *
 * Channel commands are normalized in [-1, 1]. Concrete drivers map that to
 * PWM / direction. No knowledge of Twist or wheel geometry — that belongs in
 * BaseKinematics.
 */
class MotorDriver {
 public:
  virtual ~MotorDriver() = default;
  virtual void begin() = 0;
  virtual void stop() = 0;
  virtual size_t channelCount() const = 0;
  /** Write up to channelCount() commands; extras ignored, missing treated as 0. */
  virtual void setChannels(const float* cmds, size_t n) = 0;
};

/** Duty floor/ceiling as a fraction of full timer range; ``res`` sets tick count. */
struct PwmShaping {
  float min_pwm = 0.1f;
  float max_pwm = 1.0f;
  int freq = 20000;
  int res = 8;
};

}  // namespace rosie
