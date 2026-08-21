#include "rosie/session.h"
#include <zenoh-pico.h>
#include <esp_rom_sys.h>
#include <string.h>

namespace rosie {

struct SubSlot {
  z_owned_subscriber_t sub;
  SampleCallback cb = nullptr;
  void* user = nullptr;
  bool used = false;
};

struct PubSlot {
  z_owned_publisher_t pub;
  bool used = false;
};

struct Session::Impl {
  z_owned_session_t session;
  PubSlot pubs[Session::kMaxPubs];
  SubSlot subs[Session::kMaxSubs];
};

static void sampleTrampoline(z_loaned_sample_t* sample, void* arg) {
  auto* slot = static_cast<SubSlot*>(arg);
  if (!slot || !slot->cb) return;
  z_owned_slice_t slice;
  if (z_bytes_to_slice(z_sample_payload(sample), &slice) < 0) return;
  const uint8_t* data = z_slice_data(z_slice_loan(&slice));
  size_t len = z_slice_len(z_slice_loan(&slice));
  slot->cb(data, len, slot->user);
  z_slice_drop(z_slice_move(&slice));
}

void Session::copyId_(char* dst, size_t dst_len, const char* src, const char* fallback) {
  if (!src || !src[0]) {
    strncpy(dst, fallback ? fallback : "", dst_len - 1);
  } else {
    while (*src == '/') ++src;
    strncpy(dst, src, dst_len - 1);
  }
  dst[dst_len - 1] = '\0';
  size_t n = strlen(dst);
  while (n > 0 && dst[n - 1] == '/') {
    dst[--n] = '\0';
  }
}

Session::Session(const char* robot, const char* fleet) {
  impl_ = new Impl();
  memset(impl_, 0, sizeof(Impl));
  setIdentity(robot, fleet);
}

Session::~Session() {
  if (!impl_) return;
  delete impl_;
  impl_ = nullptr;
}

void Session::setIdentity(const char* robot, const char* fleet) {
  copyId_(robot_, sizeof(robot_), robot, "robot");
  if (!robot_[0]) {
    strncpy(robot_, "robot", sizeof(robot_) - 1);
    robot_[sizeof(robot_) - 1] = '\0';
  }
  if (strcmp(robot_, "_fleet") == 0) {
    Serial.println("Rosie: robot id '_fleet' is reserved; using 'robot'");
    strncpy(robot_, "robot", sizeof(robot_) - 1);
    robot_[sizeof(robot_) - 1] = '\0';
  }
  if (!fleet || !fleet[0]) {
    fleet_[0] = '\0';
  } else {
    copyId_(fleet_, sizeof(fleet_), fleet, "");
  }
}

bool Session::resolveName(const char* name, char* out, size_t out_len) const {
  if (!out || out_len == 0 || !name || !name[0]) return false;

  if (name[0] == '/') {
    while (*name == '/') ++name;
    if (!name[0]) return false;
    if (strlen(name) + 1 > out_len) return false;
    strncpy(out, name, out_len - 1);
    out[out_len - 1] = '\0';
    return true;
  }

  if (fleet_[0]) {
    size_t need = strlen(fleet_) + 1 + strlen(robot_) + 1 + strlen(name) + 1;
    if (need > out_len) return false;
    snprintf(out, out_len, "%s/%s/%s", fleet_, robot_, name);
  } else {
    size_t need = strlen(robot_) + 1 + strlen(name) + 1;
    if (need > out_len) return false;
    snprintf(out, out_len, "%s/%s", robot_, name);
  }
  return true;
}

bool Session::resolveFleetName(const char* name, char* out, size_t out_len) const {
  if (!out || out_len == 0 || !name || !name[0] || !fleet_[0]) return false;
  while (*name == '/') ++name;
  if (!name[0]) return false;
  size_t need = strlen(fleet_) + 1 + 6 + 1 + strlen(name) + 1;  // /_fleet/
  if (need > out_len) return false;
  snprintf(out, out_len, "%s/_fleet/%s", fleet_, name);
  return true;
}

bool Session::open(const char* connect_locator, const char* mode,
                   const char* user, const char* password) {
  if (!impl_ || ok_) return ok_;

  z_owned_config_t config;
  z_config_default(&config);
  zp_config_insert(z_config_loan_mut(&config), Z_CONFIG_MODE_KEY, mode);
  zp_config_insert(z_config_loan_mut(&config), Z_CONFIG_CONNECT_KEY, connect_locator);
  if (user && user[0] && password && password[0]) {
    // zenoh-pico currently exposes USER/PASSWORD config keys but does not
    // implement usrpwd handshake. Keep inserting for forward compatibility;
    // authenticated routers will reject MCU clients until pico supports auth.
    zp_config_insert(z_config_loan_mut(&config), Z_CONFIG_USER_KEY, user);
    zp_config_insert(z_config_loan_mut(&config), Z_CONFIG_PASSWORD_KEY, password);
    Serial.printf("Rosie: Zenoh auth user='%s' (pico may ignore usrpwd)\n", user);
    esp_rom_printf("Rosie: Zenoh auth user='%s' (pico may ignore usrpwd)\n", user);
  }

  Serial.printf("Rosie: opening Zenoh session to %s ...\n", connect_locator);
  esp_rom_printf("Rosie: opening Zenoh session to %s ...\n", connect_locator);
  if (z_open(&impl_->session, z_config_move(&config), NULL) < 0) {
    Serial.println("Rosie: unable to open session (is zenohd running?).");
    esp_rom_printf("Rosie: unable to open Zenoh session.\n");
    return false;
  }

  if (zp_start_read_task(z_session_loan_mut(&impl_->session), NULL) < 0) {
    Serial.println("Rosie: failed to start read task");
  } else if (zp_start_lease_task(z_session_loan_mut(&impl_->session), NULL) < 0) {
    Serial.println("Rosie: failed to start lease task");
  }
  ok_ = true;
  Serial.println("Rosie: Zenoh session ready.");
  esp_rom_printf("Rosie: Zenoh session ready.\n");
  return true;
}

void Session::fillPublisherOptions_(Qos qos, void* options_out) {
  auto* opts = static_cast<z_publisher_options_t*>(options_out);
  z_publisher_options_default(opts);
  // MCU never BLOCK: nav_result / telemetry may publish from tick(); a blocking
  // put would stall the control loop. Host Python uses BLOCK for Command/Critical.
  opts->congestion_control = Z_CONGESTION_CONTROL_DROP;
  switch (qos) {
    case Qos::Command:
      opts->priority = Z_PRIORITY_INTERACTIVE_HIGH;
      opts->is_express = true;
      break;
    case Qos::Bulk:
      opts->priority = Z_PRIORITY_DATA_LOW;
      opts->is_express = false;
      break;
    case Qos::Stream:
    default:
      opts->priority = Z_PRIORITY_DATA;
      opts->is_express = false;
      break;
  }
}

int Session::createPublisher(const char* name, Qos qos) {
  if (!ok_ || !impl_) return -1;
  char keyexpr[kMaxKeyLen];
  if (!resolveName(name, keyexpr, sizeof(keyexpr))) {
    Serial.printf("Rosie: bad publisher name: %s\n", name ? name : "(null)");
    return -1;
  }
  for (int i = 0; i < kMaxPubs; i++) {
    if (impl_->pubs[i].used) continue;
    z_view_keyexpr_t ke;
    z_view_keyexpr_from_str_unchecked(&ke, keyexpr);
    z_publisher_options_t opts;
    fillPublisherOptions_(qos, &opts);
    if (z_declare_publisher(z_session_loan(&impl_->session), &impl_->pubs[i].pub,
                            z_view_keyexpr_loan(&ke), &opts) < 0) {
      Serial.printf("Rosie: declare publisher failed: %s\n", keyexpr);
      return -1;
    }
    impl_->pubs[i].used = true;
    return i;
  }
  Serial.println("Rosie: no free publisher slots");
  return -1;
}

int Session::createFleetPublisher(const char* name, Qos qos) {
  if (!ok_ || !impl_) return -1;
  char keyexpr[kMaxKeyLen];
  if (!resolveFleetName(name, keyexpr, sizeof(keyexpr))) {
    Serial.printf("Rosie: bad fleet publisher name: %s\n", name ? name : "(null)");
    return -1;
  }
  for (int i = 0; i < kMaxPubs; i++) {
    if (impl_->pubs[i].used) continue;
    z_view_keyexpr_t ke;
    z_view_keyexpr_from_str_unchecked(&ke, keyexpr);
    z_publisher_options_t opts;
    fillPublisherOptions_(qos, &opts);
    if (z_declare_publisher(z_session_loan(&impl_->session), &impl_->pubs[i].pub,
                            z_view_keyexpr_loan(&ke), &opts) < 0) {
      Serial.printf("Rosie: declare publisher failed: %s\n", keyexpr);
      return -1;
    }
    impl_->pubs[i].used = true;
    return i;
  }
  Serial.println("Rosie: no free publisher slots");
  return -1;
}

bool Session::createSubscription(const char* name, SampleCallback cb, void* user) {
  if (!ok_ || !impl_ || !cb) return false;
  char keyexpr[kMaxKeyLen];
  if (!resolveName(name, keyexpr, sizeof(keyexpr))) {
    Serial.printf("Rosie: bad subscriber name: %s\n", name ? name : "(null)");
    return false;
  }
  for (int i = 0; i < kMaxSubs; i++) {
    if (impl_->subs[i].used) continue;
    impl_->subs[i].cb = cb;
    impl_->subs[i].user = user;
    z_owned_closure_sample_t closure;
    z_closure_sample(&closure, sampleTrampoline, NULL, &impl_->subs[i]);
    z_view_keyexpr_t ke;
    z_view_keyexpr_from_str_unchecked(&ke, keyexpr);
    if (z_declare_subscriber(z_session_loan(&impl_->session), &impl_->subs[i].sub,
                             z_view_keyexpr_loan(&ke),
                             z_closure_sample_move(&closure), NULL) < 0) {
      Serial.printf("Rosie: declare subscriber failed: %s\n", keyexpr);
      return false;
    }
    impl_->subs[i].used = true;
    return true;
  }
  Serial.println("Rosie: no free subscriber slots");
  return false;
}

bool Session::createFleetSubscription(const char* name, SampleCallback cb, void* user) {
  if (!ok_ || !impl_ || !cb) return false;
  char keyexpr[kMaxKeyLen];
  if (!resolveFleetName(name, keyexpr, sizeof(keyexpr))) {
    Serial.printf("Rosie: bad fleet subscriber name: %s\n", name ? name : "(null)");
    return false;
  }
  for (int i = 0; i < kMaxSubs; i++) {
    if (impl_->subs[i].used) continue;
    impl_->subs[i].cb = cb;
    impl_->subs[i].user = user;
    z_owned_closure_sample_t closure;
    z_closure_sample(&closure, sampleTrampoline, NULL, &impl_->subs[i]);
    z_view_keyexpr_t ke;
    z_view_keyexpr_from_str_unchecked(&ke, keyexpr);
    if (z_declare_subscriber(z_session_loan(&impl_->session), &impl_->subs[i].sub,
                             z_view_keyexpr_loan(&ke),
                             z_closure_sample_move(&closure), NULL) < 0) {
      Serial.printf("Rosie: declare subscriber failed: %s\n", keyexpr);
      return false;
    }
    impl_->subs[i].used = true;
    return true;
  }
  Serial.println("Rosie: no free subscriber slots");
  return false;
}

bool Session::publish(int pub_id, const uint8_t* data, size_t len) {
  if (!ok_ || !impl_ || pub_id < 0 || pub_id >= kMaxPubs || !impl_->pubs[pub_id].used) {
    return false;
  }
  if (!data || len == 0) return false;
  z_owned_bytes_t payload;
  z_bytes_copy_from_buf(&payload, data, len);
  return z_publisher_put(z_publisher_loan(&impl_->pubs[pub_id].pub),
                         z_bytes_move(&payload), NULL) >= 0;
}

bool Session::publishStr(int pub_id, const char* str) {
  if (!str) return false;
  return publish(pub_id, reinterpret_cast<const uint8_t*>(str), strlen(str));
}

bool Session::publishJson(int pub_id, JsonDocument& doc) {
  if (doc["stamp"].isNull()) {
    doc["stamp"] = millis() / 1000.0;
  }
  char buf[384];
  size_t n = serializeJson(doc, buf, sizeof(buf));
  if (n == 0 || n >= sizeof(buf)) return false;
  return publishStr(pub_id, buf);
}

}  // namespace rosie
