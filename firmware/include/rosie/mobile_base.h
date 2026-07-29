#pragma once

#include "rosie/base_kinematics.h"
#include "rosie/motor_driver.h"
#include "rosie/session.h"
#include "rosie/velocity_controller.h"

#include <ArduinoJson.h>
#include <stddef.h>
#include <stdint.h>

namespace rosie {

/** Outer-loop goto: pose error → body Twist (m/s, rad/s). */
struct GotoGains {
  float kp_linear = 0.8f;
  float kp_angular = 1.5f;
  float v_max = 0.35f;
  float w_max = 1.5f;
  float pos_tolerance = 0.025f;
  float approach_dist = 0.20f;
  float align_tol = 0.52f;
};

struct MobileBaseConfig {
  const char* robot = "robot";
  const char* fleet = nullptr;
  unsigned long dt_ms = 20;
  unsigned long teleop_timeout_ms = 400;
  float max_pwm = 100.0f;  // teleop / kinematics channel scale
  GotoGains goto_gains;
  float pose_hz = 20.0f;
  float presence_hz = 1.0f;
  float control_hz = 5.0f;  // velocity-controller telemetry
  float encoders_hz = 0.0f;  // 0 = off; optional EncoderTicks topic
  float imu_hz = 0.0f;       // 0 = off; optional Imu topic
};

enum class DriveMode : uint8_t {
  Idle = 0,
  Manual = 1,
  Auto = 2,
};

/** Optional hook for robot-specific cmd ops (e.g. camera_enable). */
using CmdHandler = void (*)(const char* op, JsonVariantConst value, void* user);

/**
 * Tick provider for encoders / IMU — robot or factory supplies these.
 * Return false from readYawRate / readImu if IMU unavailable.
 */
struct MobileBaseSensors {
  void (*readTicks)(int32_t* left, int32_t* right, void* user) = nullptr;
  bool (*readYawRate)(float* yaw_rad_s, void* user) = nullptr;
  /** Optional 6-axis sample: accel m/s², gyro rad/s. Used for imu topic. */
  bool (*readImu)(float* ax, float* ay, float* az, float* gx, float* gy,
                  float* gz, void* user) = nullptr;
  void (*onZeroPose)(void* user) = nullptr;  // e.g. clear encoders + recal IMU
  void* user = nullptr;
};

/**
 * Ground mobile-base application layer on Session.
 *
 * Owns cmd_vel / goto / cmd inbox, IDLE/MANUAL/AUTO arbiter, teleop deadman,
 * cascaded goto (pose → Twist) + optional VelocityController, and publishers.
 *
 * Inbox callbacks latch motion requests into an internal command state;
 * under the default multi-threaded Zenoh build they run on the pico read
 * task. ``tick()`` (via ``spin()`` at ``dt_ms``) applies modes and drives
 * motors. See docs/robots/mobile-base.md § Control loop timing.
 */
class MobileBase {
 public:
  MobileBase(const MobileBaseConfig& cfg, MotorDriver& motors,
             BaseKinematics& kinematics, const MobileBaseSensors& sensors = {});

  void setSensors(const MobileBaseSensors& sensors) { sensors_ = sensors; }

  /**
   * Attach inner-loop velocity controller (teleop + goto share driveTwist_).
   * Registers set_gains / get_gains cmd ops. Pass nullptr to clear.
   */
  void setVelocityController(VelocityController* controller);

  /** Register custom cmd op (built-ins: stop, zero; set_gains/get_gains when vel set). */
  bool onCmd(const char* op, CmdHandler handler, void* user = nullptr);

  /**
   * Bring up network externally (softAP / wifiStation), then call begin.
   * Opens Session, declares topics. Retries are the caller's responsibility.
   */
  bool begin(const char* connect_locator, const char* mode = "client",
             const char* user = nullptr, const char* password = nullptr);
  bool ready() const;

  /** Poll session + fixed-rate control + pose/presence publish. Call from loop(). */
  void spin();

  /** One control tick (odom + arbiter). Prefer spin(). */
  void tick();

  void requestStop();
  void requestZero();
  void requestGoto(float x, float y, int32_t goal_id = 0, bool has_goal_id = false);
  void injectCmdVel(float v, float w);

