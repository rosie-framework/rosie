#pragma once

#include "rosie/mobile_base.h"

namespace rosie {

/**
 * Thin USB serial diagnostics shell for MobileBase.
 *
 * Commands: test | enc | zero | stop | imu | <x> <y>
 * ``test`` / ``enc`` need encoder read + optional motor channel hooks.
 */
struct SerialShellHooks {
  void (*motorTest)(MobileBase& base, void* user) = nullptr;
  void (*encoderMonitor)(MobileBase& base, void* user) = nullptr;
  void (*toggleImu)(MobileBase& base, void* user) = nullptr;
  void* user = nullptr;
};

class SerialShell {
 public:
  SerialShell(MobileBase& base, const SerialShellHooks& hooks = {});
  void poll();

 private:
  void handleLine_(const String& line);
  MobileBase& base_;
  SerialShellHooks hooks_;
};

}  // namespace rosie
