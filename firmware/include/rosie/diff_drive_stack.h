#pragma once

/**
 * Diff-drive MobileBase stack wired from ``robot_config.h`` macros.
 *
 * Usage (typical robot ``main.cpp``)::
 *
 *   #include "generated/robot_config.h"   // from ``rosie mcu gen-config``
 *   #include <rosie/diff_drive_stack.h>
 *
 *   rosie::DiffDriveStack stack;
 *
 *   void setup() {
 *     Serial.begin(115200);
 *     delay(300);
 *     stack.begin();
 *   }
 *   void loop() { stack.loop(); }
 *
 * Requires ``ROSIE_*`` macros from ``robot_config.h`` before this include.
 * Custom ``cmd`` ops: ``stack.base().onCmd("my_op", handler);`` before or after
 * ``begin()`` (register before ``begin()`` if the host may send them early).
 */

#ifndef ROSIE_ROBOT_CONFIG_H
#error "Include generated/robot_config.h before <rosie/diff_drive_stack.h>"
#endif

#ifndef ROSIE_VEL_KP
#define ROSIE_VEL_KP 0.0f
#define ROSIE_VEL_KI 0.0f
#define ROSIE_VEL_KD 0.0f
#define ROSIE_VEL_ICLAMP 0.5f
#endif

#ifndef ROSIE_V_MAX
#define ROSIE_V_MAX 0.35f
#define ROSIE_W_MAX 1.5f
#endif

#include "rosie/diff_drive.h"
#include "rosie/drivers/esp32_camera.h"
#include "rosie/drivers/mpu6050.h"
#include "rosie/drivers/quad_encoder.h"
#include "rosie/drivers/tb6612.h"
#include "rosie/mobile_base.h"
#include "rosie/serial_shell.h"
#include "rosie/velocity_controller.h"
#include "rosie/wifi_softap.h"
#include "rosie/wifi_station.h"

#include <string.h>

namespace rosie {

/**
 * Owns motors, kinematics, encoders, optional IMU/camera, velocity PID,
 * MobileBase, SerialShell. All pin/gain/network values come from ``ROSIE_*``.
 */
class DiffDriveStack {
 public:
  DiffDriveStack()
      : motors_({ROSIE_PIN_PWMA, ROSIE_PIN_AIN1, ROSIE_PIN_AIN2, ROSIE_PIN_PWMB,
                 ROSIE_PIN_BIN1, ROSIE_PIN_BIN2},
                {ROSIE_MIN_PWM, ROSIE_MAX_PWM, ROSIE_PWM_FREQ, ROSIE_PWM_RES}),
        kin_({ROSIE_WHEEL_DIAMETER, ROSIE_WHEEL_BASE, ROSIE_TICKS_PER_REV},
             {ROSIE_TELEOP_KV, ROSIE_TELEOP_KW, ROSIE_MAX_PWM}),
        imu_({ROSIE_IMU_SDA, ROSIE_IMU_SCL, ROSIE_IMU_ADDR, ROSIE_IMU_YAW_AXIS,
              ROSIE_IMU_YAW_SIGN}),
        vel_({ROSIE_VEL_KP, ROSIE_VEL_KI, ROSIE_VEL_KD, ROSIE_VEL_ICLAMP}),
        cfg_(makeConfig_()),
        sensors_{readTicks_, readYaw_, onZero_, this},
        base_(cfg_, motors_, kin_, sensors_),
        shell_hooks_{motorTest_, encoderMonitor_, nullptr, this},
        shell_(base_, shell_hooks_) {
    base_.setVelocityController(&vel_);
  }

  MobileBase& base() { return base_; }
  const MobileBase& base() const { return base_; }
  TB6612& motors() { return motors_; }
  DiffDriveKinematics& kinematics() { return kin_; }
  DiffDriveEncoders& encoders() { return enc_; }
  Mpu6050& imu() { return imu_; }
  PidVelocityController& velocityController() { return vel_; }
  Esp32Camera* camera() { return cam_; }
  SerialShell& shell() { return shell_; }

