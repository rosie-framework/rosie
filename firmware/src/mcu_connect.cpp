#include "rosie/mcu_connect.h"

#include "rosie/mobile_base.h"
#include "rosie/session.h"
#include "rosie/wifi_softap.h"
#include "rosie/wifi_station.h"

#include <string.h>

namespace rosie {
namespace {

bool bringUpWifi_(const McuConnectConfig& cfg) {
  if (cfg.network_mode != nullptr && strcmp(cfg.network_mode, "station") == 0) {
    return wifiStation(cfg.wifi_ssid, cfg.wifi_password);
  }
  softAP(cfg.wifi_ssid, cfg.wifi_password, cfg.softap_channel);
  return true;
}

template <typename OpenFn>
bool connectWithRetries_(const McuConnectConfig& cfg, OpenFn open_zenoh) {
  if (!bringUpWifi_(cfg)) {
    Serial.println("Rosie: skipping Zenoh (Wi-Fi not connected).");
    return false;
  }

  const int retries = cfg.zenoh_retries > 0 ? cfg.zenoh_retries : 1;
  for (int attempt = 1; attempt <= retries; attempt++) {
    Serial.printf("Rosie connect attempt %d/%d ...\n", attempt, retries);
    delay(1500);
    if (open_zenoh()) return true;
    if (attempt == retries) {
      Serial.println("Rosie not connected — USB serial still works.");
      Serial.println("Start zenohd on the laptop and reset the board to retry.");
    }
  }
  return false;
}

}  // namespace

bool mcuConnect(Session& session, const McuConnectConfig& cfg) {
  return connectWithRetries_(cfg, [&]() {
    return session.open(cfg.zenoh_connect, cfg.zenoh_mode, cfg.zenoh_user,
                        cfg.zenoh_password);
  });
}

bool mcuConnect(MobileBase& base, const McuConnectConfig& cfg) {
  return connectWithRetries_(cfg, [&]() {
    return base.begin(cfg.zenoh_connect, cfg.zenoh_mode, cfg.zenoh_user,
                      cfg.zenoh_password);
  });
}

}  // namespace rosie
