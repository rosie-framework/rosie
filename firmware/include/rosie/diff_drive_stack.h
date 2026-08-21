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
 * Motors / encoders / IMU / camera are selected from ``robot.yaml``.
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

/* Legacy robot_config.h without driver macros → TB6612 + encoders. */
#if !defined(ROSIE_MOTORS_TB6612) && !defined(ROSIE_MOTORS_L298N)
#define ROSIE_MOTORS_TB6612 1
#endif

#ifndef ROSIE_HAS_ENCODERS
#define ROSIE_HAS_ENCODERS 1
#endif

#if ROSIE_HAS_ENCODERS && !defined(ROSIE_ENCODERS_QUAD_ENCODER)
#define ROSIE_ENCODERS_QUAD_ENCODER 1
#endif

#ifndef ROSIE_HAS_IMU
#define ROSIE_HAS_IMU 0
#endif

#if ROSIE_HAS_IMU && !defined(ROSIE_IMU_MPU6050)
#define ROSIE_IMU_MPU6050 1
#endif

#ifndef ROSIE_HAS_CAMERA
#define ROSIE_HAS_CAMERA 0
#endif

#ifndef ROSIE_HAS_RANGE
#define ROSIE_HAS_RANGE 0
#endif

#ifndef ROSIE_ENCODERS_PUB_HZ
#define ROSIE_ENCODERS_PUB_HZ 0.0f
#endif

#ifndef ROSIE_IMU_PUB_HZ
#define ROSIE_IMU_PUB_HZ 0.0f
#endif

#if ROSIE_HAS_CAMERA && !defined(ROSIE_CAMERA_ESP32S3_EYE) && !defined(ROSIE_CAMERA_CUSTOM)
#define ROSIE_CAMERA_ESP32S3_EYE 1
#endif

#ifndef ROSIE_MOTORS_DRIVER_ID
#if defined(ROSIE_MOTORS_L298N)
#define ROSIE_MOTORS_DRIVER_ID "l298n"
#else
#define ROSIE_MOTORS_DRIVER_ID "tb6612"
#endif
#endif

#include "rosie/diff_drive.h"
#include "rosie/mcu_connect.h"
#include "rosie/mobile_base.h"
#include "rosie/motor_driver.h"
#include "rosie/serial_shell.h"
#include "rosie/velocity_controller.h"

#if defined(ROSIE_MOTORS_TB6612)
#include "rosie/drivers/motors/tb6612.h"
#elif defined(ROSIE_MOTORS_L298N)
#include "rosie/drivers/motors/l298n.h"
#else
#error "DiffDriveStack: set motors.driver in robot.yaml (supported: tb6612, l298n)"
#endif

#if ROSIE_HAS_ENCODERS
#include "rosie/drivers/encoders/quad_encoder.h"
#endif

#if ROSIE_HAS_IMU
#include "rosie/drivers/imu/mpu6050.h"
#endif

#if ROSIE_HAS_CAMERA
#include "rosie/drivers/camera/esp32_camera.h"
#endif

#if ROSIE_HAS_RANGE
#include "rosie/drivers/range/vl53l0x.h"
#include "rosie/drivers/range/vl53l1x.h"
#ifndef ROSIE_MAX_RANGE_SENSORS
#define ROSIE_MAX_RANGE_SENSORS 4
#endif
#ifndef ROSIE_RANGE_COUNT
#define ROSIE_RANGE_COUNT 0
#endif
#ifndef ROSIE_RANGE_CHIP_VL53L1X
#define ROSIE_RANGE_CHIP_VL53L1X 0
#endif
#ifndef ROSIE_RANGE_CHIP_VL53L0X
#define ROSIE_RANGE_CHIP_VL53L0X 1
#endif
#endif

