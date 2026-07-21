#pragma once

#include "rosie/base_kinematics.h"

namespace rosie {

struct DiffDriveGeometry {
  float wheel_diameter = 0.068f;
  float wheel_base = 0.13f;
  float ticks_per_rev = 1440.0f;
};

struct DiffDriveTeleop {
  /** Map body twist to pre-PWM scale (same units as historical TELEOP_KV/KW). */
  float kv = 180.0f;
  float kw = 40.0f;
  /** Divide by this to produce MotorDriver [-1, 1] channels. */
  float max_pwm = 100.0f;
};

/**
 * Differential-drive kinematics + encoder odometry.
 *
 * Optional IMU yaw-rate fusion: pass yaw_rate_hint (rad/s); use NAN to skip.
 */
class DiffDriveKinematics : public BaseKinematics {
 public:
  DiffDriveKinematics(const DiffDriveGeometry& geom,
                      const DiffDriveTeleop& teleop = {},
                      float imu_enc_fallback_ratio = 0.25f);

  size_t channelCount() const override { return 2; }
  void twistToChannels(float v, float w, float* out, size_t n) const override;
  void twistToWheelVel(float v, float w, float* out, size_t n) const override;
  void wheelVelocities(float* out, size_t n) const override;
  void updateOdometry(const int32_t* ticks, size_t n, float dt_s,
                      float yaw_rate_hint) override;
  Pose2DState pose() const override { return pose_; }
  void zeroPose() override;

  void setUseImuHeading(bool on) { use_imu_heading_ = on; }
  bool useImuHeading() const { return use_imu_heading_; }

 private:
  DiffDriveGeometry geom_;
  DiffDriveTeleop teleop_;
  float imu_enc_fallback_ratio_;
  Pose2DState pose_;
  int32_t prev_left_ = 0;
  int32_t prev_right_ = 0;
  bool have_prev_ = false;
  bool use_imu_heading_ = true;
  float wheel_vel_[2] = {0, 0};
};

}  // namespace rosie
