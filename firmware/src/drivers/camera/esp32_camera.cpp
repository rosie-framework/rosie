#include "rosie/drivers/camera/esp32_camera.h"
#include "esp_camera.h"
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace rosie {

Esp32CameraPins esp32s3EyePins() {
  Esp32CameraPins p;
  p.pwdn = -1;
  p.reset = -1;
  p.xclk = 15;
  p.siod = 4;
  p.sioc = 5;
  p.y9 = 16;
  p.y8 = 17;
  p.y7 = 18;
  p.y6 = 12;
  p.y5 = 10;
  p.y4 = 8;
  p.y3 = 9;
  p.y2 = 11;
  p.vsync = 6;
  p.href = 7;
  p.pclk = 13;
  return p;
}

Esp32Camera::Esp32Camera(const Esp32CameraConfig& cfg) : cfg_(cfg) {
  enable_ = cfg.enable_default;
}

bool Esp32Camera::begin() {
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = cfg_.pins.y2;
  config.pin_d1 = cfg_.pins.y3;
  config.pin_d2 = cfg_.pins.y4;
  config.pin_d3 = cfg_.pins.y5;
  config.pin_d4 = cfg_.pins.y6;
  config.pin_d5 = cfg_.pins.y7;
  config.pin_d6 = cfg_.pins.y8;
  config.pin_d7 = cfg_.pins.y9;
  config.pin_xclk = cfg_.pins.xclk;
  config.pin_pclk = cfg_.pins.pclk;
  config.pin_vsync = cfg_.pins.vsync;
  config.pin_href = cfg_.pins.href;
  config.pin_sccb_sda = cfg_.pins.siod;
  config.pin_sccb_scl = cfg_.pins.sioc;
  config.pin_pwdn = cfg_.pins.pwdn;
  config.pin_reset = cfg_.pins.reset;
  config.xclk_freq_hz = 20000000;
  config.frame_size = FRAMESIZE_QVGA;
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.jpeg_quality = cfg_.jpeg_quality;
  config.fb_count = 1;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }
  sensor_t* s = esp_camera_sensor_get();
  if (s && cfg_.vflip) s->set_vflip(s, 1);
  ok_ = true;
  return true;
}

void Esp32Camera::setEnable(bool enable) { enable_ = enable; }

bool Esp32Camera::enabled() const { return enable_; }

void Esp32Camera::startPublishTask(PublishFn fn, void* user) {
  if (!ok_ || !fn) return;
  publish_fn_ = fn;
  publish_user_ = user;
  xTaskCreatePinnedToCore(publishTaskTrampoline_, "cam_pub", 8192, this,
                          /*priority=*/1, nullptr, /*core=*/0);
}

void Esp32Camera::publishTaskTrampoline_(void* arg) {
  static_cast<Esp32Camera*>(arg)->publishTask_();
}

void Esp32Camera::publishTask_() {
  const TickType_t period =
      pdMS_TO_TICKS((int)(1000.0f / (cfg_.pub_hz > 0.1f ? cfg_.pub_hz : 1.0f)));
  for (;;) {
    if (!ok_ || !enable_ || !publish_fn_) {
      vTaskDelay(period);
      continue;
    }
    if (publishing_) {
      vTaskDelay(period);
      continue;
    }
    publishing_ = true;
    camera_fb_t* fb = esp_camera_fb_get();
    if (fb) {
      publish_fn_(fb->buf, fb->len, publish_user_);
      esp_camera_fb_return(fb);
    }
    publishing_ = false;
    vTaskDelay(period);
  }
}

}  // namespace rosie
