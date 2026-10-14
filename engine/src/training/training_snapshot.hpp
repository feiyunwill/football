// 2026-10-14: bounded training-layer wire format; independent of a live engine.
#pragma once
#include "base/snapshot_envelope.hpp"
#include "training/observation_buffer.hpp"
#include <bit>
#include <cmath>
#include <cstdint>
#include <limits>
#include <string>
#include <string_view>
#include <vector>

namespace football::training::snapshot {
inline constexpr uint32_t kVersion = 1;
inline constexpr size_t kHeaderBytes = 16;
inline constexpr size_t kMaxIdentityBytes = 128;
inline constexpr size_t kMaxScenarioBytes = 4096;
inline constexpr size_t kMaxKernelBytes = blunted::snapshot::kMaxBytes + blunted::snapshot::kHeaderBytes;
inline constexpr size_t kMaxBytes = kMaxKernelBytes + 32768;

// Identity and scenario are canonical byte values supplied by the environment.
// History is [oldest..newest frame, player, feature], so no ring cursor leaks.
struct State {
  std::string compatibility;
  std::string scenario;
  std::string kernel;
  bool builtin_ai_action = false;
  bool fixed_positions = true;
  bool checkpoint_rewards = false;
  bool stacked = false;
  bool ready = true;
  uint32_t left_agents = 1;
  uint32_t right_agents = 0;
  uint32_t physics_steps = 10;
  int32_t previous_score_diff = 0;
  int32_t previous_game_mode = -1;
  int32_t previous_ball_owned_team = -1;
  std::vector<uint8_t> checkpoints;
  std::vector<float> history;
  friend bool operator==(const State&, const State&) = default;
};

inline void Require(bool valid, const char* message) {
  if (!valid) throw std::invalid_argument(message);
}
inline void Validate(const State& state) {
  Require(!state.compatibility.empty() && state.compatibility.size() <= kMaxIdentityBytes,
          "Invalid training compatibility identity");
  Require(!state.scenario.empty() && state.scenario.size() <= kMaxScenarioBytes,
          "Invalid training scenario identity");
  Require(state.left_agents <= kMaxTrainingAgents && state.right_agents <= kMaxTrainingAgents &&
          (state.left_agents == 0) != (state.right_agents == 0), "Invalid training agent counts");
  Require(state.physics_steps >= 1 && state.physics_steps <= 1000, "Invalid training cadence");
  Require(state.previous_game_mode >= -1 && state.previous_game_mode <= 6 &&
          state.previous_ball_owned_team >= -1 && state.previous_ball_owned_team <= 1,
          "Invalid training terminal history");
  const size_t players = state.left_agents + state.right_agents;
  Require(state.checkpoints.size() == (state.checkpoint_rewards ? players : 0),
          "Invalid checkpoint state length");
  for (auto count : state.checkpoints) Require(count <= 10, "Invalid checkpoint count");
  Require(state.history.size() == (state.stacked ? kFrameStackFrames * players * kSimple115Features : 0),
          "Invalid frame history length");
  for (float value : state.history) Require(std::isfinite(value), "Nonfinite frame history");
  // This checks the nested envelope, not the engine payload's semantic validity.
  (void)blunted::snapshot::Decode(state.kernel);
}

namespace detail {
inline void Append32(std::string& bytes, uint32_t value) {
  const size_t offset = bytes.size();
  bytes.resize(offset + 4);
  blunted::snapshot::Write32(bytes, offset, value);
}
inline void AppendBlob(std::string& bytes, std::string_view value) {
  Append32(bytes, static_cast<uint32_t>(value.size()));
  bytes.append(value);
}
class Reader {
 public:
  explicit Reader(std::string_view bytes) : bytes_(bytes) {}
  uint32_t word() {
    Require(bytes_.size() >= 4, "Truncated training snapshot field");
    const uint32_t value = blunted::snapshot::Read32(bytes_, 0);
    bytes_.remove_prefix(4);
    return value;
  }
  std::string_view take(size_t count) {
    Require(count <= bytes_.size(), "Truncated training snapshot collection");
    auto value = bytes_.substr(0, count);
    bytes_.remove_prefix(count);
    return value;
  }
  std::string blob(size_t limit) {
    const size_t count = word();
    Require(count > 0 && count <= limit, "Training snapshot collection exceeds budget");
    return std::string(take(count));
  }
  bool empty() const { return bytes_.empty(); }
 private:
  std::string_view bytes_;
};
}  // namespace detail

inline std::string Encode(const State& state) {
  static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559);
  Validate(state);
  std::string payload;
  detail::Append32(payload, uint32_t(state.builtin_ai_action) | (uint32_t(state.fixed_positions) << 1) |
      (uint32_t(state.checkpoint_rewards) << 2) | (uint32_t(state.stacked) << 3) | (uint32_t(state.ready) << 4));
  for (auto value : {state.left_agents, state.right_agents, state.physics_steps}) detail::Append32(payload, value);
  for (auto value : {state.previous_score_diff, state.previous_game_mode, state.previous_ball_owned_team})
    detail::Append32(payload, std::bit_cast<uint32_t>(value));
  detail::AppendBlob(payload, state.compatibility);
  detail::AppendBlob(payload, state.scenario);
  detail::Append32(payload, static_cast<uint32_t>(state.checkpoints.size()));
  for (auto count : state.checkpoints) payload.push_back(static_cast<char>(count));
  detail::Append32(payload, static_cast<uint32_t>(state.history.size()));
  for (float value : state.history) detail::Append32(payload, std::bit_cast<uint32_t>(value));
  detail::AppendBlob(payload, state.kernel);
  Require(payload.size() <= kMaxBytes - kHeaderBytes, "Training snapshot exceeds budget");
  std::string result(kHeaderBytes, '\0');
  result.replace(0, 4, "FTRN");
  blunted::snapshot::Write32(result, 4, kVersion);
  blunted::snapshot::Write32(result, 8, static_cast<uint32_t>(payload.size()));
  blunted::snapshot::Write32(result, 12, blunted::snapshot::Checksum(payload));
  result += payload;
  return result;
}

