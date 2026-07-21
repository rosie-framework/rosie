#pragma once

#include <stddef.h>
#include <stdint.h>
#include <math.h>

namespace rosie {

/** Planar pose used by MobileBase / DiffDrive (matches std_msgs Pose2D fields). */
struct Pose2DState {
  float x = 0;
  float y = 0;
  float theta = 0;
};

/**
 * Steering model: Twist(v, w) ↔ actuator channels + odometry.
 *
 * Implementations: DiffDriveKinematics (v1). Future: mecanum, ackermann.
 * Pass NAN for yaw_rate_hint when no IMU measurement is available.
 */
class BaseKinematics {
 public:
  virtual ~BaseKinematics() = default;
  virtual size_t channelCount() const = 0;
  virtual void twistToChannels(float v, float w, float* out, size_t n) const = 0;
  /** Body twist → per-wheel linear velocity targets (m/s). */
  virtual void twistToWheelVel(float v, float w, float* out, size_t n) const = 0;
  /** Last measured per-wheel linear velocities (m/s) from odometry. */
  virtual void wheelVelocities(float* out, size_t n) const = 0;
  virtual void updateOdometry(const int32_t* ticks, size_t n, float dt_s,
                              float yaw_rate_hint) = 0;
  virtual Pose2DState pose() const = 0;
  virtual void zeroPose() = 0;
};

#ifndef NAN
#define ROSIE_NAN nanf("")
#else
#define ROSIE_NAN NAN
#endif

}  // namespace rosie
