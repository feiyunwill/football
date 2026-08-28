// Copyright 2026 Google LLC & Contributors
// GameEnvWrapper: wrapping GameEnv as RLtools-compatible environment interface
// 1v0 scenario: 1 RL player vs AI opponent
//
// The RLtools OnPolicyRunner calls step()/observe()/reward()/terminated() as
// free functions. We route these through a global GameEnv* pointer so the
// training loop drives the real engine.

#ifndef _HPP_GAME_ENV_WRAPPER
#define _HPP_GAME_ENV_WRAPPER

#include "../../game_env.hpp"
#include "../../gamedefines.hpp"
#include "../../main.hpp"

#include <rl_tools/rl/environments/environments.h>
#include <cmath>
#include <vector>
#include <cstring>

// Global engine pointer (set in training.cpp before RLtools loop starts)
class GameEnv;
extern GameEnv* g_rl_env;

RL_TOOLS_NAMESPACE_WRAPPER_START
namespace rl_tools::rl::environments::game_env_wrapper {

// ===== Environment Parameters =====
template <typename T_T, typename T_TI = unsigned long>
struct DefaultParameters {
  using T = T_T;
  using TI = T_TI;
  static constexpr TI OBS_DIM = 128;
  static constexpr TI ACTION_DIM = 1;
  static constexpr TI N_AGENTS = 1;
  static constexpr TI EPISODE_STEP_LIMIT = 3000;  // 300s match
  static constexpr int LEFT_AGENTS = 1;
  static constexpr int RIGHT_AGENTS = 0;
  static constexpr int PHYSICS_STEPS = 10;
  // Number of RL engine actions (subset of the full 19-action set)
  static constexpr int N_ACTIONS = 19;
};

// Specification wrapper (follows Pendulum pattern)
template <typename T_T, typename T_TI, typename T_PARAMETERS = DefaultParameters<T_T, T_TI>>
struct Specification {
  using T = T_T;
  using TI = T_TI;
  using PARAMETERS = T_PARAMETERS;
};

// ===== Environment State =====
template <typename T_SPEC>
struct State {
  using T = typename T_SPEC::T;
  using TI = typename T_SPEC::TI;
  // Engine observation snapshot
  T ball_pos[3];
  T ball_dir[3];
  T ball_rot[3];
  T left_pos[22];   // 11 players x 2 coords
  T left_dir[22];
  T left_tired[11];
  T left_active[11];
  T right_pos[22];
  T right_dir[22];
  T right_tired[11];
  T right_active[11];
  T score[2];
  TI game_mode;
  TI ball_owned_team;
  TI ball_owned_player;
  TI steps_left;
  TI step_count;
  T prev_ball_dist;
  bool done;
};

}  // namespace rl_tools::rl::environments::game_env_wrapper
RL_TOOLS_NAMESPACE_WRAPPER_END

// ===== RLtools Environment definition =====
RL_TOOLS_NAMESPACE_WRAPPER_START
namespace rl_tools::rl::environments {

template <typename T_SPEC>
struct GameEnvWrapper : Environment<typename T_SPEC::T, typename T_SPEC::TI> {
  using SPEC = T_SPEC;
  using T = typename SPEC::T;
  using TI = typename SPEC::TI;
  using State = game_env_wrapper::State<game_env_wrapper::Specification<T, TI>>;
  using Parameters = typename SPEC::PARAMETERS;
  struct Observation { static constexpr TI DIM = Parameters::OBS_DIM; };
  using ObservationPrivileged = Observation;
  static constexpr TI N_AGENTS = Parameters::N_AGENTS;
  static constexpr TI ACTION_DIM = Parameters::ACTION_DIM;
  static constexpr TI EPISODE_STEP_LIMIT = Parameters::EPISODE_STEP_LIMIT;
};

}  // namespace rl_tools::rl::environments
RL_TOOLS_NAMESPACE_WRAPPER_END

