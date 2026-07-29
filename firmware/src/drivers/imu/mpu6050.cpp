#include "rosie/drivers/imu/mpu6050.h"
#include <Wire.h>
#include <math.h>

namespace rosie {

Mpu6050::Mpu6050(const Mpu6050Config& cfg) : cfg_(cfg) {}

bool Mpu6050::writeReg_(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(cfg_.addr);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

bool Mpu6050::readReg_(uint8_t reg, uint8_t* buf, size_t n) {
  Wire.beginTransmission(cfg_.addr);
  Wire.write(reg);
  if (Wire.endTransmission(true) != 0) return false;
  if (Wire.requestFrom((int)cfg_.addr, (int)n) != (int)n) return false;
  for (size_t i = 0; i < n; i++) buf[i] = Wire.read();
  return true;
}

bool Mpu6050::begin() {
  Wire.begin(cfg_.sda, cfg_.scl);
  Wire.setClock(100000);
  delay(50);
  uint8_t who = 0;
  if (!readReg_(0x75, &who, 1)) return false;
  if (who != 0x68 && who != 0x98 && who != 0x70) {
    Serial.printf("MPU WHO_AM_I=0x%02X (unexpected)\n", who);
  } else {
    Serial.printf("MPU WHO_AM_I=0x%02X OK (Wire @ SDA=%d SCL=%d)\n", who, cfg_.sda,
                  cfg_.scl);
  }
  if (!writeReg_(0x6B, 0x00)) return false;
  delay(10);
  if (!writeReg_(0x1B, 0x08)) return false;  // gyro ±500 deg/s
  if (!writeReg_(0x1C, 0x00)) return false;  // accel ±2 g
  if (!writeReg_(0x1A, 0x03)) return false;
  accel_lsb_per_g_ = 16384.0f;
  ok_ = true;
  return true;
}

void Mpu6050::calibrateGyroBias() {
  long sum[3] = {0, 0, 0};
  int ok = 0;
  for (int i = 0; i < cfg_.cal_samples; i++) {
    uint8_t b[6];
    if (!readReg_(0x43, b, 6)) {
      delay(2);
      continue;
    }
    for (int a = 0; a < 3; a++) {
      int16_t raw = (int16_t)((b[a * 2] << 8) | b[a * 2 + 1]);
      sum[a] += raw;
    }
    ok++;
    delay(2);
  }
  if (ok > 0) {
    for (int a = 0; a < 3; a++) gyro_bias_[a] = (float)sum[a] / (float)ok;
    Serial.printf("Gyro bias LSB: X=%.1f Y=%.1f Z=%.1f (%d samples)\n",
                  gyro_bias_[0], gyro_bias_[1], gyro_bias_[2], ok);
  }
}

bool Mpu6050::readGyroDps(float* gx, float* gy, float* gz) {
  uint8_t b[6];
  if (!readReg_(0x43, b, 6)) return false;
  int16_t rx = (int16_t)((b[0] << 8) | b[1]);
  int16_t ry = (int16_t)((b[2] << 8) | b[3]);
  int16_t rz = (int16_t)((b[4] << 8) | b[5]);
  *gx = (rx - gyro_bias_[0]) / cfg_.gyro_lsb_per_dps;
  *gy = (ry - gyro_bias_[1]) / cfg_.gyro_lsb_per_dps;
  *gz = (rz - gyro_bias_[2]) / cfg_.gyro_lsb_per_dps;
  return true;
}

bool Mpu6050::readImu(float* ax, float* ay, float* az, float* gx, float* gy,
                      float* gz) {
  uint8_t b[14];
  if (!readReg_(0x3B, b, 14)) return false;
  int16_t rax = (int16_t)((b[0] << 8) | b[1]);
  int16_t ray = (int16_t)((b[2] << 8) | b[3]);
  int16_t raz = (int16_t)((b[4] << 8) | b[5]);
  int16_t rgx = (int16_t)((b[8] << 8) | b[9]);
  int16_t rgy = (int16_t)((b[10] << 8) | b[11]);
  int16_t rgz = (int16_t)((b[12] << 8) | b[13]);
  constexpr float kG = 9.80665f;
  *ax = (rax / accel_lsb_per_g_) * kG;
  *ay = (ray / accel_lsb_per_g_) * kG;
  *az = (raz / accel_lsb_per_g_) * kG;
  float dps_to_rad = static_cast<float>(M_PI) / 180.0f;
  *gx = ((rgx - gyro_bias_[0]) / cfg_.gyro_lsb_per_dps) * dps_to_rad;
  *gy = ((rgy - gyro_bias_[1]) / cfg_.gyro_lsb_per_dps) * dps_to_rad;
  *gz = ((rgz - gyro_bias_[2]) / cfg_.gyro_lsb_per_dps) * dps_to_rad;
  return true;
}

bool Mpu6050::readYawRate(float* yaw_rad_s) {
  float gx, gy, gz;
  if (!readGyroDps(&gx, &gy, &gz)) return false;
  float dps = (cfg_.yaw_axis == 0) ? gx : (cfg_.yaw_axis == 1) ? gy : gz;
  *yaw_rad_s = cfg_.yaw_sign * dps * (static_cast<float>(M_PI) / 180.0f);
  return true;
}

}  // namespace rosie