  /**
   * Init hardware, Wi‑Fi, Zenoh (with retries), register built-in cmd ops,
   * start camera publish task when present.
   */
  void begin(int zenoh_retries = 10) {
    motors_.begin();
    enc_.begin(ROSIE_ENC_LA, ROSIE_ENC_LB, ROSIE_ENC_RA, ROSIE_ENC_RB);

    if (ROSIE_HAS_IMU) {
      if (imu_.begin()) {
        Serial.println("IMU ready. Hold still for gyro bias calibration...");
        imu_.calibrateGyroBias();
        base_.setImuOk(true);
        base_.setUseImuHeading(true);
        Serial.println("Heading source: IMU gyro.");
      } else {
        base_.setImuOk(false);
        base_.setUseImuHeading(false);
        Serial.println("IMU not found; heading from encoders only.");
      }
      base_.onCmd("heading_source", onHeadingSource_, this);
    }

    if (ROSIE_HAS_CAMERA) {
      Esp32CameraConfig cam_cfg;
      cam_cfg.pins = esp32s3EyePins();
      cam_cfg.jpeg_quality = ROSIE_CAMERA_JPEG_QUALITY;
      cam_cfg.pub_hz = ROSIE_CAMERA_PUB_HZ;
      cam_cfg.enable_default = ROSIE_CAMERA_ENABLE_DEFAULT;
      cam_cfg.vflip = true;
      cam_ = new Esp32Camera(cam_cfg);
      if (cam_->begin()) {
        Serial.println("Camera ready.");
        base_.onCmd("camera_enable", onCameraEnable_, this);
      } else {
        Serial.println("Continuing without camera.");
        delete cam_;
        cam_ = nullptr;
      }
    }

    if (strcmp(ROSIE_NETWORK_MODE, "station") == 0) {
      wifiStation(ROSIE_WIFI_SSID, ROSIE_WIFI_PASSWORD);
    } else {
      softAP(ROSIE_WIFI_SSID, ROSIE_WIFI_PASSWORD, 1);
    }

    for (int attempt = 1; attempt <= zenoh_retries; attempt++) {
      Serial.printf("Rosie connect attempt %d/%d ...\n", attempt, zenoh_retries);
      delay(1500);
      if (base_.begin(ROSIE_ZENOH_CONNECT, ROSIE_ZENOH_MODE)) break;
      if (attempt == zenoh_retries) {
        Serial.println("Rosie not connected — USB serial still works.");
        Serial.println("Start zenohd on the laptop and reset the board to retry.");
      }
    }

    if (cam_ && base_.ready()) {
      cam_->startPublishTask(publishJpeg_, this);
    }

    Serial.println("Ready (USB): <x> <y> | test | enc | zero | imu | stop");
    Serial.printf("Rosie: robot='%s' (DiffDriveStack / MobileBase)\n", ROSIE_ROBOT_ID);
  }

  /** Call from ``loop()``: USB shell + MobileBase spin. */
  void loop() {
    shell_.poll();
    base_.spin();
  }

 private:
  static MobileBaseConfig makeConfig_() {
    MobileBaseConfig c;
    c.robot = ROSIE_ROBOT_ID;
    c.fleet = ROSIE_FLEET_ID;
    c.dt_ms = ROSIE_DT_MS;
    c.teleop_timeout_ms = ROSIE_TELEOP_TIMEOUT_MS;
    c.max_pwm = ROSIE_MAX_PWM;
    c.goto_gains.kp_linear = ROSIE_KP_LINEAR;
    c.goto_gains.kp_angular = ROSIE_KP_ANGULAR;
    c.goto_gains.v_max = ROSIE_V_MAX;
    c.goto_gains.w_max = ROSIE_W_MAX;
    c.goto_gains.pos_tolerance = ROSIE_POS_TOLERANCE;
    c.goto_gains.approach_dist = ROSIE_APPROACH_DIST;
    c.goto_gains.align_tol = ROSIE_ALIGN_TOL;
    c.pose_hz = ROSIE_POSE_HZ;
    c.presence_hz = ROSIE_PRESENCE_HZ;
    return c;
  }

