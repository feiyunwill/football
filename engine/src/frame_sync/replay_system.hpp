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
#include "frame_sync/memory_budget.hpp"
#include <algorithm>
#include <array>  // 2026-09-10: fixed-size streaming serialization scratch.
#include <bit>
#include <string_view>
#include <utility>
#include <cstdint>
#include <cstring>  // 2026-09-09: self-contained without the test PCH.
#include <string>
#include <vector>
#include <deque>
#include <optional>

namespace frame_sync {

// 2026-09-09: explicit little-endian encoding preserves existing x86 replays.
namespace replay_detail {
inline constexpr size_t kMaxScenarioBytes = 1024;
inline constexpr size_t kHeaderBytes = 28;
// 2026-09-10: share identical wire encoding between strings and bounded sinks.
// template<class Integer>
// void Write(std::string& output, Integer value) {
template<class Output, class Integer>
void Write(Output& output, Integer value) {
  for (size_t i = 0; i < sizeof(Integer); ++i)
    output.push_back(static_cast<char>((value >> (8 * i)) & 0xff));
}
template<class Integer>
bool Read(std::string_view input, size_t& offset, Integer& value) {
  if (offset > input.size() || sizeof(Integer) > input.size() - offset) return false;
  value = 0;
  for (size_t i = 0; i < sizeof(Integer); ++i)
    value |= static_cast<Integer>(static_cast<uint8_t>(input[offset++])) << (8 * i);
  return true;
}
// 2026-09-10: the sink consumes each view synchronously; no whole-file copy.
template<class Sink>
class ChunkOutput {
 public:
  explicit ChunkOutput(Sink& sink) : sink_(sink) {}
  void push_back(char byte) {
    if (used_ == buffer_.size()) Flush();
    buffer_[used_++] = byte;
  }
  void append(std::string_view text) {
    while (!text.empty()) {
      if (used_ == buffer_.size()) Flush();
      const auto count = std::min(text.size(), buffer_.size() - used_);
      std::memcpy(buffer_.data() + used_, text.data(), count);
      used_ += count;
      text.remove_prefix(count);
    }
  }
  size_t Finish() { Flush(); return total_; }
 private:
  void Flush() {
    if (!used_) return;
    sink_(std::string_view(buffer_.data(), used_));
    total_ += used_;
    used_ = 0;
  }
  Sink& sink_;
  std::array<char, 4096> buffer_{};
  size_t used_ = 0, total_ = 0;
};
}  // namespace replay_detail

enum class ReplayStopReason { None, User, Capacity, InvalidInput };

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
// 2026-09-09: the existing wire format stores complete inputs, not deltas.
// /// Uses delta compression for memory efficiency.
/// Retains complete inputs within explicit frame and byte budgets.
class ReplayRecorder {
 public:
  // 2026-09-09: bound retained replay memory and preserve committed data on failure.
  //   ReplayRecorder() = default;
  explicit ReplayRecorder(ReplayBudget budget = ReplayBudget{})
      : budget_(budget.frame_limit, budget.byte_limit) {}
  ~ReplayRecorder() = default;
  ReplayRecorder(const ReplayRecorder&) = default;
  ReplayRecorder& operator=(const ReplayRecorder& other) {
    if (this != &other) { ReplayRecorder copy(other); Swap(copy); }
    return *this;
  }
  ReplayRecorder(ReplayRecorder&& other) : ReplayRecorder() { Swap(other); }
  ReplayRecorder& operator=(ReplayRecorder&& other) {
    if (this != &other) { ReplayRecorder moved(std::move(other)); Swap(moved); }
    return *this;
  }

