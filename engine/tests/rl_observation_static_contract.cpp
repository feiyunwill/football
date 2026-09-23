// Copyright 2026 Google LLC & Contributors
// Compile-time bounds and ordering checks use the same writer as the live adapter.
#include "frame_sync/rl_training/observation_layout.hpp"
struct ObservationState {
  ObservationState() = default;
  ~ObservationState() = default;
  ObservationState(const ObservationState&) = default;
  ObservationState& operator=(const ObservationState&) = default;
  ObservationState(ObservationState&&) = default;
  ObservationState& operator=(ObservationState&&) = default;
  using T = float;
  T ball_pos[3]{}, ball_dir[3]{}, ball_rot[3]{};
#ifdef FOOTBALL_RL_BAD_STATE
  T left_pos[21]{};
#else
  T left_pos[22]{};
#endif
  T left_dir[22]{}, left_tired[11]{}, left_active[11]{};
  T right_pos[22]{}, right_dir[22]{}, right_tired[11]{}, right_active[11]{};
  T score[2]{};
  unsigned long game_mode{}, ball_owned_team{}, ball_owned_player{}, steps_left{};
};

constexpr ObservationState DistinctState() {
  ObservationState state;
  float value = 0;
  const auto fill = [&](auto& values) { for (auto& entry : values) entry = ++value; };
  fill(state.ball_pos); fill(state.ball_dir); fill(state.ball_rot);
  fill(state.left_pos); fill(state.left_dir); fill(state.left_tired); fill(state.left_active);
  fill(state.right_pos); fill(state.right_dir); fill(state.right_tired); fill(state.right_active);
  fill(state.score);
  state.game_mode = static_cast<unsigned long>(++value);
  state.ball_owned_team = static_cast<unsigned long>(++value);
  state.ball_owned_player = static_cast<unsigned long>(++value);
  state.steps_left = static_cast<unsigned long>(++value);
  return state;
}

template <football::training::ObservationIndex Columns>
constexpr bool CheckObservation(const ObservationState& state, bool distinct) {
  float output[Columns + 2]{};
  output[0] = output[Columns + 1] = -999.0f;
  bool written[Columns]{};
  bool valid = true;
  football::training::ObservationIndex calls = 0;
  football::training::WriteObservation<Columns>(state,
      [&](football::training::ObservationIndex index, float value) {
        if (index >= Columns) { valid = false; return; }
        if (written[index]) valid = false;
        written[index] = true;
        output[index + 1] = value;
        ++calls;
      });
  if (!valid || calls != Columns || output[0] != -999.0f ||
      output[Columns + 1] != -999.0f) return false;
  for (football::training::ObservationIndex index = 0; index < Columns; ++index) {
    const float expected = distinct && index < 147 ? static_cast<float>(index + 1) : 0.0f;
    if (!written[index] || output[index + 1] != expected) return false;
  }
  return true;
}
static_assert(football::training::kObservationFeatures == 147);
#ifdef FOOTBALL_RL_BAD_COLUMNS
static_assert(CheckObservation<128>(DistinctState(), true));
#else
static_assert(CheckObservation<147>(DistinctState(), true));
static_assert(CheckObservation<160>(DistinctState(), true));
static_assert(CheckObservation<147>(ObservationState{}, false));
static_assert(CheckObservation<160>(ObservationState{}, false));
#endif
