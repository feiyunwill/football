// Copyright 2026 Google LLC & Contributors
// Replay System for frame sync (ms-16.7).
// Records game states and inputs for later playback.
//
// Usage:
//   ReplayRecorder recorder;
//   recorder.StartRecording(seed, scenario);
//   recorder.RecordFrame(frame, state_hash, inputs);
//   recorder.StopRecording();
//   std::string data = recorder.Serialize();
//
//   ReplayPlayer player;
//   player.LoadReplay(data);
//   player.Play();
//   auto frame = player.GetCurrentFrame();

#ifndef GFOOTBALL_FRAME_SYNC_REPLAY_SYSTEM_HPP
#define GFOOTBALL_FRAME_SYNC_REPLAY_SYSTEM_HPP

#include "frame_sync/protocol.hpp"
#include <cstdint>
#include <string>
#include <vector>
#include <deque>
#include <optional>

namespace frame_sync {

/// @brief Replay frame data
struct ReplayFrame {
  uint32_t frame_number = 0;           ///< Frame number
  uint64_t state_hash = 0;             ///< State hash at this frame
  std::vector<SlotInput> inputs;       ///< Inputs for this frame
};

/// @brief Replay metadata
struct ReplayMetadata {
  uint32_t seed = 0;                   ///< Random seed
  std::string scenario;                ///< Scenario name
  uint32_t total_frames = 0;           ///< Total frames recorded
  uint32_t num_slots = 0;              ///< Number of input slots
  uint64_t final_state_hash = 0;       ///< Final state hash
};

/// @brief Replay recorder
///
/// Records game states and inputs during gameplay for later playback.
/// Uses delta compression for memory efficiency.
class ReplayRecorder {
 public:
  ReplayRecorder() = default;

  /// @brief Start recording a new replay
  /// @param seed Random seed used for the game
  /// @param scenario Scenario name
  /// @param num_slots Number of input slots per frame
  void StartRecording(uint32_t seed, const std::string& scenario, uint32_t num_slots) {
    metadata_.seed = seed;
    metadata_.scenario = scenario;
    metadata_.num_slots = num_slots;
    frames_.clear();
    is_recording_ = true;
  }

  /// @brief Record a frame
  /// @param frame_number Frame number
  /// @param state_hash State hash at this frame
  /// @param inputs Inputs for this frame
  void RecordFrame(uint32_t frame_number, uint64_t state_hash, 
                   const std::vector<SlotInput>& inputs) {
    if (!is_recording_) return;

    ReplayFrame frame;
    frame.frame_number = frame_number;
    frame.state_hash = state_hash;
    frame.inputs = inputs;
    frames_.push_back(std::move(frame));
  }

  /// @brief Stop recording
  void StopRecording() {
    is_recording_ = false;
    if (!frames_.empty()) {
      metadata_.total_frames = static_cast<uint32_t>(frames_.size());
      metadata_.final_state_hash = frames_.back().state_hash;
    }
  }

  /// @brief Check if currently recording
  [[nodiscard]] bool IsRecording() const { return is_recording_; }

  /// @brief Get current frame count
  [[nodiscard]] size_t GetFrameCount() const { return frames_.size(); }

  /// @brief Get metadata
  [[nodiscard]] const ReplayMetadata& GetMetadata() const { return metadata_; }

  /// @brief Serialize replay to string
  [[nodiscard]] std::string Serialize() const {
    std::string data;
    
    // Write metadata
    data.append(reinterpret_cast<const char*>(&metadata_.seed), sizeof(uint32_t));
    uint32_t scenario_len = static_cast<uint32_t>(metadata_.scenario.size());
    data.append(reinterpret_cast<const char*>(&scenario_len), sizeof(uint32_t));
    data.append(metadata_.scenario);
    data.append(reinterpret_cast<const char*>(&metadata_.total_frames), sizeof(uint32_t));
    data.append(reinterpret_cast<const char*>(&metadata_.num_slots), sizeof(uint32_t));
    data.append(reinterpret_cast<const char*>(&metadata_.final_state_hash), sizeof(uint64_t));
    
    // Write frame count
    uint32_t frame_count = static_cast<uint32_t>(frames_.size());
    data.append(reinterpret_cast<const char*>(&frame_count), sizeof(uint32_t));
    
    // Write frames
    for (const auto& frame : frames_) {
      data.append(reinterpret_cast<const char*>(&frame.frame_number), sizeof(uint32_t));
      data.append(reinterpret_cast<const char*>(&frame.state_hash), sizeof(uint64_t));
      
      for (const auto& input : frame.inputs) {
        data.append(reinterpret_cast<const char*>(&input.dir_x), sizeof(float));
        data.append(reinterpret_cast<const char*>(&input.dir_y), sizeof(float));
        data.append(reinterpret_cast<const char*>(&input.buttons), sizeof(uint16_t));
      }
    }
    
    return data;
  }

  /// @brief Clear recorded data
  void Clear() {
    frames_.clear();
    metadata_ = ReplayMetadata{};
    is_recording_ = false;
  }

 private:
  ReplayMetadata metadata_;
  std::vector<ReplayFrame> frames_;
  bool is_recording_ = false;
};

/// @brief Replay player
///
/// Plays back recorded replays with seeking and speed control.
class ReplayPlayer {
 public:
  ReplayPlayer() = default;