  /// @brief Start recording a new replay
  /// @param seed Random seed used for the game
  /// @param scenario Scenario name
  /// @param num_slots Number of input slots per frame
  // 2026-09-09: bound retained replay memory and preserve committed data on failure.
  //   void StartRecording(uint32_t seed, const std::string& scenario, uint32_t num_slots) {
  //     metadata_.seed = seed;
  //     metadata_.scenario = scenario;
  //     metadata_.num_slots = num_slots;
  //     frames_.clear();
  //     is_recording_ = true;
  //   }
  void StartRecording(uint32_t seed, const std::string& scenario, uint32_t num_slots) {
    CheckedControlledSlots(num_slots);
    if (scenario.size() > replay_detail::kMaxScenarioBytes ||
        scenario.size() > budget_.byte_limit - replay_detail::kHeaderBytes)
      throw std::length_error("Replay scenario exceeds byte budget");
    ReplayMetadata metadata{seed, scenario, 0, num_slots, 0};
    if (metadata.scenario.capacity() > budget_.byte_limit)
      throw std::length_error("Replay scenario capacity exceeds byte budget");
    std::vector<ReplayFrame>{}.swap(frames_);
    metadata_ = std::move(metadata);
    input_bytes_ = 0;
    is_recording_ = true;
    stop_reason_ = ReplayStopReason::None;
  }

  /// @brief Record a frame
  /// @param frame_number Frame number
  /// @param state_hash State hash at this frame
  /// @param inputs Inputs for this frame
  // 2026-09-09: bound retained replay memory and preserve committed data on failure.
  //   void RecordFrame(uint32_t frame_number, uint64_t state_hash,
  //                    const std::vector<SlotInput>& inputs) {
  //     if (!is_recording_) return;
  //
  //     ReplayFrame frame;
  //     frame.frame_number = frame_number;
  //     frame.state_hash = state_hash;
  //     frame.inputs = inputs;
  //     frames_.push_back(std::move(frame));
  //   }
  bool RecordFrame(uint32_t frame_number, uint64_t state_hash,
                   const std::vector<SlotInput>& inputs) {
    if (!is_recording_) return false;
    if (inputs.size() != metadata_.num_slots ||
        !std::all_of(inputs.begin(), inputs.end(), IsValidSlotInput) ||
        (!frames_.empty() && frame_number <= frames_.back().frame_number))
      return Refuse(ReplayStopReason::InvalidInput);
    if (frames_.size() == budget_.frame_limit ||
        SerializedSize(frames_.size() + 1) > budget_.byte_limit)
      return Refuse(ReplayStopReason::Capacity);
    ReplayFrame frame{frame_number, state_hash,
                      std::vector<SlotInput>(inputs.begin(), inputs.end())};
    const auto bytes = RetainedBytes(frame.inputs);
    if (!ReserveFrame(bytes)) return Refuse(ReplayStopReason::Capacity);
    frames_.push_back(std::move(frame));
    input_bytes_ += bytes;
    metadata_.total_frames = static_cast<uint32_t>(frames_.size());
    metadata_.final_state_hash = state_hash;
    if (frames_.size() == budget_.frame_limit) Refuse(ReplayStopReason::Capacity);
    return true;
  }

  /// @brief Stop recording
  // 2026-09-09: bound retained replay memory and preserve committed data on failure.
  //   void StopRecording() {
  //     is_recording_ = false;
  //     if (!frames_.empty()) {
  //       metadata_.total_frames = static_cast<uint32_t>(frames_.size());
  //       metadata_.final_state_hash = frames_.back().state_hash;
  //     }
  //   }
  void StopRecording() {
    if (is_recording_) Refuse(ReplayStopReason::User);
  }

  /// @brief Check if currently recording
  [[nodiscard]] bool IsRecording() const { return is_recording_; }

  /// @brief Get current frame count
  [[nodiscard]] size_t GetFrameCount() const { return frames_.size(); }

  /// @brief Get metadata
  [[nodiscard]] const ReplayMetadata& GetMetadata() const { return metadata_; }

