// 2026-10-14: bounded contiguous output for plain and four-frame observations.
#pragma once
#include <cstddef>
#include <span>
#include <stdexcept>
#include <utility>
#include <vector>

namespace football::training {
inline constexpr size_t kSimple115Features = 115;
inline constexpr size_t kFrameStackFrames = 4;
inline constexpr size_t kMaxTrainingBatchSteps = 256;
inline constexpr size_t kMaxTrainingAgents = 11;

class ObservationBuffer {
 public:
  explicit ObservationBuffer(size_t rows = 0, size_t columns = kSimple115Features)
      : columns_(columns) {
    if (columns != kSimple115Features && columns != kSimple115Features * kFrameStackFrames)
      throw std::invalid_argument("Observation width must be 115 or 460");
    resize(rows);
  }
  ~ObservationBuffer() = default;
  ObservationBuffer(const ObservationBuffer&) = default;
  ObservationBuffer& operator=(const ObservationBuffer& other) {
    if (this != &other) {
      ObservationBuffer copy(other);
      std::swap(columns_, copy.columns_);
      values_.swap(copy.values_);
    }
    return *this;
  }
  ObservationBuffer(ObservationBuffer&&) noexcept = default;
  ObservationBuffer& operator=(ObservationBuffer&&) noexcept = default;

  size_t size() const { return values_.size() / columns_; }
  size_t columns() const { return columns_; }
  std::span<float> buffer() { return values_; }
  std::span<const float> buffer() const { return values_; }
  std::span<float> operator[](size_t row) {
    check_row(row);
    return buffer().subspan(row * columns_, columns_);
  }
  std::span<const float> operator[](size_t row) const {
    check_row(row);
    return buffer().subspan(row * columns_, columns_);
  }
  std::span<const float> back() const { return (*this)[size() - 1]; }
  void resize(size_t rows) {
    if (rows > kMaxTrainingBatchSteps * kMaxTrainingAgents)
      throw std::invalid_argument("Observation row capacity exceeded");
    values_.resize(rows * columns_);
  }
  friend bool operator==(const ObservationBuffer&, const ObservationBuffer&) = default;

 private:
  void check_row(size_t row) const {
    if (row >= size()) throw std::out_of_range("Observation row out of range");
  }
  size_t columns_;
  std::vector<float> values_;
};
}  // namespace football::training
