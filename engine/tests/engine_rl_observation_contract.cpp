// Copyright 2026 Google LLC & Contributors
#include "frame_sync/rl_training/observation_layout.hpp"
#include <array>
#include <cstdio>
#include <stdexcept>

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

static int assertions = 0;
static void Require(bool condition) {
  ++assertions;
  if (!condition) throw std::runtime_error("observation contract failed");
}

static ObservationState DistinctState() {
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

template <std::size_t Columns>
static void Check(const ObservationState& state, bool distinct) {
  std::array<float, Columns + 2> guarded;
  guarded.fill(-999.0f);
  std::array<bool, Columns> written{};
  std::size_t calls = 0;
  football::training::WriteObservation<Columns>(state, [&](std::size_t index, float value) {
    Require(index < Columns);
    Require(!written.at(index));
    written.at(index) = true;
    guarded.at(index + 1) = value;
    ++calls;
  });
  Require(calls == Columns);
  Require(guarded.front() == -999.0f && guarded.back() == -999.0f);
  for (std::size_t index = 0; index < Columns; ++index) {
    const float expected = distinct && index < 147 ? static_cast<float>(index + 1) : 0.0f;
    Require(written[index] && guarded[index + 1] == expected);
  }
}

int main() {
  try {
    static_assert(football::training::kObservationFeatures == 147);
#ifdef FOOTBALL_RL_BAD_COLUMNS
    Check<128>(DistinctState(), true);
#else
    Check<147>(DistinctState(), true);
    Check<160>(DistinctState(), true);
    Check<147>(ObservationState{}, false);
    Check<160>(ObservationState{}, false);
#endif
    std::printf("{\"passed\":true,\"checks\":4,\"assertions\":%d,\"skipped\":0}\n", assertions);
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "%s\n", error.what());
    return 1;
  }
}
