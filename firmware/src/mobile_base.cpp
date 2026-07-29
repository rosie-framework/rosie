/**
 * MobileBase — planar ground-robot application layer on Session.
 *
 * Typical call pattern (DiffDriveStack does this for you)::
 *
 *   begin(connect) → loop: spin()
 *
 * ``spin()`` does three independent things each Arduino ``loop()``:
 *
 *   - ``session_.poll()`` — no-op when ``Z_FEATURE_MULTI_THREAD=1`` (default);
 *     otherwise drains Zenoh on this thread
 *   - ``tick()`` — every ``control.dt_ms`` (odometry + mode + motors)
 *   - telemetry pubs — at pose_hz / presence_hz / …
 *
 * Latch vs actuate (important):
 *
 *   Under the default multi-threaded build, Zenoh callbacks run on the
 *   pico read task as soon as samples arrive (concurrent with ``tick()``).
 *   Built-in cmds (stop / zero / goto / cmd_vel) never touch motors there —
 *   they only write the latest request into ``cmd_`` under a mutex ("latch").
 *   ``tick()`` later snapshots ``cmd_`` and performs mode changes +
 *   ``driveTwist_`` ("actuate"). Many cmd_vels between ticks overwrite the
 *   latch; only the last one is applied at dt_ms. Custom ``cmd`` handlers
 *   (e.g. set_gains) may run immediately in the callback.
 *
 * See docs/robots/mobile-base.md (control loop timing + topics/YAML).
 */

#include "rosie/mobile_base.h"
#include "rosie/diff_drive.h"

#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <math.h>
#include <string.h>

