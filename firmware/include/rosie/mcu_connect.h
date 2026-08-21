#pragma once

/**
 * Shared MCU Wi‑Fi + Zenoh bring-up (SoftAP or station, then Session / MobileBase).
 *
 * DiffDriveStack and future MCU assemblies (Ackermann, drone, …) call this
 * instead of inlining station/SoftAP + retry loops. Primitives remain
 * ``wifi_station`` / ``wifi_softap``; this only orchestrates them.
 */

namespace rosie {

class Session;
class MobileBase;

struct McuConnectConfig {
  const char* network_mode;  ///< ``"station"`` → wifiStation; else softAP
  const char* wifi_ssid;
  const char* wifi_password;
  int softap_channel = 1;
  const char* zenoh_connect;
  const char* zenoh_mode = "client";
  const char* zenoh_user = nullptr;
  const char* zenoh_password = nullptr;
  int zenoh_retries = 10;
};

/** Wi‑Fi then retry ``Session::open``. Returns true if the session opened. */
bool mcuConnect(Session& session, const McuConnectConfig& cfg);

/**
 * Wi‑Fi then retry ``MobileBase::begin`` (Session + MobileBase topics).
 * Returns true if ``begin`` succeeded.
 */
bool mcuConnect(MobileBase& base, const McuConnectConfig& cfg);

}  // namespace rosie