  static void readTicks_(int32_t* left, int32_t* right, void* user) {
    static_cast<DiffDriveStack*>(user)->enc_.read(left, right);
  }

  static bool readYaw_(float* yaw, void* user) {
    auto* self = static_cast<DiffDriveStack*>(user);
    return self->imu_.ok() && self->imu_.readYawRate(yaw);
  }

  static void onZero_(void* user) {
    auto* self = static_cast<DiffDriveStack*>(user);
    self->enc_.clear();
    if (self->imu_.ok()) self->imu_.calibrateGyroBias();
  }

  static bool publishJpeg_(const uint8_t* data, size_t len, void* user) {
    return static_cast<DiffDriveStack*>(user)->base_.publishJpeg(data, len);
  }

  static void onHeadingSource_(const char* /*op*/, JsonVariantConst value, void* user) {
    auto* self = static_cast<DiffDriveStack*>(user);
    if (!self->imu_.ok()) {
      self->base_.log("warn", "IMU not available.");
      return;
    }
    bool next;
    if (value.isNull()) {
      next = !self->base_.useImuHeading();
    } else {
      next = value.as<bool>() || value.as<int>() != 0;
    }
    self->base_.setUseImuHeading(next);
    self->base_.log("info", next ? "Heading source: IMU gyro" : "Heading source: encoders");
  }

  static void onCameraEnable_(const char* /*op*/, JsonVariantConst value, void* user) {
    auto* self = static_cast<DiffDriveStack*>(user);
    if (!self->cam_) return;
    bool en = value.isNull() ? true : (value.as<bool>() || value.as<int>() != 0);
    self->cam_->setEnable(en);
  }

  static void motorTest_(MobileBase& base, void* /*user*/) {
    base.requestStop();
    float fwd[2] = {1.0f, 0.0f};
    float rev[2] = {-1.0f, 0.0f};
    float rfwd[2] = {0.0f, 1.0f};
    float rrev[2] = {0.0f, -1.0f};
    Serial.println("MSG,Motor test: LEFT forward");
    base.motors().setChannels(fwd, 2);
    delay(1000);
    base.motors().stop();
    delay(400);
    Serial.println("MSG,Motor test: LEFT reverse");
    base.motors().setChannels(rev, 2);
    delay(1000);
    base.motors().stop();
    delay(400);
    Serial.println("MSG,Motor test: RIGHT forward");
    base.motors().setChannels(rfwd, 2);
    delay(1000);
    base.motors().stop();
    delay(400);
    Serial.println("MSG,Motor test: RIGHT reverse");
    base.motors().setChannels(rrev, 2);
    delay(1000);
    base.motors().stop();
    Serial.println("MSG,Motor test complete.");
  }

  static void encoderMonitor_(MobileBase& /*base*/, void* user) {
    auto* self = static_cast<DiffDriveStack*>(user);
    Serial.println("MSG,Encoder monitor: spin each wheel BY HAND for 8 s...");
    unsigned long start = millis();
    while (millis() - start < 8000) {
      int32_t l = 0, r = 0;
      self->enc_.read(&l, &r);
      Serial.printf("ENC,left=%ld,right=%ld\n", (long)l, (long)r);
      delay(250);
    }
    Serial.println("MSG,Encoder monitor done.");
  }

  TB6612 motors_;
  DiffDriveKinematics kin_;
  DiffDriveEncoders enc_;
  Mpu6050 imu_;
  PidVelocityController vel_;
  Esp32Camera* cam_ = nullptr;
  MobileBaseConfig cfg_;
  MobileBaseSensors sensors_;
  MobileBase base_;
  SerialShellHooks shell_hooks_;
  SerialShell shell_;
};

}  // namespace rosie
