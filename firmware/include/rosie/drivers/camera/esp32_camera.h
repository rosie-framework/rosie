#pragma once

#include <Arduino.h>
#include <stddef.h>
#include <stdint.h>

namespace rosie {

/** DVP pin map for ESP32 camera (esp32s3_eye / Freenove clones). */
struct Esp32CameraPins {
  int pwdn = -1;
  int reset = -1;
  int xclk = 15;
  int siod = 4;
  int sioc = 5;
  int y9 = 16;
  int y8 = 17;
  int y7 = 18;
  int y6 = 12;
  int y5 = 10;
  int y4 = 8;
  int y3 = 9;
  int y2 = 11;
  int vsync = 6;
  int href = 7;
  int pclk = 13;
};

/** Built-in preset: ESP32-S3-EYE DVP pinout (also Freenove ESP32-S3 CAM). */
Esp32CameraPins esp32s3EyePins();

struct Esp32CameraConfig {
  Esp32CameraPins pins = esp32s3EyePins();
  int jpeg_quality = 18;
  float pub_hz = 2.0f;
  bool enable_default = true;
  bool vflip = true;
};

/**
 * ESP32 esp_camera JPEG capture.
 *
 * Optional FreeRTOS publish task calls a user callback with JPEG bytes.
 */
class Esp32Camera {
 public:
  using PublishFn = bool (*)(const uint8_t* data, size_t len, void* user);

  explicit Esp32Camera(const Esp32CameraConfig& cfg = {});

  bool begin();
  void setEnable(bool enable);
  bool enabled() const;
  bool ok() const { return ok_; }
  float pubHz() const { return cfg_.pub_hz; }

  /** Start background JPEG publish task (no-op if begin() failed). */
  void startPublishTask(PublishFn fn, void* user = nullptr);

 private:
  Esp32CameraConfig cfg_;
  bool ok_ = false;
  volatile bool enable_ = true;
  volatile bool publishing_ = false;
  PublishFn publish_fn_ = nullptr;
  void* publish_user_ = nullptr;

  static void publishTaskTrampoline_(void* arg);
  void publishTask_();
};

}  // namespace rosie
