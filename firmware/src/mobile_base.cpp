#include "rosie/mobile_base.h"
#include "rosie/diff_drive.h"

#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <math.h>
#include <string.h>

namespace rosie {

MobileBase::MobileBase(const MobileBaseConfig& cfg, MotorDriver& motors,
                       BaseKinematics& kinematics, const MobileBaseSensors& sensors)
    : cfg_(cfg),
      motors_(motors),
      kinematics_(kinematics),
      sensors_(sensors),
      session_(cfg.robot ? cfg.robot : "robot", cfg.fleet) {
  cmd_mux_ = xSemaphoreCreateMutex();
}

const char* MobileBase::modeName(DriveMode m) {
  switch (m) {
    case DriveMode::Manual:
      return "manual";
    case DriveMode::Auto:
      return "auto";
    default:
      return "idle";
  }
}

void MobileBase::lockCmd_() {
  if (cmd_mux_) xSemaphoreTake(static_cast<SemaphoreHandle_t>(cmd_mux_), portMAX_DELAY);
}

void MobileBase::unlockCmd_() {
  if (cmd_mux_) xSemaphoreGive(static_cast<SemaphoreHandle_t>(cmd_mux_));
}

bool MobileBase::onCmd(const char* op, CmdHandler handler, void* user) {
  if (!op || !handler || n_cmd_handlers_ >= kMaxCmdHandlers) return false;
  CmdBinding& b = cmd_handlers_[n_cmd_handlers_++];
  strncpy(b.op, op, sizeof(b.op) - 1);
  b.op[sizeof(b.op) - 1] = 0;
  b.handler = handler;
  b.user = user;
  return true;
}

void MobileBase::setVelocityController(VelocityController* controller) {
  vel_ = controller;
  if (vel_ && !gains_ops_registered_) {
    onCmd("set_gains", onSetGains_, this);
    onCmd("get_gains", onGetGains_, this);
    gains_ops_registered_ = true;
  }
}

void MobileBase::resetVelocity_() {
  if (vel_) vel_->reset();
}

void MobileBase::setUseImuHeading(bool on) {
  auto* kin = static_cast<DiffDriveKinematics*>(&kinematics_);
  kin->setUseImuHeading(on);
}

bool MobileBase::useImuHeading() const {
  const auto* kin = static_cast<const DiffDriveKinematics*>(&kinematics_);
  return kin->useImuHeading();
}

bool MobileBase::begin(const char* connect_locator, const char* mode) {
  if (!session_.ready()) {
    if (!session_.open(connect_locator, mode)) return false;
  }
  declareEndpoints_();
  ok_ = true;
  log("info", "MobileBase online (Rosie/Zenoh).");
  return true;
}

bool MobileBase::ready() const { return ok_ && session_.ready(); }

void MobileBase::declareEndpoints_() {
  if (endpoints_) return;
  pub_pose_ = session_.createPublisher("pose");
  pub_log_ = session_.createPublisher("log");
  pub_cam_ = session_.createPublisher("camera/compressed");
  pub_presence_ = session_.createPublisher("presence");
  pub_control_ = session_.createPublisher("control");
  session_.createSubscription("cmd_vel", onCmdVel_, this);
  session_.createSubscription("goto", onGoto_, this);
  session_.createSubscription("cmd", onCmd_, this);
  endpoints_ = true;
}

void MobileBase::onCmdVel_(const uint8_t* data, size_t len, void* user) {
  auto* self = static_cast<MobileBase*>(user);
  char buf[128];
  if (len >= sizeof(buf)) len = sizeof(buf) - 1;
  memcpy(buf, data, len);
  buf[len] = '\0';
  JsonDocument doc;
  if (deserializeJson(doc, buf)) return;
  float v = doc["v"] | 0.0f;
  float w = doc["w"] | 0.0f;
  self->lockCmd_();
  self->cmd_.cmd_v = v;
  self->cmd_.cmd_w = w;
  self->cmd_.last_cmd_vel_ms = millis();
  self->cmd_.cmd_vel_seen = true;
  self->unlockCmd_();
}

void MobileBase::onGoto_(const uint8_t* data, size_t len, void* user) {
  auto* self = static_cast<MobileBase*>(user);
  char buf[128];
  if (len >= sizeof(buf)) len = sizeof(buf) - 1;
  memcpy(buf, data, len);
  buf[len] = '\0';
  JsonDocument doc;
  if (deserializeJson(doc, buf)) return;
  if (!doc["x"].is<float>() && !doc["x"].is<int>()) return;
  if (!doc["y"].is<float>() && !doc["y"].is<int>()) return;
  self->lockCmd_();
  self->cmd_.goto_x = doc["x"].as<float>();
  self->cmd_.goto_y = doc["y"].as<float>();
  self->cmd_.goto_requested = true;
  self->unlockCmd_();
}

void MobileBase::onCmd_(const uint8_t* data, size_t len, void* user) {
  auto* self = static_cast<MobileBase*>(user);
  char buf[160];
  if (len >= sizeof(buf)) len = sizeof(buf) - 1;
  memcpy(buf, data, len);
  buf[len] = '\0';
  JsonDocument doc;
  if (deserializeJson(doc, buf)) return;
  const char* op = doc["op"] | "";
  if (strcmp(op, "stop") == 0) {
    self->lockCmd_();
    self->cmd_.stop_requested = true;
    self->unlockCmd_();
    return;
  }
  if (strcmp(op, "zero") == 0) {
    self->lockCmd_();
    self->cmd_.zero_requested = true;
    self->unlockCmd_();
    return;
  }
  for (int i = 0; i < self->n_cmd_handlers_; i++) {
    if (strcmp(self->cmd_handlers_[i].op, op) == 0) {
      self->cmd_handlers_[i].handler(op, doc["value"], self->cmd_handlers_[i].user);
      return;
    }
  }
}

void MobileBase::onSetGains_(const char* /*op*/, JsonVariantConst value, void* user) {
  auto* self = static_cast<MobileBase*>(user);
  if (!self->vel_) {
    self->log("warn", "No velocity controller attached.");
    return;
  }
  VelocityGains g = self->vel_->gains();
  if (value.isNull() || !value.is<JsonObjectConst>()) {
    self->log("warn", "set_gains expects {kp,ki,kd,i_clamp} (partial OK).");
    return;
  }
  JsonObjectConst obj = value.as<JsonObjectConst>();
  if (!obj["kp"].isNull()) g.kp = obj["kp"].as<float>();
  if (!obj["ki"].isNull()) g.ki = obj["ki"].as<float>();
  if (!obj["kd"].isNull()) g.kd = obj["kd"].as<float>();
  if (!obj["i_clamp"].isNull()) g.i_clamp = obj["i_clamp"].as<float>();
  self->vel_->configure(g);
  char buf[96];
  snprintf(buf, sizeof(buf), "gains kp=%.3f ki=%.3f kd=%.3f i_clamp=%.3f", g.kp, g.ki,
           g.kd, g.i_clamp);
  self->log("info", buf);
  self->publishControl_();
}

void MobileBase::onGetGains_(const char* /*op*/, JsonVariantConst /*value*/, void* user) {
  auto* self = static_cast<MobileBase*>(user);
  if (!self->vel_) {
    self->log("warn", "No velocity controller attached.");
    return;
  }
  self->publishControl_();
  VelocityGains g = self->vel_->gains();
  char buf[96];
  snprintf(buf, sizeof(buf), "gains kp=%.3f ki=%.3f kd=%.3f i_clamp=%.3f", g.kp, g.ki,
           g.kd, g.i_clamp);
  self->log("info", buf);
}

void MobileBase::requestStop() {
  lockCmd_();
  cmd_.stop_requested = true;
  unlockCmd_();
}

void MobileBase::requestZero() {
  lockCmd_();
  cmd_.zero_requested = true;
  unlockCmd_();
}

void MobileBase::requestGoto(float x, float y) {
  lockCmd_();
  cmd_.goto_x = x;
  cmd_.goto_y = y;
  cmd_.goto_requested = true;
  unlockCmd_();
}

void MobileBase::injectCmdVel(float v, float w) {
  lockCmd_();
  cmd_.cmd_v = v;
  cmd_.cmd_w = w;
  cmd_.last_cmd_vel_ms = millis();
  cmd_.cmd_vel_seen = true;
  unlockCmd_();
}

void MobileBase::driveTwist_(float v, float w) {
  float ff[8] = {0};
  float target[8] = {0};
  float meas[8] = {0};
  float out[8] = {0};
  size_t n = kinematics_.channelCount();
  if (n > 8) n = 8;
  float dt = cfg_.dt_ms / 1000.0f;

  kinematics_.twistToChannels(v, w, ff, n);
  kinematics_.twistToWheelVel(v, w, target, n);
  kinematics_.wheelVelocities(meas, n);

  last_n_ch_ = n;
  for (size_t i = 0; i < n; i++) {
    last_target_vel_[i] = target[i];
    last_meas_vel_[i] = meas[i];
  }

  if (vel_) {
    vel_->update(ff, target, meas, n, dt, out);
    motors_.setChannels(out, n);
  } else {
    motors_.setChannels(ff, n);
  }
}

void MobileBase::teleopDrive_(float v, float w) { driveTwist_(v, w); }

void MobileBase::navigate_() {
  Pose2DState p = kinematics_.pose();
  float dx = target_x_ - p.x;
  float dy = target_y_ - p.y;
  float distance = sqrtf(dx * dx + dy * dy);
  const GotoGains& g = cfg_.goto_gains;

  if (distance < g.pos_tolerance) {
    motors_.stop();
    resetVelocity_();
    navigating_ = false;
    mode_ = DriveMode::Idle;
    char buf[80];
    snprintf(buf, sizeof(buf), "Arrived at (%.3f, %.3f) m, heading %.1f deg", p.x, p.y,
             p.theta * 180.0f / static_cast<float>(M_PI));
    log("info", buf);
    return;
  }

  float target_heading = atan2f(dy, dx);
  float heading_err = target_heading - p.theta;
  while (heading_err > static_cast<float>(M_PI)) heading_err -= 2.0f * static_cast<float>(M_PI);
  while (heading_err < -static_cast<float>(M_PI)) heading_err += 2.0f * static_cast<float>(M_PI);

  if (distance < g.approach_dist && fabsf(heading_err) > static_cast<float>(M_PI) * 0.5f) {
    motors_.stop();
    resetVelocity_();
    navigating_ = false;
    mode_ = DriveMode::Idle;
    char buf[96];
    snprintf(buf, sizeof(buf), "Arrived (past goal) at (%.3f, %.3f) m, heading %.1f deg", p.x, p.y,
             p.theta * 180.0f / static_cast<float>(M_PI));
    log("info", buf);
    return;
  }

  float v = g.kp_linear * distance;
  float w = g.kp_angular * heading_err;
  if (distance < g.approach_dist) w *= (distance / g.approach_dist);

  float abs_err = fabsf(heading_err);
  float gate = 1.0f - (abs_err / g.align_tol);
  if (gate < 0.0f) gate = 0.0f;
  v *= gate;
  if (v < 0) v = 0;

  if (v > g.v_max) v = g.v_max;
  if (w > g.w_max) w = g.w_max;
  if (w < -g.w_max) w = -g.w_max;

  driveTwist_(v, w);
}

void MobileBase::tick() {
  int32_t ticks[8] = {0};
  size_t nch = kinematics_.channelCount();
  if (nch > 8) nch = 8;
  if (sensors_.readTicks) {
    sensors_.readTicks(&ticks[0], &ticks[1], sensors_.user);
  }
  float yaw = NAN;
  float dt = cfg_.dt_ms / 1000.0f;
  if (sensors_.readYawRate) {
    float yr = 0;
    if (sensors_.readYawRate(&yr, sensors_.user)) yaw = yr;
  }
  kinematics_.updateOdometry(ticks, nch, dt, yaw);

  CommandState snap;
  lockCmd_();
  snap = cmd_;
  cmd_.stop_requested = false;
  cmd_.zero_requested = false;
  cmd_.goto_requested = false;
  cmd_.cmd_vel_seen = false;
  unlockCmd_();

  DriveMode prev_mode = mode_;

  if (snap.stop_requested) {
    navigating_ = false;
    mode_ = DriveMode::Idle;
    motors_.stop();
    resetVelocity_();
    log("info", "Stopped.");
  }
  if (snap.zero_requested) {
    kinematics_.zeroPose();
    if (sensors_.onZeroPose) sensors_.onZeroPose(sensors_.user);
    mode_ = DriveMode::Idle;
    navigating_ = false;
    motors_.stop();
    resetVelocity_();
    log("info", "Pose zeroed.");
  }
  if (snap.goto_requested) {
    target_x_ = snap.goto_x;
    target_y_ = snap.goto_y;
    navigating_ = true;
    mode_ = DriveMode::Auto;
    char buf[64];
    snprintf(buf, sizeof(buf), "New target: (%.3f, %.3f) m", target_x_, target_y_);
    log("info", buf);
  }
  if (snap.cmd_vel_seen) {
    mode_ = DriveMode::Manual;
    navigating_ = false;
  }

  if (mode_ != prev_mode && (mode_ == DriveMode::Manual || mode_ == DriveMode::Auto ||
                             prev_mode == DriveMode::Manual || prev_mode == DriveMode::Auto)) {
    resetVelocity_();
  }

  switch (mode_) {
    case DriveMode::Auto:
      if (navigating_) navigate_();
      else mode_ = DriveMode::Idle;
      break;
    case DriveMode::Manual: {
      unsigned long age = millis() - snap.last_cmd_vel_ms;
      if (age > cfg_.teleop_timeout_ms) {
        motors_.stop();
        resetVelocity_();
        mode_ = DriveMode::Idle;
        log("warn", "Teleop deadman timeout.");
      } else {
        teleopDrive_(snap.cmd_v, snap.cmd_w);
      }
      break;
    }
    case DriveMode::Idle:
    default:
      break;
  }
}

void MobileBase::spin() {
  session_.poll();
  unsigned long now = millis();
  if (now - last_loop_ms_ >= cfg_.dt_ms) {
    last_loop_ms_ = now;
    tick();
  }
  unsigned long pose_ms =
      cfg_.pose_hz > 0.1f ? (unsigned long)(1000.0f / cfg_.pose_hz) : 50;
  unsigned long presence_ms =
      cfg_.presence_hz > 0.1f ? (unsigned long)(1000.0f / cfg_.presence_hz) : 1000;
  unsigned long control_ms =
      cfg_.control_hz > 0.1f ? (unsigned long)(1000.0f / cfg_.control_hz) : 200;
  if (ready() && (now - last_pose_ms_ >= pose_ms)) {
    last_pose_ms_ = now;
    publishPose_();
  }
  if (ready() && (now - last_presence_ms_ >= presence_ms)) {
    last_presence_ms_ = now;
    publishPresence_();
  }
  if (ready() && vel_ && (now - last_control_ms_ >= control_ms)) {
    last_control_ms_ = now;
    publishControl_();
  }
}

void MobileBase::publishPose_() {
  if (pub_pose_ < 0) return;
  Pose2DState p = kinematics_.pose();
  float dx = target_x_ - p.x;
  float dy = target_y_ - p.y;
  float dist = sqrtf(dx * dx + dy * dy);
  JsonDocument doc;
  doc["x"] = p.x;
  doc["y"] = p.y;
  doc["theta"] = p.theta;
  doc["heading_deg"] = p.theta * 180.0f / static_cast<float>(M_PI);
  doc["dist"] = dist;
  doc["navigating"] = navigating_;
  doc["mode"] = modeName(mode_);
  doc["imu_ok"] = imu_ok_;
  doc["imu_heading"] = imu_ok_ && useImuHeading();
  session_.publishJson(pub_pose_, doc);
}

void MobileBase::publishPresence_() {
  if (pub_presence_ < 0) return;
  JsonDocument doc;
  doc["robot_id"] = session_.getRobot();
  if (session_.hasFleet()) doc["fleet_id"] = session_.getFleet();
  doc["status"] = "ready";
  session_.publishJson(pub_presence_, doc);
}

void MobileBase::publishControl_() {
  if (pub_control_ < 0 || !vel_) return;
  VelocityGains g = vel_->gains();
  JsonDocument doc;
  doc["kp"] = g.kp;
  doc["ki"] = g.ki;
  doc["kd"] = g.kd;
  doc["i_clamp"] = g.i_clamp;
  doc["mode"] = modeName(mode_);
  JsonArray tgt = doc["target_vel"].to<JsonArray>();
  JsonArray meas = doc["meas_vel"].to<JsonArray>();
  for (size_t i = 0; i < last_n_ch_; i++) {
    tgt.add(last_target_vel_[i]);
    meas.add(last_meas_vel_[i]);
  }
  session_.publishJson(pub_control_, doc);
}

void MobileBase::log(const char* level, const char* msg) {
  Serial.printf("LOG[%s] %s\n", level, msg);
  if (!ready() || pub_log_ < 0) return;
  JsonDocument doc;
  doc["level"] = level;
  doc["msg"] = msg;
  session_.publishJson(pub_log_, doc);
}

bool MobileBase::publishJpeg(const uint8_t* data, size_t len) {
  if (!ready() || pub_cam_ < 0) return false;
  return session_.publish(pub_cam_, data, len);
}

}  // namespace rosie
