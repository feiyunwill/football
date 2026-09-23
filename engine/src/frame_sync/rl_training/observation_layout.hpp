// Copyright 2026 Google LLC & Contributors
#ifndef FOOTBALL_RL_OBSERVATION_LAYOUT_HPP
#define FOOTBALL_RL_OBSERVATION_LAYOUT_HPP

namespace football::training {
using ObservationIndex = decltype(sizeof(0));
// Ball vectors, both teams, scores, and four match-state scalars.
inline constexpr ObservationIndex kObservationFeatures =
    3 * 3 + 2 * (22 + 22 + 11 + 11) + 2 + 4;

template <ObservationIndex Columns, typename State, typename Writer>
constexpr void WriteObservation(const State& state, Writer&& write) {
  static_assert(Columns >= kObservationFeatures, "Observation columns too small");
  constexpr ObservationIndex encoded =
      sizeof(state.ball_pos) / sizeof(state.ball_pos[0]) +
      sizeof(state.ball_dir) / sizeof(state.ball_dir[0]) +
      sizeof(state.ball_rot) / sizeof(state.ball_rot[0]) +
      sizeof(state.left_pos) / sizeof(state.left_pos[0]) +
      sizeof(state.left_dir) / sizeof(state.left_dir[0]) +
      sizeof(state.left_tired) / sizeof(state.left_tired[0]) +
      sizeof(state.left_active) / sizeof(state.left_active[0]) +
      sizeof(state.right_pos) / sizeof(state.right_pos[0]) +
      sizeof(state.right_dir) / sizeof(state.right_dir[0]) +
      sizeof(state.right_tired) / sizeof(state.right_tired[0]) +
      sizeof(state.right_active) / sizeof(state.right_active[0]) +
      sizeof(state.score) / sizeof(state.score[0]) + 4;
  static_assert(encoded == kObservationFeatures, "Observation state layout changed");
  using T = typename State::T;
  ObservationIndex index = 0;
  const auto append = [&](const auto& values) {
    for (const auto value : values) write(index++, static_cast<T>(value));
  };
  append(state.ball_pos);
  append(state.ball_dir);
  append(state.ball_rot);
  append(state.left_pos);
  append(state.left_dir);
  append(state.left_tired);
  append(state.left_active);
  append(state.right_pos);
  append(state.right_dir);
  append(state.right_tired);
  append(state.right_active);
  append(state.score);
  write(index++, static_cast<T>(state.game_mode));
  write(index++, static_cast<T>(state.ball_owned_team));
  write(index++, static_cast<T>(state.ball_owned_player));
  write(index++, static_cast<T>(state.steps_left));
  while (index < Columns) write(index++, T{});
}
}  // namespace football::training
#endif