  /// @brief Serialize replay to string
  // 2026-09-09: bound retained replay memory and preserve committed data on failure.
  // // 2026-09-10: stream native saves without allocating a second full replay.
//   [[nodiscard]] std::string Serialize() const {
//   //     std::string data;
//   //
//   //     // Write metadata
//   //     data.append(reinterpret_cast<const char*>(&metadata_.seed), sizeof(uint32_t));
//   //     uint32_t scenario_len = static_cast<uint32_t>(metadata_.scenario.size());
//   //     data.append(reinterpret_cast<const char*>(&scenario_len), sizeof(uint32_t));
//   //     data.append(metadata_.scenario);
//   //     data.append(reinterpret_cast<const char*>(&metadata_.total_frames), sizeof(uint32_t));
//   //     data.append(reinterpret_cast<const char*>(&metadata_.num_slots), sizeof(uint32_t));
//   //     data.append(reinterpret_cast<const char*>(&metadata_.final_state_hash), sizeof(uint64_t));
//   //
//   //     // Write frame count
//   //     uint32_t frame_count = static_cast<uint32_t>(frames_.size());
//   //     data.append(reinterpret_cast<const char*>(&frame_count), sizeof(uint32_t));
//   //
//   //     // Write frames
//   //     for (const auto& frame : frames_) {
//   //       data.append(reinterpret_cast<const char*>(&frame.frame_number), sizeof(uint32_t));
//   //       data.append(reinterpret_cast<const char*>(&frame.state_hash), sizeof(uint64_t));
//   //
//   //       for (const auto& input : frame.inputs) {
//   //         data.append(reinterpret_cast<const char*>(&input.dir_x), sizeof(float));
//   //         data.append(reinterpret_cast<const char*>(&input.dir_y), sizeof(float));
//   //         data.append(reinterpret_cast<const char*>(&input.buttons), sizeof(uint16_t));
//   //       }
//   //     }
//   //
//   //     return data;
//   //   }
//   [[nodiscard]] std::string Serialize() const {
//     if (metadata_.num_slots == 0) return {};
//     const auto bytes = SerializedSize(frames_.size());
//     if (bytes > budget_.byte_limit) throw std::length_error("Replay serialization exceeds budget");
//     std::string data;
//     data.reserve(bytes);
//     replay_detail::Write(data, metadata_.seed);
//     replay_detail::Write(data, static_cast<uint32_t>(metadata_.scenario.size()));
//     data.append(metadata_.scenario);
//     replay_detail::Write(data, metadata_.total_frames);
//     replay_detail::Write(data, metadata_.num_slots);
//     replay_detail::Write(data, metadata_.final_state_hash);
//     replay_detail::Write(data, static_cast<uint32_t>(frames_.size()));
//     for (const auto& frame : frames_) {
//       replay_detail::Write(data, frame.frame_number);
//       replay_detail::Write(data, frame.state_hash);
//       for (const auto& input : frame.inputs) {
//         replay_detail::Write(data, std::bit_cast<uint32_t>(static_cast<float>(input.dir_x)));
//         replay_detail::Write(data, std::bit_cast<uint32_t>(static_cast<float>(input.dir_y)));
//         replay_detail::Write(data, static_cast<uint16_t>(input.buttons));
//       }
//     }
//     return data;
//   }
  [[nodiscard]] std::string Serialize() const {
    if (metadata_.num_slots == 0) return {};
    const auto bytes = CheckedSerializedSize();
    std::string data;
    data.reserve(bytes);
    WriteSerialized(data);
    return data;
  }

  // The callback must consume the view before returning and must not mutate
  // this recorder. Sink exceptions propagate; the recording stays unchanged.
  template<class Sink>
  size_t SerializeTo(Sink&& sink) const {
    if (metadata_.num_slots == 0) return 0;
    CheckedSerializedSize();
    replay_detail::ChunkOutput output(sink);
    WriteSerialized(output);
    return output.Finish();
  }

  /// @brief Clear recorded data
  // 2026-09-09: bound retained replay memory and preserve committed data on failure.
  //   void Clear() {
  //     frames_.clear();
  //     metadata_ = ReplayMetadata{};
  //     is_recording_ = false;
  //   }
  void Clear() {
    std::vector<ReplayFrame>{}.swap(frames_);
    metadata_ = ReplayMetadata{};
    input_bytes_ = 0;
    is_recording_ = false;
    stop_reason_ = ReplayStopReason::None;
  }
  ReplayStopReason GetStopReason() const { return stop_reason_; }
  size_t GetRetainedBytes() const {
    return RetainedBytes(frames_) + input_bytes_ + metadata_.scenario.capacity();
  }

