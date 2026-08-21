#pragma once

#ifndef Z_FEATURE_MULTI_THREAD
#define Z_FEATURE_MULTI_THREAD 0
#endif
#if Z_FEATURE_MULTI_THREAD != 1
#error "Rosie MCU Session requires -DZ_FEATURE_MULTI_THREAD=1 (zenoh-pico read/lease tasks)"
#endif

#include <Arduino.h>
#include <ArduinoJson.h>
#include <stddef.h>
#include <stdint.h>

namespace rosie {

/** Callback for JSON/text payloads (null-terminated if text). */
typedef void (*SampleCallback)(const uint8_t* data, size_t len, void* user);

/**
 * Delivery class for publishers (see docs/conventions.md).
 *
 * Mapped to zenoh-pico ``z_publisher_options_t`` at declare time.
 * Host Python uses BLOCK for Command/Critical; MCU always DROP + priority
 * so ``tick()`` never stalls on a blocking put.
 */
enum class Qos {
  Stream,   ///< Default telemetry (DROP, DATA)
  Command,  ///< One-shot cmd/goto/nav_result (DROP, INTERACTIVE_HIGH, express)
  Bulk,     ///< Large streams e.g. camera (DROP, DATA_LOW)
};

/**
 * Zenoh session for ESP32 (zenoh-pico), bound to a robot (+ optional fleet).
 *
 * Relative topic names resolve to ``{robot}/name`` or ``{fleet}/{robot}/name``.
 * A leading ``/`` makes a name absolute (leading slashes stripped for Zenoh).
 * Fleet-scoped names resolve via ``resolveFleetName`` → ``{fleet}/_fleet/name``.
 */
class Session {
 public:
  static constexpr int kMaxPubs = 14;
  static constexpr int kMaxSubs = 8;
  static constexpr size_t kMaxKeyLen = 128;

  explicit Session(const char* robot = "robot", const char* fleet = nullptr);
  ~Session();

  /** Set identity before declaring pubs/subs. ``fleet`` may be nullptr/empty. */
  void setIdentity(const char* robot, const char* fleet = nullptr);

  const char* getRobot() const { return robot_; }
  /** Empty string when no fleet. */
  const char* getFleet() const { return fleet_; }
  bool hasFleet() const { return fleet_[0] != '\0'; }

  /**
   * Resolve relative/absolute name into ``out`` (NUL-terminated).
   * Returns false if ``name`` is empty or ``out`` is too small.
   */
  bool resolveName(const char* name, char* out, size_t out_len) const;

  /**
   * Resolve fleet-scoped name → ``{fleet}/_fleet/{name}``.
   * Returns false if no fleet is set, ``name`` is empty, or ``out`` is too small.
   */
  bool resolveFleetName(const char* name, char* out, size_t out_len) const;

  /** Open session to zenohd. mode is usually "client".
   *  Optional ``user``/``password`` enable Zenoh usrpwd (password may be SHA-256 hex).
   */
  bool open(const char* connect_locator, const char* mode = "client",
            const char* user = nullptr, const char* password = nullptr);
  bool ready() const { return ok_; }

  /** Declare a publisher; ``name`` is relative or absolute. Returns id or -1. */
  int createPublisher(const char* name, Qos qos = Qos::Stream);

  /** Declare a fleet-scoped publisher (requires fleet). Returns id or -1. */
  int createFleetPublisher(const char* name, Qos qos = Qos::Stream);

  /** Declare a subscriber with raw-bytes callback. */
  bool createSubscription(const char* name, SampleCallback cb, void* user = nullptr);

  /** Declare a fleet-scoped subscriber (requires fleet). */
  bool createFleetSubscription(const char* name, SampleCallback cb, void* user = nullptr);

  bool publish(int pub_id, const uint8_t* data, size_t len);
  bool publishStr(int pub_id, const char* str);

  /**
   * Publish a JsonDocument, injecting top-level stamp if missing.
   * Mutates doc when stamp is absent.
   */
  bool publishJson(int pub_id, JsonDocument& doc);

 private:
  bool ok_ = false;
  char robot_[24] = "robot";
  char fleet_[24] = "";
  // Opaque storage sized for zenoh-pico owned types (avoid including zenoh in header).
  struct Impl;
  Impl* impl_ = nullptr;

  static void copyId_(char* dst, size_t dst_len, const char* src, const char* fallback);
  static void fillPublisherOptions_(Qos qos, void* options_out);
};

}  // namespace rosie