namespace rosie {

// ---------------------------------------------------------------------------
// Construction / configuration
// ---------------------------------------------------------------------------

MobileBase::MobileBase(const MobileBaseConfig& cfg, MotorDriver& motors,
                       BaseKinematics& kinematics, const MobileBaseSensors& sensors)
    : cfg_(cfg),
      motors_(motors),
      kinematics_(kinematics),
      sensors_(sensors),
      session_(cfg.robot ? cfg.robot : "robot", cfg.fleet) {
  // Protects cmd_ between Zenoh callbacks (other tasks) and tick().
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
  // DiffDriveKinematics owns the IMU-vs-encoder heading flag today.
  auto* kin = static_cast<DiffDriveKinematics*>(&kinematics_);
  kin->setUseImuHeading(on);
}

bool MobileBase::useImuHeading() const {
  const auto* kin = static_cast<const DiffDriveKinematics*>(&kinematics_);
  return kin->useImuHeading();
}

// ---------------------------------------------------------------------------
// Session bring-up and topic endpoints
// ---------------------------------------------------------------------------

bool MobileBase::begin(const char* connect_locator, const char* mode,
                       const char* user, const char* password) {
  // Caller brings up Wi‑Fi first; we only open Zenoh + declare topics.
  if (!session_.ready()) {
    if (!session_.open(connect_locator, mode, user, password)) return false;
  }
  declareEndpoints_();
  ok_ = true;
  log("info", "MobileBase online (Rosie/Zenoh).");
  return true;
}

bool MobileBase::ready() const { return ok_ && session_.ready(); }

/** Declare standard MobileBase pubs/subs once (relative names → Session prefix). */
void MobileBase::declareEndpoints_() {
  if (endpoints_) return;
  pub_pose_ = session_.createPublisher("pose", Qos::Stream);
  pub_log_ = session_.createPublisher("log", Qos::Stream);
  pub_cam_ = session_.createPublisher("camera/compressed", Qos::Bulk);
  pub_presence_ = session_.createPublisher("presence", Qos::Stream);
  pub_control_ = session_.createPublisher("control", Qos::Stream);
  // COMMAND: high priority + express; MCU still DROP (never block in tick).
  pub_nav_result_ = session_.createPublisher("nav_result", Qos::Command);
  // Optional raw telemetry — only when pub_hz > 0 (uses Session pub slots).
  if (cfg_.encoders_hz > 0.1f) {
    pub_encoders_ = session_.createPublisher("encoders", Qos::Stream);
  }
  if (cfg_.imu_hz > 0.1f) {
    pub_imu_ = session_.createPublisher("imu", Qos::Stream);
  }
  session_.createSubscription("cmd_vel", onCmdVel_, this);
  session_.createSubscription("goto", onGoto_, this);
  session_.createSubscription("cmd", onCmd_, this);
  endpoints_ = true;
}

// ---------------------------------------------------------------------------
// Zenoh inbox callbacks — latch only for motion (no motors here)
//
// Under Z_FEATURE_MULTI_THREAD=1 (default), these run on the zenoh-pico read
// task as soon as a sample arrives — not from spin()/poll(). They must stay
// short: parse JSON, update cmd_, return. Motors, mode transitions, and
// odometry run later in tick() at a fixed dt_ms. Custom cmd handlers
// (set_gains / get_gains) may run immediately in this task.
// ---------------------------------------------------------------------------

/** Latch Twist into cmd_; Manual mode + drive happen on the next tick(). */
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

/** Latch planar goal into cmd_; Auto navigation starts on the next tick(). */
void MobileBase::onGoto_(const uint8_t* data, size_t len, void* user) {
  auto* self = static_cast<MobileBase*>(user);
  char buf[160];
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
  if (!doc["goal_id"].isNull()) {
    self->cmd_.goto_has_goal_id = true;
    self->cmd_.goto_goal_id = doc["goal_id"].as<int32_t>();
  } else {
    self->cmd_.goto_has_goal_id = false;
    self->cmd_.goto_goal_id = 0;
  }
  self->cmd_.goto_ms = millis();
  self->cmd_.goto_requested = true;
  self->unlockCmd_();
}

/**
 * Latch discrete ``cmd`` ops (or dispatch custom handlers).
 * Built-ins stop/zero only set flags; tick() stops motors / zeros pose.
 * Handlers registered via onCmd() (e.g. set_gains) may run here immediately.
 */
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
    self->cmd_.stop_ms = millis();
    self->unlockCmd_();
    return;
  }
  if (strcmp(op, "zero") == 0) {
    self->lockCmd_();
    self->cmd_.zero_requested = true;
    self->cmd_.zero_ms = millis();
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

/** Partial PID update ``{kp,ki,kd,i_clamp}`` then republish ``control``. */
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

/** Ask robot to publish current gains / wheel velocities on ``control``. */
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

// ---------------------------------------------------------------------------
// Local request API (USB shell, DiffDriveStack, tests) — same inbox as Zenoh
// ---------------------------------------------------------------------------

void MobileBase::requestStop() {
  lockCmd_();
  cmd_.stop_requested = true;
  cmd_.stop_ms = millis();
  unlockCmd_();
}

void MobileBase::requestZero() {
  lockCmd_();
  cmd_.zero_requested = true;
  cmd_.zero_ms = millis();
  unlockCmd_();
}

void MobileBase::requestGoto(float x, float y, int32_t goal_id, bool has_goal_id) {
  lockCmd_();
  cmd_.goto_x = x;
  cmd_.goto_y = y;
  cmd_.goto_goal_id = goal_id;
  cmd_.goto_has_goal_id = has_goal_id;
  cmd_.goto_ms = millis();
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

// ---------------------------------------------------------------------------
// Actuation: body Twist → kinematics → optional wheel PID → motors
// ---------------------------------------------------------------------------

/**
 * Shared drive path for Manual and Auto.
 * Feedforward channels always computed; VelocityController corrects when set.
 */
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

// ---------------------------------------------------------------------------
// Auto mode: pose error → Twist (cascaded outer loop)
// ---------------------------------------------------------------------------

void MobileBase::publishNavResult_(const char* status) {
  if (pub_nav_result_ < 0) return;
  Pose2DState p = kinematics_.pose();
  JsonDocument doc;
  doc["goal_id"] = active_goal_id_;
  doc["status"] = status;
  doc["x"] = p.x;
  doc["y"] = p.y;
  session_.publishJson(pub_nav_result_, doc);
}

/** Terminal end of a goto: publish nav_result once, stop, return to Idle. */
void MobileBase::endNavigation_(const char* status) {
  if (!navigating_) return;
  navigating_ = false;
  publishNavResult_(status);
  mode_ = DriveMode::Idle;
  motors_.stop();
  resetVelocity_();
}

/**
 * One Auto-mode control step toward (target_x_, target_y_).
 * Succeeds within pos_tolerance (or past-goal near approach_dist).
 * Linear speed gated by heading alignment (align_tol).
 */
void MobileBase::navigate_() {
  Pose2DState p = kinematics_.pose();
  float dx = target_x_ - p.x;
  float dy = target_y_ - p.y;
  float distance = sqrtf(dx * dx + dy * dy);
  const GotoGains& g = cfg_.goto_gains;

  if (distance < g.pos_tolerance) {
    char buf[80];
    snprintf(buf, sizeof(buf), "Arrived at (%.3f, %.3f) m, heading %.1f deg", p.x, p.y,
             p.theta * 180.0f / static_cast<float>(M_PI));
    log("info", buf);
    endNavigation_("succeeded");
    return;
  }

  float target_heading = atan2f(dy, dx);
  float heading_err = target_heading - p.theta;
  while (heading_err > static_cast<float>(M_PI)) heading_err -= 2.0f * static_cast<float>(M_PI);
  while (heading_err < -static_cast<float>(M_PI)) heading_err += 2.0f * static_cast<float>(M_PI);

  // Near the goal but pointing away — treat as arrived (avoid spinning in place).
  if (distance < g.approach_dist && fabsf(heading_err) > static_cast<float>(M_PI) * 0.5f) {
    char buf[96];
    snprintf(buf, sizeof(buf), "Arrived (past goal) at (%.3f, %.3f) m, heading %.1f deg", p.x, p.y,
             p.theta * 180.0f / static_cast<float>(M_PI));
    log("info", buf);
    endNavigation_("succeeded");
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

// ---------------------------------------------------------------------------
// Control tick — odometry + command arbiter + mode behavior
// ---------------------------------------------------------------------------

/**
 * One control period (``control.dt_ms``). Prefer calling via spin().
 *
 * This is where latched inbox state becomes action:
 *
 *   1. Sensors → odometry
 *   2. Snapshot + clear edge flags in cmd_ (mutex); arrival stamps retained
 *   3. Mode transitions from that snapshot (arrival-order: stop/zero beat
 *      older cmd_vel; goto ignores duplicate/stale goal_id while navigating)
 *   4. Manual (deadman teleop) or Auto (goto) → driveTwist_ → motors
 */
void MobileBase::tick() {
  // --- Sensors → odometry (+ cache for optional encoders/imu topics) ---
  int32_t ticks[8] = {0};
  size_t nch = kinematics_.channelCount();
  if (nch > 8) nch = 8;
  if (sensors_.readTicks) {
    sensors_.readTicks(&ticks[0], &ticks[1], sensors_.user);
    last_enc_left_ = ticks[0];
    last_enc_right_ = ticks[1];
    last_enc_valid_ = true;
  } else {
    last_enc_valid_ = false;
  }
  float yaw = NAN;
  float dt = cfg_.dt_ms / 1000.0f;
  if (sensors_.readYawRate) {
    float yr = 0;
    if (sensors_.readYawRate(&yr, sensors_.user)) yaw = yr;
  }
  if (sensors_.readImu) {
    float ax, ay, az, gx, gy, gz;
    if (sensors_.readImu(&ax, &ay, &az, &gx, &gy, &gz, sensors_.user)) {
      last_accel_[0] = ax;
      last_accel_[1] = ay;
      last_accel_[2] = az;
      last_gyro_[0] = gx;
      last_gyro_[1] = gy;
      last_gyro_[2] = gz;
      last_imu_ok_ = true;
    } else {
      last_imu_ok_ = false;
    }
  } else {
    last_imu_ok_ = false;
  }
  kinematics_.updateOdometry(ticks, nch, dt, yaw);

  // --- Snapshot + clear edge-triggered inbox flags (keep arrival stamps) ---
  CommandState snap;
  lockCmd_();
  snap = cmd_;
  cmd_.stop_requested = false;
  cmd_.zero_requested = false;
  cmd_.goto_requested = false;
  cmd_.cmd_vel_seen = false;
  unlockCmd_();

  DriveMode prev_mode = mode_;

  // --- Apply discrete requests by arrival order (MCU-local millis stamps) ---
  if (snap.stop_requested) {
    if (navigating_) {
      endNavigation_("canceled");
      log("info", "Stopped.");
    } else {
      mode_ = DriveMode::Idle;
      motors_.stop();
      resetVelocity_();
      log("info", "Stopped.");
    }
  }
  if (snap.zero_requested) {
    if (navigating_) endNavigation_("canceled");
    kinematics_.zeroPose();
    if (sensors_.onZeroPose) sensors_.onZeroPose(sensors_.user);
    mode_ = DriveMode::Idle;
    motors_.stop();
    resetVelocity_();
    log("info", "Pose zeroed.");
  }
  if (snap.goto_requested) {
    // Superseded by a newer stop/zero in the same window (or sticky stamps).
    if (snap.goto_ms < snap.stop_ms || snap.goto_ms < snap.zero_ms) {
      // ignore
    } else if (navigating_ && snap.goto_has_goal_id) {
      if (snap.goto_goal_id == active_goal_id_) {
        // Duplicate of the goal already in progress — keep driving.
      } else if (snap.goto_goal_id < active_goal_id_) {
        char buf[72];
        snprintf(buf, sizeof(buf), "Ignoring stale goto goal_id=%ld (active=%ld)",
                 (long)snap.goto_goal_id, (long)active_goal_id_);
        log("warn", buf);
      } else {
        if (navigating_) endNavigation_("canceled");
        target_x_ = snap.goto_x;
        target_y_ = snap.goto_y;
        active_goal_id_ = snap.goto_goal_id;
        if (active_goal_id_ >= next_goal_id_) next_goal_id_ = active_goal_id_ + 1;
        navigating_ = true;
        mode_ = DriveMode::Auto;
        char buf[80];
        snprintf(buf, sizeof(buf), "New target: (%.3f, %.3f) m goal_id=%ld", target_x_,
                 target_y_, (long)active_goal_id_);
        log("info", buf);
      }
    } else {
      if (navigating_) endNavigation_("canceled");
      target_x_ = snap.goto_x;
      target_y_ = snap.goto_y;
      if (snap.goto_has_goal_id) {
        active_goal_id_ = snap.goto_goal_id;
        if (active_goal_id_ >= next_goal_id_) next_goal_id_ = active_goal_id_ + 1;
      } else {
        active_goal_id_ = next_goal_id_++;
      }
      navigating_ = true;
      mode_ = DriveMode::Auto;
      char buf[80];
      snprintf(buf, sizeof(buf), "New target: (%.3f, %.3f) m goal_id=%ld", target_x_,
               target_y_, (long)active_goal_id_);
      log("info", buf);
    }
  }
  // Enter Manual only if cmd_vel arrived after the latest stop/zero (sticky stop).
  if (snap.cmd_vel_seen && snap.last_cmd_vel_ms > snap.stop_ms &&
      snap.last_cmd_vel_ms > snap.zero_ms) {
    if (navigating_) endNavigation_("canceled");
    mode_ = DriveMode::Manual;
  }

  // Reset wheel PID integrators on Manual/Auto transitions.
  if (mode_ != prev_mode && (mode_ == DriveMode::Manual || mode_ == DriveMode::Auto ||
                             prev_mode == DriveMode::Manual || prev_mode == DriveMode::Auto)) {
    resetVelocity_();
  }

  // --- Mode behavior ---
  switch (mode_) {
    case DriveMode::Auto:
      if (navigating_) navigate_();
      else mode_ = DriveMode::Idle;
      break;
    case DriveMode::Manual: {
      // Deadman: stop if no fresh cmd_vel within teleop_timeout_ms.
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

/**
 * Arduino ``loop()`` entry: timed tick + telemetry publishers.
 *
 * Call as often as possible. Under ``Z_FEATURE_MULTI_THREAD=1`` (default),
 * ``session_.poll()`` is a no-op — Zenoh callbacks already run on the pico
 * read task. ``tick()`` runs only every ``dt_ms``. Publish rates are
 * independent (*_hz).
 */
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
  unsigned long encoders_ms =
      cfg_.encoders_hz > 0.1f ? (unsigned long)(1000.0f / cfg_.encoders_hz) : 0;
  unsigned long imu_ms =
      cfg_.imu_hz > 0.1f ? (unsigned long)(1000.0f / cfg_.imu_hz) : 0;
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
  if (ready() && encoders_ms > 0 && last_enc_valid_ &&
      (now - last_encoders_ms_ >= encoders_ms)) {
    last_encoders_ms_ = now;
    publishEncoders_();
  }
  if (ready() && imu_ms > 0 && sensors_.readImu &&
      (now - last_imu_ms_ >= imu_ms)) {
    last_imu_ms_ = now;
    publishImu_();
  }
}

// ---------------------------------------------------------------------------
// Telemetry publishers (JSON via Session; stamp filled by publishJson)
// ---------------------------------------------------------------------------

/** Pose2D + MobileBase extras (mode, navigating, dist, imu flags, …). */
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
  if (navigating_) doc["goal_id"] = active_goal_id_;
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

/** Velocity PID gains + last target/meas wheel velocities (when controller set). */
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

/** Cumulative quadrature ticks (EncoderTicks); requires encoders_hz > 0. */
void MobileBase::publishEncoders_() {
  if (pub_encoders_ < 0 || !last_enc_valid_) return;
  JsonDocument doc;
  doc["left"] = last_enc_left_;
  doc["right"] = last_enc_right_;
  session_.publishJson(pub_encoders_, doc);
}

/** 6-axis Imu sample (m/s², rad/s); requires imu_hz > 0 and readImu hook. */
void MobileBase::publishImu_() {
  if (pub_imu_ < 0) return;
  JsonDocument doc;
  doc["accel_x"] = last_imu_ok_ ? last_accel_[0] : 0.0f;
  doc["accel_y"] = last_imu_ok_ ? last_accel_[1] : 0.0f;
  doc["accel_z"] = last_imu_ok_ ? last_accel_[2] : 0.0f;
  doc["gyro_x"] = last_imu_ok_ ? last_gyro_[0] : 0.0f;
  doc["gyro_y"] = last_imu_ok_ ? last_gyro_[1] : 0.0f;
  doc["gyro_z"] = last_imu_ok_ ? last_gyro_[2] : 0.0f;
  doc["ok"] = last_imu_ok_;
  session_.publishJson(pub_imu_, doc);
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
