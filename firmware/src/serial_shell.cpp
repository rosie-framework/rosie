#include "rosie/serial_shell.h"

namespace rosie {

SerialShell::SerialShell(MobileBase& base, const SerialShellHooks& hooks)
    : base_(base), hooks_(hooks) {}

void SerialShell::poll() {
  if (!Serial.available()) return;
  handleLine_(Serial.readStringUntil('\n'));
}

void SerialShell::handleLine_(const String& raw) {
  String line = raw;
  line.trim();
  if (line.length() == 0) return;

  if (line.equalsIgnoreCase("test")) {
    if (hooks_.motorTest) hooks_.motorTest(base_, hooks_.user);
    else Serial.println("MSG,motor test hook not set.");
    return;
  }
  if (line.equalsIgnoreCase("enc")) {
    if (hooks_.encoderMonitor) hooks_.encoderMonitor(base_, hooks_.user);
    else Serial.println("MSG,encoder monitor hook not set.");
    return;
  }
  if (line.equalsIgnoreCase("zero")) {
    base_.requestZero();
    return;
  }
  if (line.equalsIgnoreCase("imu")) {
    if (hooks_.toggleImu) hooks_.toggleImu(base_, hooks_.user);
    else {
      bool next = !base_.useImuHeading();
      base_.setUseImuHeading(next);
      Serial.printf("MSG,Heading source: %s\n", next ? "IMU gyro" : "encoders");
    }
    return;
  }
  if (line.equalsIgnoreCase("stop")) {
    base_.requestStop();
    return;
  }

  int sp = line.indexOf(' ');
  if (sp <= 0) {
    Serial.println("MSG,USB: <x> <y> | test | enc | zero | imu | stop");
    return;
  }
  float x = line.substring(0, sp).toFloat();
  float y = line.substring(sp + 1).toFloat();
  base_.requestGoto(x, y);
  Serial.printf("MSG,New target: (%.3f, %.3f) m\n", x, y);
}

}  // namespace rosie