  // 2026-09-13: admit disk writes using the exact bounded wire size without
  // allocating or serializing a second copy of the recording.
  size_t GetSerializedBytes() const {
    return metadata_.num_slots ? CheckedSerializedSize() : 0;
  }

 private:
  size_t CheckedSerializedSize() const {
    const auto bytes = SerializedSize(frames_.size());
    if (bytes > budget_.byte_limit) throw std::length_error("Replay serialization exceeds budget");
    return bytes;
  }
  // 2026-09-10: the first extraction matched a historical commented method;
  // restore the full encoder and verify independent on-disk frame contents.
  // template<class Output>
  // void WriteSerialized(Output& data) const {
  // }
  template<class Output>
  void WriteSerialized(Output& data) const {
    replay_detail::Write(data, metadata_.seed);
    replay_detail::Write(data, static_cast<uint32_t>(metadata_.scenario.size()));
    data.append(metadata_.scenario);
    replay_detail::Write(data, metadata_.total_frames);
    replay_detail::Write(data, metadata_.num_slots);
    replay_detail::Write(data, metadata_.final_state_hash);
    replay_detail::Write(data, static_cast<uint32_t>(frames_.size()));
    for (const auto& frame : frames_) {
      replay_detail::Write(data, frame.frame_number);
      replay_detail::Write(data, frame.state_hash);
      for (const auto& input : frame.inputs) {
        replay_detail::Write(data, std::bit_cast<uint32_t>(static_cast<float>(input.dir_x)));
        replay_detail::Write(data, std::bit_cast<uint32_t>(static_cast<float>(input.dir_y)));
        replay_detail::Write(data, static_cast<uint16_t>(input.buttons));
      }
    }
  }
  size_t SerializedSize(size_t count) const {
    return replay_detail::kHeaderBytes + metadata_.scenario.size() +
           count * (12 + SLOT_INPUT_BYTES * metadata_.num_slots);
  }
  bool Refuse(ReplayStopReason reason) {
    stop_reason_ = reason;
    is_recording_ = false;
    return false;
  }
  bool ReserveFrame(size_t input_bytes) {
    const auto already = input_bytes_ + metadata_.scenario.capacity();
    if (input_bytes > budget_.byte_limit - already) return false;
    const auto room = budget_.byte_limit - already - input_bytes;
    const auto wanted = frames_.size() + 1;
    if (wanted > room / sizeof(ReplayFrame)) return false;
    if (frames_.capacity() >= wanted) return RetainedBytes(frames_) <= room;
    const auto capacity = std::min({budget_.frame_limit, room / sizeof(ReplayFrame),
                                  std::max(wanted, frames_.capacity() * 2)});
    std::vector<ReplayFrame> expanded;
    expanded.reserve(capacity);
    if (RetainedBytes(expanded) > room) return false;
    for (auto& frame : frames_) expanded.push_back(std::move(frame));
    frames_.swap(expanded);
    return true;
  }
  void Swap(ReplayRecorder& other) noexcept {
    using std::swap;
    swap(budget_, other.budget_);
    swap(metadata_, other.metadata_);
    swap(frames_, other.frames_);
    swap(input_bytes_, other.input_bytes_);
    swap(is_recording_, other.is_recording_);
    swap(stop_reason_, other.stop_reason_);
  }
  ReplayBudget budget_;
  size_t input_bytes_ = 0;
  ReplayStopReason stop_reason_ = ReplayStopReason::None;
  ReplayMetadata metadata_;
  std::vector<ReplayFrame> frames_;
  bool is_recording_ = false;
};

/// @brief Replay player
///
/// Plays back recorded replays with seeking and speed control.
class ReplayPlayer {
 public:
  // 2026-09-09: bound retained replay memory and preserve committed data on failure.
  //   ReplayPlayer() = default;
  explicit ReplayPlayer(ReplayBudget budget = ReplayBudget{})
      : budget_(budget.frame_limit, budget.byte_limit) {}
  ~ReplayPlayer() = default;
  ReplayPlayer(const ReplayPlayer&) = default;
  ReplayPlayer& operator=(const ReplayPlayer& other) {
    if (this != &other) { ReplayPlayer copy(other); Swap(copy); }
    return *this;
  }
  ReplayPlayer(ReplayPlayer&& other) : ReplayPlayer() { Swap(other); }
  ReplayPlayer& operator=(ReplayPlayer&& other) {
    if (this != &other) { ReplayPlayer moved(std::move(other)); Swap(moved); }
    return *this;
  }

