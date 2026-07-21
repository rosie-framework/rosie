#include "rosie/diff_drive.h"
#include <math.h>

namespace rosie {

DiffDriveKinematics::DiffDriveKinematics(const DiffDriveGeometry& geom,
                                         const DiffDriveTeleop& teleop,
                                         float imu_enc_fallback_ratio)
    : geom_(geom),
      teleop_(teleop),
      imu_enc_fallback_ratio_(imu_enc_fallback_ratio) {}

void DiffDriveKinematics::twistToChannels(float v, float w, float* out,
                                          size_t n) const {
  if (!out || n < 2) return;
  float scale = teleop_.max_pwm > 1e-3f ? teleop_.max_pwm : 1.0f;
  float left = (teleop_.kv * v - teleop_.kw * w) / scale;
  float right = (teleop_.kv * v + teleop_.kw * w) / scale;
  if (left > 1.0f) left = 1.0f;
  if (left < -1.0f) left = -1.0f;
  if (right > 1.0f) right = 1.0f;
  if (right < -1.0f) right = -1.0f;
  out[0] = left;
  out[1] = right;
}

void DiffDriveKinematics::twistToWheelVel(float v, float w, float* out,
                                          size_t n) const {
  if (!out || n < 2) return;
  float half_l = geom_.wheel_base * 0.5f;
  out[0] = v - w * half_l;
  out[1] = v + w * half_l;
}

void DiffDriveKinematics::wheelVelocities(float* out, size_t n) const {
  if (!out || n < 2) return;
  out[0] = wheel_vel_[0];
  out[1] = wheel_vel_[1];
}

void DiffDriveKinematics::updateOdometry(const int32_t* ticks, size_t n,
                                         float dt_s, float yaw_rate_hint) {
  if (!ticks || n < 2) return;
  int32_t l = ticks[0];
  int32_t r = ticks[1];
  if (!have_prev_) {
    prev_left_ = l;
    prev_right_ = r;
    have_prev_ = true;
    wheel_vel_[0] = 0;
    wheel_vel_[1] = 0;
    return;
  }
  int32_t dL = l - prev_left_;
  int32_t dR = r - prev_right_;
  prev_left_ = l;
  prev_right_ = r;

  const float dist_per_tick =
      (static_cast<float>(M_PI) * geom_.wheel_diameter) / geom_.ticks_per_rev;
  float d_left = dL * dist_per_tick;
  float d_right = dR * dist_per_tick;
  float d_center = (d_left + d_right) * 0.5f;
  float d_theta_enc = (d_right - d_left) / geom_.wheel_base;

  if (dt_s <= 0.0f || dt_s > 0.2f) dt_s = 0.02f;

  wheel_vel_[0] = d_left / dt_s;
  wheel_vel_[1] = d_right / dt_s;

  float d_theta = d_theta_enc;
  if (use_imu_heading_ && !isnan(yaw_rate_hint)) {
    float d_theta_imu = yaw_rate_hint * dt_s;
    if (fabsf(d_theta_enc) > 0.005f &&
        fabsf(d_theta_imu) < imu_enc_fallback_ratio_ * fabsf(d_theta_enc)) {
      d_theta = d_theta_enc;
    } else {
      d_theta = d_theta_imu;
    }
  }

  pose_.x += d_center * cosf(pose_.theta + d_theta * 0.5f);
  pose_.y += d_center * sinf(pose_.theta + d_theta * 0.5f);
  pose_.theta += d_theta;
  while (pose_.theta > static_cast<float>(M_PI)) pose_.theta -= 2.0f * static_cast<float>(M_PI);
  while (pose_.theta < -static_cast<float>(M_PI)) pose_.theta += 2.0f * static_cast<float>(M_PI);
}

void DiffDriveKinematics::zeroPose() {
  pose_ = {};
  have_prev_ = false;
  prev_left_ = 0;
  prev_right_ = 0;
  wheel_vel_[0] = 0;
  wheel_vel_[1] = 0;
}

}  // namespace rosie
