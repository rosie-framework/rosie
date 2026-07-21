#pragma once

#include <Arduino.h>

namespace rosie {

/**
 * Start Wi-Fi SoftAP (solo-robot fallback).
 *
 * Laptop joins this network and typically runs ``rosie router`` / zenohd.
 * For multi-robot fleets, prefer a dedicated travel-router AP and join as a
 * Wi-Fi station instead — see docs/fleet-networking.md.
 */
bool softAP(const char* ssid, const char* password, int channel = 1);

}  // namespace rosie
