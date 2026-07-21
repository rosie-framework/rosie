#include "rosie/wifi_softap.h"
#include <WiFi.h>

namespace rosie {

bool softAP(const char* ssid, const char* password, int channel) {
  WiFi.mode(WIFI_AP);
  bool ok = WiFi.softAP(ssid, password, channel);
  Serial.printf("Rosie SoftAP '%s' %s. IP %s\n",
                ssid, ok ? "started" : "FAILED",
                WiFi.softAPIP().toString().c_str());
  return ok;
}

}  // namespace rosie