  /// @brief Load a replay from serialized data
  /// @param data Serialized replay data
  /// @return true if loaded successfully
  // 2026-09-09: bound retained replay memory and preserve committed data on failure.
  //   bool LoadReplay(const std::string& data) {
  //     size_t offset = 0;
  //
  //     // Read metadata
  //     if (offset + sizeof(uint32_t) > data.size()) return false;
  //     std::memcpy(&metadata_.seed, data.data() + offset, sizeof(uint32_t));
  //     offset += sizeof(uint32_t);
  //
  //     if (offset + sizeof(uint32_t) > data.size()) return false;
  //     uint32_t scenario_len;
  //     std::memcpy(&scenario_len, data.data() + offset, sizeof(uint32_t));
  //     offset += sizeof(uint32_t);
  //
  //     if (offset + scenario_len > data.size()) return false;
  //     metadata_.scenario = data.substr(offset, scenario_len);
  //     offset += scenario_len;
  //
  //     if (offset + sizeof(uint32_t) > data.size()) return false;
  //     std::memcpy(&metadata_.total_frames, data.data() + offset, sizeof(uint32_t));
  //     offset += sizeof(uint32_t);
  //
  //     if (offset + sizeof(uint32_t) > data.size()) return false;
  //     std::memcpy(&metadata_.num_slots, data.data() + offset, sizeof(uint32_t));
  //     offset += sizeof(uint32_t);
  //
  //     if (offset + sizeof(uint64_t) > data.size()) return false;
  //     std::memcpy(&metadata_.final_state_hash, data.data() + offset, sizeof(uint64_t));
  //     offset += sizeof(uint64_t);
  //
  //     // Read frame count
  //     if (offset + sizeof(uint32_t) > data.size()) return false;
  //     uint32_t frame_count;
  //     std::memcpy(&frame_count, data.data() + offset, sizeof(uint32_t));
  //     offset += sizeof(uint32_t);
  //
  //     // Read frames
  //     frames_.clear();
  //     frames_.reserve(frame_count);
  //
  //     for (uint32_t i = 0; i < frame_count; ++i) {
  //       ReplayFrame frame;
  //
  //       if (offset + sizeof(uint32_t) > data.size()) return false;
  //       std::memcpy(&frame.frame_number, data.data() + offset, sizeof(uint32_t));
  //       offset += sizeof(uint32_t);
  //
  //       if (offset + sizeof(uint64_t) > data.size()) return false;
  //       std::memcpy(&frame.state_hash, data.data() + offset, sizeof(uint64_t));
  //       offset += sizeof(uint64_t);
  //
  //       frame.inputs.resize(metadata_.num_slots);
  //       for (uint32_t j = 0; j < metadata_.num_slots; ++j) {
  //         if (offset + sizeof(float) * 2 + sizeof(uint16_t) > data.size()) return false;
  //         std::memcpy(&frame.inputs[j].dir_x, data.data() + offset, sizeof(float));
  //         offset += sizeof(float);
  //         std::memcpy(&frame.inputs[j].dir_y, data.data() + offset, sizeof(float));
  //         offset += sizeof(float);
  //         std::memcpy(&frame.inputs[j].buttons, data.data() + offset, sizeof(uint16_t));
  //         offset += sizeof(uint16_t);
  //       }
  //
  //       frames_.push_back(std::move(frame));
  //     }
  //
  //     current_frame_index_ = 0;
  //     is_playing_ = false;
  //     is_loaded_ = true;
  //
  //     return true;
  //   }
  bool LoadReplay(const std::string& data) {
    if (data.size() > budget_.byte_limit) return false;
    size_t offset = 0;
    ReplayMetadata metadata;
    uint32_t scenario_len = 0, count = 0;
    if (!replay_detail::Read(data, offset, metadata.seed) ||
        !replay_detail::Read(data, offset, scenario_len)) return false;
    if (scenario_len > replay_detail::kMaxScenarioBytes || scenario_len > data.size() - offset)
      return false;
    const std::string_view scenario(data.data() + offset, scenario_len);
    offset += scenario_len;
    if (!replay_detail::Read(data, offset, metadata.total_frames) ||
        !replay_detail::Read(data, offset, metadata.num_slots) ||
        !replay_detail::Read(data, offset, metadata.final_state_hash) ||
        !replay_detail::Read(data, offset, count)) return false;
    if (metadata.num_slots == 0 || metadata.num_slots > kMaxControlledSlots ||
        count > budget_.frame_limit || count != metadata.total_frames) return false;
    const size_t frame_bytes = 12 + SLOT_INPUT_BYTES * metadata.num_slots;
    const size_t remaining = data.size() - offset;
    // Validate the entire declared shape before allocating frame/slot arrays.
    if (remaining / frame_bytes != count || remaining % frame_bytes != 0) return false;
    if (count > (budget_.byte_limit - scenario_len) /
                    (sizeof(ReplayFrame) + SLOT_INPUT_BYTES * metadata.num_slots)) return false;
    metadata.scenario = scenario;
    std::vector<ReplayFrame> frames;
    frames.reserve(count);
    size_t retained = RetainedBytes(frames) + metadata.scenario.capacity();
    if (retained > budget_.byte_limit) return false;
    for (uint32_t i = 0; i < count; ++i) {
      ReplayFrame frame;
      if (!replay_detail::Read(data, offset, frame.frame_number) ||
          !replay_detail::Read(data, offset, frame.state_hash)) return false;
      if (!frames.empty() && frame.frame_number <= frames.back().frame_number) return false;
      frame.inputs.resize(metadata.num_slots);
      const auto bytes = RetainedBytes(frame.inputs);
      if (bytes > budget_.byte_limit - retained) return false;
      retained += bytes;
      for (auto& input : frame.inputs) {
        uint32_t x = 0, y = 0;
        uint16_t buttons = 0;
        if (!replay_detail::Read(data, offset, x) || !replay_detail::Read(data, offset, y) ||
            !replay_detail::Read(data, offset, buttons)) return false;
        input.dir_x = std::bit_cast<float>(x);
        input.dir_y = std::bit_cast<float>(y);
        input.buttons = buttons;
        if (!IsValidSlotInput(input)) return false;
      }
      frames.push_back(std::move(frame));
    }
    if (metadata.final_state_hash != (frames.empty() ? 0 : frames.back().state_hash)) return false;
    metadata_ = std::move(metadata);
    frames_ = std::move(frames);
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

  size_t GetRetainedBytes() const {
    size_t bytes = RetainedBytes(frames_) + metadata_.scenario.capacity();
    for (const auto& frame : frames_) bytes += RetainedBytes(frame.inputs);
    return bytes;
  }

 private:
  void Swap(ReplayPlayer& other) noexcept {
    using std::swap;
    swap(budget_, other.budget_);
    swap(metadata_, other.metadata_);
    swap(frames_, other.frames_);
    swap(current_frame_index_, other.current_frame_index_);
    swap(is_playing_, other.is_playing_);
    swap(is_loaded_, other.is_loaded_);
  }
  ReplayBudget budget_;
  ReplayMetadata metadata_;
  std::vector<ReplayFrame> frames_;
  size_t current_frame_index_ = 0;
  bool is_playing_ = false;
  bool is_loaded_ = false;
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_REPLAY_SYSTEM_HPP