// ===== RLtools operation functions =====
RL_TOOLS_NAMESPACE_WRAPPER_START
namespace rl_tools {

// ---- malloc / free / init ----
template <typename DEVICE, typename SPEC>
static void malloc(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&) {}
template <typename DEVICE, typename SPEC>
static void free(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&) {}
template <typename DEVICE, typename SPEC>
static void init(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&) {}
template <typename DEVICE, typename SPEC, typename RNG>
static void sample_initial_parameters(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&,
                                       typename SPEC::PARAMETERS&, RNG&) {}
template <typename DEVICE, typename SPEC>
static void initial_parameters(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&,
                                typename SPEC::PARAMETERS&) {}

// ---- Extract SharedInfo into State ----
template <typename STATE_SPEC>
static void extract_info_to_state(const SharedInfo& info, int step_count,
                                   rl::environments::game_env_wrapper::State<STATE_SPEC>& state) {
  using T = typename STATE_SPEC::T;
  using TI = typename STATE_SPEC::TI;

  state.ball_pos[0] = info.ball_position[0];
  state.ball_pos[1] = info.ball_position[1];
  state.ball_pos[2] = info.ball_position[2];
  state.ball_dir[0] = info.ball_direction[0];
  state.ball_dir[1] = info.ball_direction[1];
  state.ball_dir[2] = info.ball_direction[2];
  state.ball_rot[0] = info.ball_rotation[0];
  state.ball_rot[1] = info.ball_rotation[1];
  state.ball_rot[2] = info.ball_rotation[2];

  for (int i = 0; i < 11 && i < static_cast<int>(info.left_team.size()); i++) {
    state.left_pos[i * 2]     = info.left_team[i].player_position[0];
    state.left_pos[i * 2 + 1] = info.left_team[i].player_position[1];
    state.left_dir[i * 2]     = info.left_team[i].player_direction[0];
    state.left_dir[i * 2 + 1] = info.left_team[i].player_direction[1];
    state.left_tired[i]  = info.left_team[i].tired_factor;
    state.left_active[i] = info.left_team[i].is_active ? 1.0f : 0.0f;
  }
  for (int i = 0; i < 11 && i < static_cast<int>(info.right_team.size()); i++) {
    state.right_pos[i * 2]     = info.right_team[i].player_position[0];
    state.right_pos[i * 2 + 1] = info.right_team[i].player_position[1];
    state.right_dir[i * 2]     = info.right_team[i].player_direction[0];
    state.right_dir[i * 2 + 1] = info.right_team[i].player_direction[1];
    state.right_tired[i]  = info.right_team[i].tired_factor;
    state.right_active[i] = info.right_team[i].is_active ? 1.0f : 0.0f;
  }

  state.score[0] = static_cast<T>(info.left_goals);
  state.score[1] = static_cast<T>(info.right_goals);
  state.game_mode = static_cast<TI>(info.game_mode);
  state.ball_owned_team = static_cast<TI>(info.ball_owned_team);
  state.ball_owned_player = static_cast<TI>(info.ball_owned_player);
  state.steps_left = static_cast<TI>(info.step);
  state.step_count = static_cast<TI>(step_count);

  T dx = state.ball_pos[0] - state.left_pos[0];
  T dy = state.ball_pos[1] - state.left_pos[1];
  state.prev_ball_dist = std::sqrt(dx * dx + dy * dy);
  state.done = false;
}

using STATE_SPEC = rl::environments::game_env_wrapper::Specification<float, unsigned long>;
using STATE_TYPE = rl::environments::game_env_wrapper::State<STATE_SPEC>;

// ---- initial_state: reset engine + extract first observation ----
template <typename DEVICE, typename SPEC, typename RNG>
static void initial_state(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&,
                           typename SPEC::PARAMETERS&,
                           STATE_TYPE& state, RNG&) {
  // Zero-init the state as safe default
  std::memset(&state, 0, sizeof(state));
  state.prev_ball_dist = 100.0f;
  state.done = false;
  if (!g_rl_env) return;
  // The engine is already initialized and reset in init_game_env().
  // Step once to advance the match into a valid playing state,
  // then extract the observation.
  g_rl_env->step();
  SharedInfo info = g_rl_env->get_info();
  extract_info_to_state(info, 0, state);
  state.step_count = 0;
  state.done = false;
}

template <typename DEVICE, typename SPEC, typename RNG>
static void sample_initial_state(DEVICE& dev, const rl::environments::GameEnvWrapper<SPEC>& env,
                                  typename SPEC::PARAMETERS& params,
                                  STATE_TYPE& state, RNG& rng) {
  initial_state(dev, env, params, state, rng);
}

// ---- step: apply action to engine, advance one frame, extract next state ----
template <typename DEVICE, typename SPEC, typename ACTION_SPEC, typename RNG>
static float step(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&,
                   typename SPEC::PARAMETERS&,
                   const STATE_TYPE&,
                   const Matrix<ACTION_SPEC>& action,
                   STATE_TYPE& next,
                   RNG&) {
  if (!g_rl_env) {
    next.done = true;
    return 0.0f;
  }

  // Map continuous action [0,1] to discrete action id [0,18]
  float raw = rl_tools::get(action, 0, 0);
  // Clamp to [0, 1]
  raw = raw < 0.0f ? 0.0f : (raw > 1.0f ? 1.0f : raw);
  int action_id = static_cast<int>(raw * 18.999f);
  if (action_id < 0) action_id = 0;
  if (action_id > 18) action_id = 18;

  // Apply action to RL player (left team, player 0)
  g_rl_env->action(action_id, true, 0);
  // Advance engine by one frame
  g_rl_env->step();

  // Extract next observation
  SharedInfo info = g_rl_env->get_info();
  extract_info_to_state(info, next.step_count + 1, next);
  next.step_count = next.step_count + 1;

  // Check termination
  if (info.game_mode == e_GameMode_Normal) {
    // Check if match ended (score change or out of play for too long)
  }
  // Terminate if episode step limit reached
  if (next.step_count >= static_cast<typename SPEC::TI>(SPEC::PARAMETERS::EPISODE_STEP_LIMIT)) {
    next.done = true;
  }
  // Terminate if game over
  if (info.left_goals > 0 || info.right_goals > 0) {
    next.done = true;
  }

  return 1.0f;
}

// ---- reward ----
template <typename DEVICE, typename SPEC, typename ACTION_SPEC, typename RNG>
static float reward(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&,
                     typename SPEC::PARAMETERS&,
                     const STATE_TYPE& state,
                     const Matrix<ACTION_SPEC>&,
                     const STATE_TYPE& next,
                     RNG&) {
  float r = 0.0f;

  // Goal reward
  if (next.score[0] > state.score[0]) r += 10.0f;
  if (next.score[1] > state.score[1]) r -= 10.0f;

  // Possession reward
  if (next.ball_owned_team == 0) r += 0.1f;

  // Approach ball reward
  float dist_improvement = state.prev_ball_dist - next.prev_ball_dist;
  r += dist_improvement * 0.5f;

  // Small per-step penalty
  r -= 0.001f;

  return r;
}

// ---- observe: flatten State into observation vector ----
template <typename DEVICE, typename SPEC, typename OBS_SPEC, typename RNG>
static void observe(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&,
                     const typename SPEC::PARAMETERS&,
                     const STATE_TYPE& state,
                     const typename rl::environments::GameEnvWrapper<SPEC>::Observation&,
                     Matrix<OBS_SPEC>& observation, RNG&) {
  typename SPEC::TI idx = 0;
  // ball pos (3)
  for (int i = 0; i < 3; i++) rl_tools::set(observation, 0, idx++, state.ball_pos[i]);
  // ball dir (3)
  for (int i = 0; i < 3; i++) rl_tools::set(observation, 0, idx++, state.ball_dir[i]);
  // ball rot (3)
  for (int i = 0; i < 3; i++) rl_tools::set(observation, 0, idx++, state.ball_rot[i]);
  // left team pos (22)
  for (int i = 0; i < 22; i++) rl_tools::set(observation, 0, idx++, state.left_pos[i]);
  // left team dir (22)
  for (int i = 0; i < 22; i++) rl_tools::set(observation, 0, idx++, state.left_dir[i]);
  // left tired (11)
  for (int i = 0; i < 11; i++) rl_tools::set(observation, 0, idx++, state.left_tired[i]);
  // left active (11)
  for (int i = 0; i < 11; i++) rl_tools::set(observation, 0, idx++, state.left_active[i]);
  // right team pos (22)
  for (int i = 0; i < 22; i++) rl_tools::set(observation, 0, idx++, state.right_pos[i]);
  // right team dir (22)
  for (int i = 0; i < 22; i++) rl_tools::set(observation, 0, idx++, state.right_dir[i]);
  // right tired (11)
  for (int i = 0; i < 11; i++) rl_tools::set(observation, 0, idx++, state.right_tired[i]);
  // right active (11)
  for (int i = 0; i < 11; i++) rl_tools::set(observation, 0, idx++, state.right_active[i]);
  // score (2)
  rl_tools::set(observation, 0, idx++, state.score[0]);
  rl_tools::set(observation, 0, idx++, state.score[1]);
  // game_mode (1)
  rl_tools::set(observation, 0, idx++, static_cast<float>(state.game_mode));
  // ball_owned (2)
  rl_tools::set(observation, 0, idx++, static_cast<float>(state.ball_owned_team));
  rl_tools::set(observation, 0, idx++, static_cast<float>(state.ball_owned_player));
  // steps_left (1)
  rl_tools::set(observation, 0, idx++, static_cast<float>(state.steps_left));
  // Pad to 128
  while (idx < 128) rl_tools::set(observation, 0, idx++, 0.0f);
}

// ---- terminated ----
template <typename DEVICE, typename SPEC, typename RNG>
static bool terminated(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&,
                        typename SPEC::PARAMETERS&,
                        const STATE_TYPE& state, RNG&) {
  return state.done;
}

}  // namespace rl_tools
RL_TOOLS_NAMESPACE_WRAPPER_END

#endif