  DriveMode mode() const { return mode_; }
  bool navigating() const { return navigating_; }
  int32_t activeGoalId() const { return active_goal_id_; }
  Pose2DState pose() const { return kinematics_.pose(); }
  float targetX() const { return target_x_; }
  float targetY() const { return target_y_; }

  void setImuOk(bool ok) { imu_ok_ = ok; }
  void setUseImuHeading(bool on);
  bool useImuHeading() const;

  void log(const char* level, const char* msg);
  bool publishJpeg(const uint8_t* data, size_t len);

  Session& session() { return session_; }
  MotorDriver& motors() { return motors_; }
  BaseKinematics& kinematics() { return kinematics_; }
  VelocityController* velocityController() { return vel_; }

  static const char* modeName(DriveMode m);

 private:
  static constexpr int kMaxCmdHandlers = 8;

  struct CmdBinding {
    char op[32] = {0};
    CmdHandler handler = nullptr;
    void* user = nullptr;
  };

  struct CommandState {
    bool stop_requested = false;
    bool zero_requested = false;
    bool goto_requested = false;
    float goto_x = 0, goto_y = 0;
    int32_t goto_goal_id = 0;
    bool goto_has_goal_id = false;
    float cmd_v = 0, cmd_w = 0;
    unsigned long last_cmd_vel_ms = 0;
    unsigned long stop_ms = 0;
    unsigned long zero_ms = 0;
    unsigned long goto_ms = 0;
    bool cmd_vel_seen = false;
  };

  void declareEndpoints_();
  void navigate_();
  void driveTwist_(float v, float w);
  void teleopDrive_(float v, float w);
  void resetVelocity_();
  void endNavigation_(const char* status);
  void publishNavResult_(const char* status);
  void publishPose_();
  void publishPresence_();
  void publishControl_();
  void publishEncoders_();
  void publishImu_();
  void lockCmd_();
  void unlockCmd_();

  static void onCmdVel_(const uint8_t* data, size_t len, void* user);
  static void onGoto_(const uint8_t* data, size_t len, void* user);
  static void onCmd_(const uint8_t* data, size_t len, void* user);
  static void onSetGains_(const char* op, JsonVariantConst value, void* user);
  static void onGetGains_(const char* op, JsonVariantConst value, void* user);

  MobileBaseConfig cfg_;
  MotorDriver& motors_;
  BaseKinematics& kinematics_;
  MobileBaseSensors sensors_;
  VelocityController* vel_ = nullptr;
  Session session_;

  int pub_pose_ = -1;
  int pub_log_ = -1;
  int pub_cam_ = -1;
  int pub_presence_ = -1;
  int pub_control_ = -1;
  int pub_nav_result_ = -1;
  int pub_encoders_ = -1;
  int pub_imu_ = -1;
  bool ok_ = false;
  bool endpoints_ = false;
  bool gains_ops_registered_ = false;

  DriveMode mode_ = DriveMode::Idle;
  bool navigating_ = false;
  float target_x_ = 0, target_y_ = 0;
  int32_t active_goal_id_ = 0;
  int32_t next_goal_id_ = 1;
  bool imu_ok_ = false;

  float last_target_vel_[8] = {0};
  float last_meas_vel_[8] = {0};
  size_t last_n_ch_ = 0;

  int32_t last_enc_left_ = 0;
  int32_t last_enc_right_ = 0;
  bool last_enc_valid_ = false;
  float last_accel_[3] = {0, 0, 0};
  float last_gyro_[3] = {0, 0, 0};
  bool last_imu_ok_ = false;

  CommandState cmd_;
  void* cmd_mux_ = nullptr;

  CmdBinding cmd_handlers_[kMaxCmdHandlers];
  int n_cmd_handlers_ = 0;

  unsigned long last_loop_ms_ = 0;
  unsigned long last_pose_ms_ = 0;
  unsigned long last_presence_ms_ = 0;
  unsigned long last_control_ms_ = 0;
  unsigned long last_encoders_ms_ = 0;
  unsigned long last_imu_ms_ = 0;
};

}  // namespace rosie
