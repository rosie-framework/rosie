#pragma once

#include <stddef.h>

namespace rosie {

/** Fixed-window median filter for range samples (N = ROSIE_RANGE_MEDIAN_WINDOW). */
template <int N>
class MedianWindow {
 public:
  void clear() {
    count_ = 0;
    next_ = 0;
  }

  /** Push a successful sample; returns current median (partial until full). */
  float push(float sample) {
    buf_[next_] = sample;
    next_ = (next_ + 1) % N;
    if (count_ < N) count_++;
    return median();
  }

  float median() const {
    if (count_ == 0) return 0.0f;
    float tmp[N];
    for (int i = 0; i < count_; i++) tmp[i] = buf_[i];
    // Insertion sort — N is tiny (5).
    for (int i = 1; i < count_; i++) {
      float key = tmp[i];
      int j = i - 1;
      while (j >= 0 && tmp[j] > key) {
        tmp[j + 1] = tmp[j];
        j--;
      }
      tmp[j + 1] = key;
    }
    return tmp[count_ / 2];
  }

  int count() const { return count_; }

 private:
  float buf_[N] = {};
  int count_ = 0;
  int next_ = 0;
};

}  // namespace rosie