inline State Decode(std::string_view bytes) {
  Require(bytes.size() >= kHeaderBytes && bytes.size() <= kMaxBytes, "Invalid training snapshot size");
  Require(bytes.substr(0, 4) == "FTRN" && blunted::snapshot::Read32(bytes, 4) == kVersion,
          "Unsupported training snapshot version");
  auto payload = bytes.substr(kHeaderBytes);
  Require(payload.size() == blunted::snapshot::Read32(bytes, 8), "Training snapshot length mismatch");
  Require(blunted::snapshot::Checksum(payload) == blunted::snapshot::Read32(bytes, 12),
          "Training snapshot checksum mismatch");
  detail::Reader reader(payload);
  State state;
  const auto flags = reader.word();
  Require((flags & ~31u) == 0, "Unknown training snapshot flags");
  state.builtin_ai_action = flags & 1;
  state.fixed_positions = flags & 2;
  state.checkpoint_rewards = flags & 4;
  state.stacked = flags & 8;
  state.ready = flags & 16;
  state.left_agents = reader.word();
  state.right_agents = reader.word();
  state.physics_steps = reader.word();
  state.previous_score_diff = std::bit_cast<int32_t>(reader.word());
  state.previous_game_mode = std::bit_cast<int32_t>(reader.word());
  state.previous_ball_owned_team = std::bit_cast<int32_t>(reader.word());
  Require(state.left_agents <= kMaxTrainingAgents && state.right_agents <= kMaxTrainingAgents &&
          (state.left_agents == 0) != (state.right_agents == 0), "Invalid training agent counts");
  const size_t players = state.left_agents + state.right_agents;
  state.compatibility = reader.blob(kMaxIdentityBytes);
  state.scenario = reader.blob(kMaxScenarioBytes);
  const size_t checkpoint_count = reader.word();
  Require(checkpoint_count == (state.checkpoint_rewards ? players : 0), "Invalid checkpoint state length");
  const auto counts = reader.take(checkpoint_count);
  state.checkpoints.assign(counts.begin(), counts.end());
  const size_t history_count = reader.word();
  Require(history_count == (state.stacked ? kFrameStackFrames * players * kSimple115Features : 0),
          "Invalid frame history length");
  // Validate the byte budget before reserving/reading a collection.
  detail::Reader values(reader.take(history_count * sizeof(float)));
  state.history.reserve(history_count);
  for (size_t i = 0; i < history_count; ++i) state.history.push_back(std::bit_cast<float>(values.word()));
  state.kernel = reader.blob(kMaxKernelBytes);
  Require(reader.empty(), "Trailing training snapshot data");
  Validate(state);
  return state;
}
}  // namespace football::training::snapshot
