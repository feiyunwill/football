// 2026-09-13: a distinct native product family; legacy v2/Python v7 are not this wire.
#pragma once
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <limits>
#include <span>
#include <stdexcept>

namespace frame_sync {
class NativeMatchContract {
 public:
  static constexpr uint8_t kHello = 64, kReady = 65, kSession = 66;
  static constexpr int kHz = 50, kPhysicsSteps = 2;
  static constexpr uint32_t kPhysicsStepUs = 10000, kScenario = 1, kDuration = 15000;
  static constexpr size_t kHelloBytes = 18, kSessionBytes = 32;
  uint32_t seed = 42;
  uint16_t left = 1, right = 1;
  NativeMatchContract() = default;
  NativeMatchContract(uint32_t seed, uint16_t left, uint16_t right)
      : seed(seed), left(left), right(right) { Validate(); }
  ~NativeMatchContract() = default;
  NativeMatchContract(const NativeMatchContract&) = default;
  NativeMatchContract& operator=(const NativeMatchContract&) = default;
  NativeMatchContract(NativeMatchContract&&) = default;
  NativeMatchContract& operator=(NativeMatchContract&&) = default;
  bool operator==(const NativeMatchContract&) const = default;
  void Validate() const {
    if (left > 11 || right > 11 || left + right == 0)
      throw std::invalid_argument("Invalid native match slots");
  }
  static std::array<uint8_t, kHelloBytes> Header(uint8_t kind = kHello) {
    return {kind, 'F', 'N', 'A', 'T', 1, 0, 0, 50, 0, 50, 0, 2, 0, 0x10, 0x27, 0, 0};
  }
  static bool IsHello(std::span<const uint8_t> bytes) {
    const auto expected = Header();
    return bytes.size() == expected.size() && std::equal(bytes.begin(), bytes.end(), expected.begin());
  }
  std::array<uint8_t, kSessionBytes> Packet(uint8_t kind = kSession) const {
    Validate();
    if (kind != kSession && kind != kReady) throw std::invalid_argument("Invalid native contract packet");
    std::array<uint8_t,kSessionBytes> bytes{};
    const auto header=Header(kind); std::copy(header.begin(),header.end(),bytes.begin());
    Write(bytes,18,seed); bytes[22]=left; bytes[23]=right;
    Write(bytes,24,kScenario); Write(bytes,28,kDuration);
    return bytes;
  }
  static bool Decode(std::span<const uint8_t> bytes, uint8_t kind, NativeMatchContract& result) {
    if ((kind != kSession && kind != kReady) || bytes.size()!=kSessionBytes) return false;
    const auto header=Header(kind);
    if (!std::equal(header.begin(),header.end(),bytes.begin()) ||
        bytes[22]>11 || bytes[23]>11 || bytes[22]+bytes[23]==0 ||
        Read(bytes,24)!=kScenario || Read(bytes,28)!=kDuration) return false;
    result=NativeMatchContract(Read(bytes,18),bytes[22],bytes[23]);
    return true;
  }
 private:
  static void Write(std::span<uint8_t> bytes,size_t at,uint32_t value) {
    for (unsigned n=0;n<4;++n) bytes[at+n]=static_cast<uint8_t>(value>>(8*n));
  }
  static uint32_t Read(std::span<const uint8_t> bytes,size_t at) {
    uint32_t value=0;for(unsigned n=0;n<4;++n)value|=uint32_t(bytes[at+n])<<(8*n);return value;
  }
};

// Seal at absolute boundaries, then immediately open the following collection.
// Slow engine work skips expired wall-clock opportunities, never simulation IDs.
class NativeFrameDeadline {
 public:
  using Time=std::chrono::steady_clock::time_point;
  static constexpr auto kPeriod=std::chrono::milliseconds(20);
  NativeFrameDeadline() = delete;
  explicit NativeFrameDeadline(Time now):deadline_(now),last_(now) { Advance(now); }
  ~NativeFrameDeadline() = default;
  NativeFrameDeadline(const NativeFrameDeadline&) = delete;
  NativeFrameDeadline& operator=(const NativeFrameDeadline&) = delete;
  NativeFrameDeadline(NativeFrameDeadline&&) = delete;
  NativeFrameDeadline& operator=(NativeFrameDeadline&&) = delete;
  Time deadline() const { return deadline_; }
  void Advance(Time now) {
// 2026-09-13: reject negative artificial timestamps before signed-duration subtraction.
//     if (now<last_ || now<deadline_) throw std::invalid_argument("Native authority clock moved backwards");
    if (now.time_since_epoch()<Time::duration::zero() || now<last_ || now<deadline_)
      throw std::invalid_argument("Native authority clock moved backwards");
    const auto advance=kPeriod-(now-deadline_)%kPeriod;
    if (Time::max()-now<advance) throw std::overflow_error("Native authority clock exhausted");
// 2026-09-13: retain the absolute grid state in the deadline owner.
//     deadline_=now+advance;last_=now;
//   }
// };
    deadline_=now+advance;last_=now;
  }
 private:
  Time deadline_,last_;
};
}  // namespace frame_sync
