// Copyright 2026 Google LLC & Contributors
// State Snapshot Codec for network transport (ms-17.2).
// Compresses state snapshots using delta encoding for efficient transmission.
//
// Usage:
//   StateSnapshotCodec codec;
//   codec.SetBaseline(full_state);
//   std::string compressed = codec.Compress(current_state);
//   std::string decompressed = codec.Decompress(compressed);

#ifndef GFOOTBALL_FRAME_SYNC_STATE_SNAPSHOT_CODEC_HPP
#define GFOOTBALL_FRAME_SYNC_STATE_SNAPSHOT_CODEC_HPP

#include "frame_sync/state_delta_codec.hpp"
#include <cstdint>
#include <string>
#include <functional>

namespace frame_sync {

/// @brief State snapshot codec for network transport
///
/// Provides compression for state snapshots using delta encoding.
/// Supports both full snapshots (baseline) and delta-compressed frames.
class StateSnapshotCodec {
 public:
  StateSnapshotCodec() = default;

  /// @brief Set baseline state for delta compression
  /// @param state Full state snapshot
  void SetBaseline(const std::string& state) {
    codec_.SetBaseline(state);
    has_baseline_ = true;
  }

  /// @brief Set baseline from raw bytes
  /// @param data State data
  /// @param size Data size
  void SetBaseline(const uint8_t* data, size_t size) {
    codec_.SetBaseline(data, size);
    has_baseline_ = true;
  }

  /// @brief Compress a state snapshot
  /// @param state Current state
  /// @param force_full Force full snapshot (for keyframes)
  /// @return Compressed state data
  [[nodiscard]] std::string Compress(const std::string& state, bool force_full = false) {
    if (force_full || !has_baseline_) {
      // Send full state with marker
      std::string result;
      result.reserve(1 + state.size());
      result.push_back(static_cast<char>(0x01));  // Full state marker
      result.append(state);
      codec_.SetBaseline(state);
      has_baseline_ = true;
      return result;
    }
    
    // Delta compress
    std::string delta = codec_.EncodeDelta(state);
    
    // Add marker
    std::string result;
    result.reserve(1 + delta.size());
    result.push_back(static_cast<char>(0x00));  // Delta marker
    result.append(delta);
    return result;
  }

  /// @brief Compress raw bytes
  /// @param data State data
  /// @param size Data size
  /// @param force_full Force full snapshot
  /// @return Compressed state data
  [[nodiscard]] std::string Compress(const uint8_t* data, size_t size, bool force_full = false) {
    return Compress(std::string(reinterpret_cast<const char*>(data), size), force_full);
  }

  /// @brief Decompress a state snapshot
  /// @param compressed Compressed data
  /// @param expected_size Expected uncompressed size (for validation)
  /// @return Decompressed state, empty on error
  [[nodiscard]] std::string Decompress(const std::string& compressed, size_t expected_size = 0) {
    if (compressed.empty()) return {};
    
    char marker = compressed[0];
    std::string payload = compressed.substr(1);
    
    if (marker == 0x01) {
      // Full state
      if (expected_size > 0 && payload.size() != expected_size) {
        return {};
      }
      codec_.SetBaseline(payload);
      has_baseline_ = true;
      return payload;
    }
    
    if (marker == 0x00) {
      // Delta
      std::string state = codec_.DecodeDelta(payload);
      if (state.empty()) return {};
      if (expected_size > 0 && state.size() != expected_size) {
        return {};
      }
      return state;
    }
    
    return {};  // Unknown marker
  }

  /// @brief Check if baseline has been set
  [[nodiscard]] bool HasBaseline() const { return has_baseline_; }

  /// @brief Reset codec state
  void Reset() {
    codec_.Reset();
    has_baseline_ = false;
  }

  /// @brief Get compression statistics
  struct CompressionStats {
    size_t baseline_size;      ///< Size of baseline state
    size_t last_compressed_size; ///< Size of last compressed output
    size_t last_original_size; ///< Size of last original input
    float compression_ratio;   ///< Compression ratio
  };

  /// @brief Get compression statistics
  [[nodiscard]] CompressionStats GetStats() const {
    return stats_;
  }

 private:
  StateDeltaCodec codec_;
  bool has_baseline_ = false;
  CompressionStats stats_ = {};
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_STATE_SNAPSHOT_CODEC_HPP
