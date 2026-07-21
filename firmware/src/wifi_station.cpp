#include "rosie/wifi_station.h"
#include <WiFi.h>

namespace rosie {

bool wifiStation(const char* ssid, const char* password, unsigned long timeout_ms) {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  Serial.printf("Rosie Wi-Fi station joining '%s' ...\n", ssid);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - start > timeout_ms) {
      Serial.println("Rosie Wi-Fi station FAILED (timeout).");
      return false;
    }
    delay(200);
  }
  Serial.printf("Rosie Wi-Fi station OK. IP %s\n", WiFi.localIP().toString().c_str());
  return true;
}

}  // namespace rosie
