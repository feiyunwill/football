// Copyright 2026 Google LLC & Contributors
// Deterministic PRNG for frame sync (ms-16.2).
// Provides a cross-platform deterministic pseudo-random number generator
// using the xorshift128+ algorithm for guaranteed reproducibility.
//
// Usage:
//   DeterministicPRNG rng(seed);
//   uint64_t value = rng.next();
//   float f = rng.next_float();  // [0.0, 1.0)
//   int r = rng.range(1, 10);    // [1, 10]

#ifndef GFOOTBALL_FRAME_SYNC_DETERMINISTIC_PRNG_HPP
#define GFOOTBALL_FRAME_SYNC_DETERMINISTIC_PRNG_HPP

#include <cstdint>
#include <limits>

namespace frame_sync {

/// @brief Cross-platform deterministic PRNG using xorshift128+
///
/// This PRNG is designed for frame sync games where reproducibility
/// across different platforms is critical. It produces identical
/// sequences given the same seed, regardless of platform.
///
/// Algorithm: xorshift128+ (public domain, by Sebastiano Vigna)
/// Period: 2^128 - 1
/// Speed: ~1 cycle per byte on modern x86-64
class DeterministicPRNG {
 public:
  /// @brief Construct with a 64-bit seed
  /// @param seed The seed value. Same seed always produces same sequence.
  explicit DeterministicPRNG(uint64_t seed) {
    // SplitMix64 to initialize state from a single seed
    // This ensures good distribution even for similar seeds
    uint64_t z = (seed + 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    state_[0] = z ^ (z >> 31);
    
    z = (state_[0] + 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    state_[1] = z ^ (z >> 31);
    
    // Ensure state is not zero (xorshift128+ requires non-zero state)
    if (state_[0] == 0 && state_[1] == 0) {
      state_[0] = 0x123456789ABCDEF0ULL;
      state_[1] = 0xFEDCBA9876543210ULL;
    }
  }

  /// @brief Generate next 64-bit random value
  /// @return Random 64-bit unsigned integer
  [[nodiscard]] uint64_t next() {
    uint64_t s1 = state_[0];
    const uint64_t s0 = state_[1];
    const uint64_t result = s0 + s1;
    state_[0] = s0;
    s1 ^= s1 << 23;
    state_[1] = s1 ^ s0 ^ (s0 >> 18) ^ (s1 >> 5);
    return result;
  }

  /// @brief Generate next 32-bit random value
  /// @return Random 32-bit unsigned integer
  [[nodiscard]] uint32_t next_uint32() {
    return static_cast<uint32_t>(next() >> 32);
  }

  /// @brief Generate random float in range [0.0, 1.0)
  /// @return Random float uniformly distributed in [0.0, 1.0)
  [[nodiscard]] float next_float() {
    // Use 23 bits for float mantissa to avoid precision issues
    return static_cast<float>(next() >> 41) * 
           (1.0f / static_cast<float>(1ULL << 23));
  }

  /// @brief Generate random double in range [0.0, 1.0)
  /// @return Random double uniformly distributed in [0.0, 1.0)
  [[nodiscard]] double next_double() {
    // Use 52 bits for double mantissa
    return static_cast<double>(next() >> 12) * 
           (1.0 / static_cast<double>(1ULL << 52));
  }

  /// @brief Generate random integer in range [min, max] (inclusive)
  /// @param min Minimum value (inclusive)
  /// @param max Maximum value (inclusive)
  /// @return Random integer uniformly distributed in [min, max]
  [[nodiscard]] int range(int min, int max) {
    if (min >= max) return min;
    uint32_t range = static_cast<uint32_t>(max - min + 1);
    return min + static_cast<int>(next_uint32() % range);
  }

  /// @brief Generate random float in range [min, max)
  /// @param min Minimum value (inclusive)
  /// @param max Maximum value (exclusive)
  /// @return Random float uniformly distributed in [min, max)
  [[nodiscard]] float range_float(float min, float max) {
    return min + next_float() * (max - min);
  }

  /// @brief Skip forward in the sequence (for parallel generation)
  /// @param steps Number of steps to skip
  void skip(uint64_t steps) {
    for (uint64_t i = 0; i < steps; ++i) {
      next();
    }
  }

  /// @brief Get the current state for serialization
  /// @return Array of two uint64_t values representing the state
  [[nodiscard]] const uint64_t* state() const { return state_; }

  /// @brief Restore state from serialization
  /// @param s Array of two uint64_t values
  void set_state(const uint64_t* s) {
    state_[0] = s[0];
    state_[1] = s[1];
  }

  /// @brief Get minimum possible value
  [[nodiscard]] static constexpr uint64_t min() { return 0; }

  /// @brief Get maximum possible value
  [[nodiscard]] static constexpr uint64_t max() { return std::numeric_limits<uint64_t>::max(); }

 private:
  uint64_t state_[2];
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_DETERMINISTIC_PRNG_HPP
