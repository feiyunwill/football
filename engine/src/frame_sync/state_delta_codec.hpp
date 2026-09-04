// Copyright 2026 Google LLC & Contributors
// State Delta Codec for full game state snapshots (ms-16.4).
// Provides delta encoding for state blobs to reduce network bandwidth.
//
// Algorithm:
// 1. Baseline frame: transmit full state
// 2. Subsequent frames: compute XOR with previous state, then RLE compress
// 3. Receiver reconstructs state from baseline + delta sequence
//
// Usage:
//   StateDeltaCodec codec;
//   codec.SetBaseline(full_state);
//   std::string delta = codec.EncodeDelta(current_state);
//   // On receiver side:
//   std::string state = codec.DecodeDelta(delta);

#ifndef GFOOTBALL_FRAME_SYNC_STATE_DELTA_CODEC_HPP
#define GFOOTBALL_FRAME_SYNC_STATE_DELTA_CODEC_HPP

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace frame_sync {

/// @brief Delta codec for full game state blobs
///
/// This codec compresses state snapshots by encoding only the differences
/// from the previous frame. It uses XOR + run-length encoding for
/// efficient compression.
class StateDeltaCodec {
 public:
  StateDeltaCodec() = default;

  /// @brief Set the baseline (full) state
  /// @param full_state The complete state blob
  void SetBaseline(const std::string& full_state) {
    baseline_ = full_state;
    has_baseline_ = true;
  }

  /// @brief Set the baseline from raw bytes
  /// @param data Pointer to state data
  /// @param size Size of data in bytes
  void SetBaseline(const uint8_t* data, size_t size) {
    baseline_.assign(reinterpret_cast<const char*>(data), size);
    has_baseline_ = true;
  }

  /// @brief Encode current state as delta from previous state
  /// @param current_state The current full state
  /// @return Delta-encoded string. Empty if no baseline or error.
  [[nodiscard]] std::string EncodeDelta(const std::string& current_state) {
    if (!has_baseline_) {
      // No baseline, return full state as "delta"
      baseline_ = current_state;
      has_baseline_ = true;
      return current_state;
    }

    // Ensure sizes match
    if (current_state.size() != baseline_.size()) {
      // Size mismatch, return full state and reset baseline
      baseline_ = current_state;
      return current_state;
    }

    // Compute XOR delta
    std::string xor_delta;
    xor_delta.reserve(current_state.size());
    for (size_t i = 0; i < current_state.size(); ++i) {
      xor_delta.push_back(current_state[i] ^ baseline_[i]);
    }

    // RLE compress the XOR delta
    std::string compressed = RLECompress(xor_delta);

    // Update baseline for next frame
    baseline_ = current_state;

    // Prepend original size for decoder
    uint32_t original_size = static_cast<uint32_t>(current_state.size());
    std::string result;
    result.reserve(sizeof(uint32_t) + compressed.size());
    result.append(reinterpret_cast<const char*>(&original_size), sizeof(uint32_t));
    result.append(compressed);

    return result;
  }

  /// @brief Encode current state as delta from raw bytes
  /// @param data Pointer to current state data
  /// @param size Size of current state in bytes
  /// @return Delta-encoded string
  [[nodiscard]] std::string EncodeDelta(const uint8_t* data, size_t size) {
    return EncodeDelta(std::string(reinterpret_cast<const char*>(data), size));
  }

  /// @brief Decode delta to reconstruct state
  /// @param delta The delta-encoded string
  /// @return Reconstructed full state. Empty if error.
  [[nodiscard]] std::string DecodeDelta(const std::string& delta) {
    if (delta.size() < sizeof(uint32_t)) {
      return {};
    }

    // Extract original size
    uint32_t original_size;
    std::memcpy(&original_size, delta.data(), sizeof(uint32_t));

    // Decompress the RLE-encoded XOR delta
    std::string compressed = delta.substr(sizeof(uint32_t));
    std::string xor_delta = RLEDecompress(compressed, original_size);

    if (xor_delta.size() != original_size) {
      return {};
    }

    if (!has_baseline_ || baseline_.size() != original_size) {
      // No valid baseline, treat delta as full state
      baseline_ = xor_delta;
      has_baseline_ = true;
      return xor_delta;
    }

    // Reconstruct state by XORing with baseline
    std::string result;
    result.reserve(original_size);
    for (size_t i = 0; i < original_size; ++i) {
      result.push_back(xor_delta[i] ^ baseline_[i]);
    }

    // Update baseline for next frame
    baseline_ = result;

    return result;
  }

  /// @brief Check if baseline has been set
  [[nodiscard]] bool HasBaseline() const { return has_baseline_; }

  /// @brief Get current baseline size
  [[nodiscard]] size_t GetBaselineSize() const { return baseline_.size(); }

  /// @brief Reset codec state
  void Reset() {
    baseline_.clear();
    has_baseline_ = false;
  }

  /// @brief Get compression ratio estimate
  /// @param delta_size Size of delta in bytes
  /// @param full_size Size of full state in bytes
  /// @return Compression ratio (delta_size / full_size)
  [[nodiscard]] static float CompressionRatio(size_t delta_size, size_t full_size) {
    if (full_size == 0) return 1.0f;
    return static_cast<float>(delta_size) / full_size;
  }

  /// @brief Run-length encode a string (public for testing)
  /// @param input Input string
  /// @return RLE-encoded string
  [[nodiscard]] static std::string RLECompress(const std::string& input) {
    if (input.empty()) return {};

    std::string output;
    output.reserve(input.size());

    size_t i = 0;
    while (i < input.size()) {
      char current = input[i];
      size_t count = 1;

      // Count consecutive identical bytes
      while (i + count < input.size() && input[i + count] == current && count < 255) {
        ++count;
      }

      if (count >= 3) {
        // Encode as run: 0xFF + count + byte
        output.push_back(static_cast<char>(0xFF));
        output.push_back(static_cast<char>(count));
        output.push_back(current);
        i += count;
      } else {
        // Encode as literal bytes
        output.push_back(current);
        ++i;
      }
    }

    return output;
  }

  /// @brief Run-length decode a string (public for testing)
  /// @param input RLE-encoded string
  /// @param expected_size Expected output size
  /// @return Decoded string
  [[nodiscard]] static std::string RLEDecompress(const std::string& input, size_t expected_size) {
    std::string output;
    output.reserve(expected_size);

    size_t i = 0;
    while (i < input.size() && output.size() < expected_size) {
      if (i + 2 < input.size() && 
          static_cast<uint8_t>(input[i]) == 0xFF) {
        // Run: 0xFF + count + byte
        uint8_t count = static_cast<uint8_t>(input[i + 1]);
        char byte = input[i + 2];
        for (uint8_t j = 0; j < count && output.size() < expected_size; ++j) {
          output.push_back(byte);
        }
        i += 3;
      } else {
        // Literal byte
        output.push_back(input[i]);
        ++i;
      }
    }

    return output;
  }

 private:
  std::string baseline_;
  bool has_baseline_ = false;
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_STATE_DELTA_CODEC_HPP
