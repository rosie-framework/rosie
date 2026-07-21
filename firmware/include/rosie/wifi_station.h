#pragma once

#include <Arduino.h>

namespace rosie {

/**
 * Join a Wi-Fi network as a station (fleet / dedicated AP path).
 *
 * Returns true when associated and has an IP within timeout_ms.
 */
bool wifiStation(const char* ssid, const char* password,
                 unsigned long timeout_ms = 15000);

}  // namespace rosie