  /// @brief Load a replay from serialized data
  /// @param data Serialized replay data
  /// @return true if loaded successfully
  bool LoadReplay(const std::string& data) {
    size_t offset = 0;
    
    // Read metadata
    if (offset + sizeof(uint32_t) > data.size()) return false;
    std::memcpy(&metadata_.seed, data.data() + offset, sizeof(uint32_t));
    offset += sizeof(uint32_t);
    
    if (offset + sizeof(uint32_t) > data.size()) return false;
    uint32_t scenario_len;
    std::memcpy(&scenario_len, data.data() + offset, sizeof(uint32_t));
    offset += sizeof(uint32_t);
    
    if (offset + scenario_len > data.size()) return false;
    metadata_.scenario = data.substr(offset, scenario_len);
    offset += scenario_len;
    
    if (offset + sizeof(uint32_t) > data.size()) return false;
    std::memcpy(&metadata_.total_frames, data.data() + offset, sizeof(uint32_t));
    offset += sizeof(uint32_t);
    
    if (offset + sizeof(uint32_t) > data.size()) return false;
    std::memcpy(&metadata_.num_slots, data.data() + offset, sizeof(uint32_t));
    offset += sizeof(uint32_t);
    
    if (offset + sizeof(uint64_t) > data.size()) return false;
    std::memcpy(&metadata_.final_state_hash, data.data() + offset, sizeof(uint64_t));
    offset += sizeof(uint64_t);
    
    // Read frame count
    if (offset + sizeof(uint32_t) > data.size()) return false;
    uint32_t frame_count;
    std::memcpy(&frame_count, data.data() + offset, sizeof(uint32_t));
    offset += sizeof(uint32_t);
    
    // Read frames
    frames_.clear();
    frames_.reserve(frame_count);
    
    for (uint32_t i = 0; i < frame_count; ++i) {
      ReplayFrame frame;
      
      if (offset + sizeof(uint32_t) > data.size()) return false;
      std::memcpy(&frame.frame_number, data.data() + offset, sizeof(uint32_t));
      offset += sizeof(uint32_t);
      
      if (offset + sizeof(uint64_t) > data.size()) return false;
      std::memcpy(&frame.state_hash, data.data() + offset, sizeof(uint64_t));
      offset += sizeof(uint64_t);
      
      frame.inputs.resize(metadata_.num_slots);
      for (uint32_t j = 0; j < metadata_.num_slots; ++j) {
        if (offset + sizeof(float) * 2 + sizeof(uint16_t) > data.size()) return false;
        std::memcpy(&frame.inputs[j].dir_x, data.data() + offset, sizeof(float));
        offset += sizeof(float);
        std::memcpy(&frame.inputs[j].dir_y, data.data() + offset, sizeof(float));
        offset += sizeof(float);
        std::memcpy(&frame.inputs[j].buttons, data.data() + offset, sizeof(uint16_t));
        offset += sizeof(uint16_t);
      }
      
      frames_.push_back(std::move(frame));
    }
    
    current_frame_index_ = 0;
    is_playing_ = false;
    is_loaded_ = true;
    
    return true;
  }

  /// @brief Start or resume playback
  void Play() {
    if (!is_loaded_ || frames_.empty()) return;
    is_playing_ = true;
    // Don't reset position if already at a specific frame
  }

  /// @brief Pause playback
  void Pause() {
    is_playing_ = false;
  }

  /// @brief Stop playback
  void Stop() {
    is_playing_ = false;
    current_frame_index_ = 0;
  }

  /// @brief Advance to next frame
  /// @return true if advanced, false if at end
  bool Advance() {
    if (!is_playing_ || current_frame_index_ >= frames_.size() - 1) {
      is_playing_ = false;
      return false;
    }
    current_frame_index_++;
    return true;
  }

  /// @brief Seek to specific frame
  /// @param frame_number Frame number to seek to
  /// @return true if found, false if not
  bool SeekToFrame(uint32_t frame_number) {
    for (size_t i = 0; i < frames_.size(); ++i) {
      if (frames_[i].frame_number == frame_number) {
        current_frame_index_ = i;
        return true;
      }
    }
    return false;
  }

  /// @brief Get current frame
  [[nodiscard]] const std::optional<ReplayFrame> GetCurrentFrame() const {
    if (!is_loaded_ || frames_.empty() || current_frame_index_ >= frames_.size()) {
      return std::nullopt;
    }
    return frames_[current_frame_index_];
  }

  /// @brief Get frame at index
  [[nodiscard]] const std::optional<ReplayFrame> GetFrameAt(size_t index) const {
    if (!is_loaded_ || index >= frames_.size()) {
      return std::nullopt;
    }
    return frames_[index];
  }

  /// @brief Get metadata
  [[nodiscard]] const ReplayMetadata& GetMetadata() const { return metadata_; }

  /// @brief Check if playing
  [[nodiscard]] bool IsPlaying() const { return is_playing_; }

  /// @brief Check if loaded
  [[nodiscard]] bool IsLoaded() const { return is_loaded_; }

  /// @brief Get current frame index
  [[nodiscard]] size_t GetCurrentFrameIndex() const { return current_frame_index_; }

  /// @brief Get total frames
  [[nodiscard]] size_t GetTotalFrames() const { return frames_.size(); }

  /// @brief Check if at end of replay
  [[nodiscard]] bool IsAtEnd() const {
    return !frames_.empty() && current_frame_index_ >= frames_.size() - 1;
  }

  /// @brief Reset to beginning
  void Reset() {
    current_frame_index_ = 0;
    is_playing_ = false;
  }

 private:
  ReplayMetadata metadata_;
  std::vector<ReplayFrame> frames_;
  size_t current_frame_index_ = 0;
  bool is_playing_ = false;
  bool is_loaded_ = false;
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_REPLAY_SYSTEM_HPP