namespace rosie {

/**
 * Owns motors, kinematics, optional encoders/IMU/camera, velocity PID,
 * MobileBase, SerialShell. Hardware ids come from ``robot.yaml`` via ``ROSIE_*``.
 */
class DiffDriveStack {
 public:
  DiffDriveStack()
#if defined(ROSIE_MOTORS_TB6612)
      : motors_({ROSIE_PIN_PWMA, ROSIE_PIN_AIN1, ROSIE_PIN_AIN2, ROSIE_PIN_PWMB,
                 ROSIE_PIN_BIN1, ROSIE_PIN_BIN2},
                {ROSIE_MIN_PWM, ROSIE_MAX_PWM, ROSIE_PWM_FREQ, ROSIE_PWM_RES}),
#elif defined(ROSIE_MOTORS_L298N)
      : motors_({ROSIE_PIN_ENA, ROSIE_PIN_IN1, ROSIE_PIN_IN2, ROSIE_PIN_ENB,
                 ROSIE_PIN_IN3, ROSIE_PIN_IN4},
                {ROSIE_MIN_PWM, ROSIE_MAX_PWM, ROSIE_PWM_FREQ, ROSIE_PWM_RES}),
#endif
        kin_({ROSIE_WHEEL_DIAMETER, ROSIE_WHEEL_BASE, ROSIE_TICKS_PER_REV},
             {ROSIE_TELEOP_KV, ROSIE_TELEOP_KW, ROSIE_MAX_PWM}),
#if ROSIE_HAS_IMU
        imu_({ROSIE_IMU_SDA, ROSIE_IMU_SCL, ROSIE_IMU_ADDR, ROSIE_IMU_YAW_AXIS,
              ROSIE_IMU_YAW_SIGN}),
#endif
        vel_({ROSIE_VEL_KP, ROSIE_VEL_KI, ROSIE_VEL_KD, ROSIE_VEL_ICLAMP}),
        cfg_(makeConfig_()),
        sensors_{
#if ROSIE_HAS_ENCODERS
            readTicks_,
#else
            nullptr,
#endif
#if ROSIE_HAS_IMU
            readYaw_,
            readImu_,
#else
            nullptr,
            nullptr,
#endif
            onZero_, this},
        base_(cfg_, motors_, kin_, sensors_),
        shell_hooks_{motorTest_,
#if ROSIE_HAS_ENCODERS
                     encoderMonitor_,
#else
                     nullptr,
#endif
                     nullptr, this},
        shell_(base_, shell_hooks_) {
    base_.setVelocityController(&vel_);
  }

  MobileBase& base() { return base_; }
  const MobileBase& base() const { return base_; }
  MotorDriver& motors() { return motors_; }
  DiffDriveKinematics& kinematics() { return kin_; }
#if ROSIE_HAS_ENCODERS
  DiffDriveEncoders& encoders() { return enc_; }
#endif
#if ROSIE_HAS_IMU
  Mpu6050& imu() { return imu_; }
#endif
  PidVelocityController& velocityController() { return vel_; }
#if ROSIE_HAS_CAMERA
  Esp32Camera* camera() { return cam_; }
#endif
  SerialShell& shell() { return shell_; }

