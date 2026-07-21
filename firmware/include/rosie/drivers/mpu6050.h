#pragma once

#include <Arduino.h>
#include <stdint.h>

namespace rosie {

struct Mpu6050Config {
  int sda = 1;
  int scl = 2;
  uint8_t addr = 0x68;
  int yaw_axis = 2;       // 0=X, 1=Y, 2=Z
  float yaw_sign = -1.0f;
  float gyro_lsb_per_dps = 65.5f;  // ±500 deg/s
  int cal_samples = 200;
};

/** MPU6050 gyro helper (yaw rate for odometry fusion). */
class Mpu6050 {
 public:
  explicit Mpu6050(const Mpu6050Config& cfg = {});

  bool begin();
  void calibrateGyroBias();
  bool readGyroDps(float* gx, float* gy, float* gz);
  bool readYawRate(float* yaw_rad_s);
  bool ok() const { return ok_; }

 private:
  bool writeReg_(uint8_t reg, uint8_t val);
  bool readReg_(uint8_t reg, uint8_t* buf, size_t n);

  Mpu6050Config cfg_;
  bool ok_ = false;
  float gyro_bias_[3] = {0, 0, 0};
};

}  // namespace rosie