  /**
   * Init hardware, then ``mcuConnect`` (Wi‑Fi + Zenoh retries), register built-in
   * cmd ops, start camera publish task when present.
   */
  void begin(int zenoh_retries = 10) {
    motors_.begin();
#if ROSIE_HAS_ENCODERS
    enc_.begin(ROSIE_ENC_LA, ROSIE_ENC_LB, ROSIE_ENC_RA, ROSIE_ENC_RB);
#endif

#if ROSIE_HAS_IMU
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
#endif

#if ROSIE_HAS_CAMERA
    {
      Esp32CameraConfig cam_cfg;
#if defined(ROSIE_CAMERA_CUSTOM)
      cam_cfg.pins.pwdn = ROSIE_CAM_PWDN;
      cam_cfg.pins.reset = ROSIE_CAM_RESET;
      cam_cfg.pins.xclk = ROSIE_CAM_XCLK;
      cam_cfg.pins.siod = ROSIE_CAM_SIOD;
      cam_cfg.pins.sioc = ROSIE_CAM_SIOC;
      cam_cfg.pins.y9 = ROSIE_CAM_Y9;
      cam_cfg.pins.y8 = ROSIE_CAM_Y8;
      cam_cfg.pins.y7 = ROSIE_CAM_Y7;
      cam_cfg.pins.y6 = ROSIE_CAM_Y6;
      cam_cfg.pins.y5 = ROSIE_CAM_Y5;
      cam_cfg.pins.y4 = ROSIE_CAM_Y4;
      cam_cfg.pins.y3 = ROSIE_CAM_Y3;
      cam_cfg.pins.y2 = ROSIE_CAM_Y2;
      cam_cfg.pins.vsync = ROSIE_CAM_VSYNC;
      cam_cfg.pins.href = ROSIE_CAM_HREF;
      cam_cfg.pins.pclk = ROSIE_CAM_PCLK;
#else
      cam_cfg.pins = esp32s3EyePins();
#endif
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
#endif

#if ROSIE_HAS_RANGE
    {
      // Multi-drop: hold every XSHUT low, then bring up one-by-one.
      for (int i = 0; i < ROSIE_RANGE_COUNT; i++) {
        if (ROSIE_RANGE_XSHUTS[i] >= 0) {
          pinMode(ROSIE_RANGE_XSHUTS[i], OUTPUT);
          digitalWrite(ROSIE_RANGE_XSHUTS[i], LOW);
        }
      }
      delay(10);
#if ROSIE_HAS_IMU
      bool wire_begun = true;  // IMU already called Wire.begin
#else
      bool wire_begun = false;
#endif
      for (int i = 0; i < ROSIE_RANGE_COUNT; i++) {
        if (!ROSIE_RANGE_IDS[i]) continue;
        range_users_[i] = {this, i};
        bool ok = false;
        const uint8_t chip = ROSIE_RANGE_CHIPS[i];
        if (chip == ROSIE_RANGE_CHIP_VL53L0X) {
          Vl53l0xConfig rc;
          rc.addr = ROSIE_RANGE_ADDRS[i];
          rc.xshut = ROSIE_RANGE_XSHUTS[i];
          rc.sda = ROSIE_RANGE_SDA;
          rc.scl = ROSIE_RANGE_SCL;
          rc.begin_wire = !wire_begun;
          ranges_l0_[i].configure(rc);
          ok = ranges_l0_[i].begin();
        } else {
          Vl53l1xConfig rc;
          rc.addr = ROSIE_RANGE_ADDRS[i];
          rc.xshut = ROSIE_RANGE_XSHUTS[i];
          rc.sda = ROSIE_RANGE_SDA;
          rc.scl = ROSIE_RANGE_SCL;
          rc.begin_wire = !wire_begun;
          ranges_l1_[i].configure(rc);
          ok = ranges_l1_[i].begin();
        }
        if (ok) {
          wire_begun = true;
          MobileBaseRangeSensor slot;
          slot.id = ROSIE_RANGE_IDS[i];
          slot.readRangeM = readRange_;
          slot.user = &range_users_[i];
          slot.pub_hz = ROSIE_RANGE_PUB_HZ[i];
          slot.min_range = ROSIE_RANGE_MIN_M[i];
          slot.max_range = ROSIE_RANGE_MAX_M[i];
          if (base_.addRangeSensor(slot)) {
            Serial.printf("Range '%s' ready (addr=0x%02X).\n",
                          ROSIE_RANGE_IDS[i], (unsigned)ROSIE_RANGE_ADDRS[i]);
          }
        } else {
          Serial.printf("Range '%s' init failed — continuing without it.\n",
                        ROSIE_RANGE_IDS[i]);
        }
      }
    }
#endif

    McuConnectConfig net;
    net.network_mode = ROSIE_NETWORK_MODE;
    net.wifi_ssid = ROSIE_WIFI_SSID;
    net.wifi_password = ROSIE_WIFI_PASSWORD;
    net.softap_channel = 1;
    net.zenoh_connect = ROSIE_ZENOH_CONNECT;
    net.zenoh_mode = ROSIE_ZENOH_MODE;
    net.zenoh_user = ROSIE_ZENOH_USER;
    net.zenoh_password = ROSIE_ZENOH_PASSWORD;
    net.zenoh_retries = zenoh_retries;
    mcuConnect(base_, net);

#if ROSIE_HAS_CAMERA
    if (cam_ && base_.ready()) {
      cam_->startPublishTask(publishJpeg_, this);
    }
#endif

    Serial.println("Ready (USB): <x> <y> | test | enc | zero | imu | stop");
    Serial.printf("Rosie: robot='%s' motors=%s (DiffDriveStack / MobileBase)\n",
                  ROSIE_ROBOT_ID, ROSIE_MOTORS_DRIVER_ID);
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
    c.control_hz = ROSIE_CONTROL_HZ;
    c.encoders_hz = ROSIE_ENCODERS_PUB_HZ;
    c.imu_hz = ROSIE_IMU_PUB_HZ;
    return c;
  }

#if ROSIE_HAS_ENCODERS
  static void readTicks_(int32_t* left, int32_t* right, void* user) {
    static_cast<DiffDriveStack*>(user)->enc_.read(left, right);
  }
#endif

#if ROSIE_HAS_IMU
  static bool readYaw_(float* yaw, void* user) {
    auto* self = static_cast<DiffDriveStack*>(user);
    return self->imu_.ok() && self->imu_.readYawRate(yaw);
  }
  static bool readImu_(float* ax, float* ay, float* az, float* gx, float* gy,
                       float* gz, void* user) {
    auto* self = static_cast<DiffDriveStack*>(user);
    return self->imu_.ok() && self->imu_.readImu(ax, ay, az, gx, gy, gz);
  }
#endif

  static void onZero_(void* user) {
    auto* self = static_cast<DiffDriveStack*>(user);
#if ROSIE_HAS_ENCODERS
    self->enc_.clear();
#endif
#if ROSIE_HAS_IMU
    if (self->imu_.ok()) self->imu_.calibrateGyroBias();
#endif
  }

#if ROSIE_HAS_CAMERA
  static bool publishJpeg_(const uint8_t* data, size_t len, void* user) {
    return static_cast<DiffDriveStack*>(user)->base_.publishJpeg(data, len);
  }

  static void onCameraEnable_(const char* /*op*/, JsonVariantConst value, void* user) {
    auto* self = static_cast<DiffDriveStack*>(user);
    if (!self->cam_) return;
    bool en = value.isNull() ? true : (value.as<bool>() || value.as<int>() != 0);
    self->cam_->setEnable(en);
  }
#endif

#if ROSIE_HAS_IMU
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
#endif

#if ROSIE_HAS_RANGE
  struct RangeUser {
    DiffDriveStack* self = nullptr;
    int idx = 0;
  };

  static bool readRange_(float* range_m, void* user) {
    auto* u = static_cast<RangeUser*>(user);
    if (!u || !u->self) return false;
    const int i = u->idx;
    if (i < 0 || i >= ROSIE_MAX_RANGE_SENSORS) return false;
    if (ROSIE_RANGE_CHIPS[i] == ROSIE_RANGE_CHIP_VL53L0X) {
      return u->self->ranges_l0_[i].ok() &&
             u->self->ranges_l0_[i].readRangeM(range_m);
    }
    return u->self->ranges_l1_[i].ok() &&
           u->self->ranges_l1_[i].readRangeM(range_m);
  }
#endif

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

#if ROSIE_HAS_ENCODERS
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
#endif

#if defined(ROSIE_MOTORS_TB6612)
  TB6612 motors_;
#elif defined(ROSIE_MOTORS_L298N)
  L298N motors_;
#endif
  DiffDriveKinematics kin_;
#if ROSIE_HAS_ENCODERS
  DiffDriveEncoders enc_;
#endif
#if ROSIE_HAS_IMU
  Mpu6050 imu_;
#endif
  PidVelocityController vel_;
#if ROSIE_HAS_CAMERA
  Esp32Camera* cam_ = nullptr;
#endif
#if ROSIE_HAS_RANGE
  Vl53l1x ranges_l1_[ROSIE_MAX_RANGE_SENSORS];
  Vl53l0x ranges_l0_[ROSIE_MAX_RANGE_SENSORS];
  RangeUser range_users_[ROSIE_MAX_RANGE_SENSORS];
#endif
  MobileBaseConfig cfg_;
  MobileBaseSensors sensors_;
  MobileBase base_;
  SerialShellHooks shell_hooks_;
  SerialShell shell_;
};

}  // namespace rosie
