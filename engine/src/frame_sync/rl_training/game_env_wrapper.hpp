// Copyright 2026 Google LLC & Contributors
// GameEnvWrapper: wrapping GameEnv as RLtools-compatible environment interface
// Supports N controlled agents (single-agent or multi-agent via shared policy)

#ifndef _HPP_GAME_ENV_WRAPPER
#define _HPP_GAME_ENV_WRAPPER

#include "../../game_env.hpp"
#include "../../gamedefines.hpp"
#include "../../main.hpp"

#include <rl_tools/rl/environments/environments.h>
#include <cmath>
#include <vector>
#include <cstring>
#include <cstdio>  // 2026-08-30: printf instead of std::println

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
  static constexpr TI EPISODE_STEP_LIMIT = 1500;
  static constexpr int LEFT_AGENTS = 11;
  static constexpr int RIGHT_AGENTS = 0;
  static constexpr int PHYSICS_STEPS = 10;
  static constexpr int N_ACTIONS = 20;
  static constexpr int MIN_ACTION_ID = 0;
};

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
  T ball_pos[3];
  T ball_dir[3];
  T ball_rot[3];
  T left_pos[22];
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
  T prev_ball_to_goal_dist;
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

static SharedInfo safe_get_info() {
  SetGame(g_rl_env);
  return g_rl_env->get_info();
}

template <typename STATE_SPEC>
static void extract_info_to_state(const SharedInfo& info, int step_count,
                                   rl::environments::game_env_wrapper::State<STATE_SPEC>& state) {
  using T = typename STATE_SPEC::T;

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
  state.game_mode = static_cast<typename STATE_SPEC::TI>(info.game_mode);
  state.ball_owned_team = static_cast<typename STATE_SPEC::TI>(info.ball_owned_team);
  state.ball_owned_player = static_cast<typename STATE_SPEC::TI>(info.ball_owned_player);
  state.steps_left = static_cast<typename STATE_SPEC::TI>(info.step);
  state.step_count = static_cast<typename STATE_SPEC::TI>(step_count);

  T dx = state.ball_pos[0] - state.left_pos[0];
  T dy = state.ball_pos[1] - state.left_pos[1];
  state.prev_ball_dist = std::sqrt(dx * dx + dy * dy);

  T gx = 1.0f - state.left_pos[0];
  T gy = 0.0f - state.left_pos[1];
  state.prev_ball_to_goal_dist = std::sqrt(gx * gx + gy * gy);

  state.done = false;
}

using STATE_SPEC = rl::environments::game_env_wrapper::Specification<float, unsigned long>;
using STATE_TYPE = rl::environments::game_env_wrapper::State<STATE_SPEC>;

// ---- Action frequency tracking ----
static int g_action_counts[20] = {};
static int g_episode_count = 0;
static float g_episode_rewards[100] = {};
static int g_episode_idx = 0;
static float g_current_episode_reward = 0.0f;

// ---- Per-episode metrics ----
struct EpisodeMetrics {
  int goals_for = 0;
  int goals_against = 0;
  int possession_frames = 0;
  int total_frames = 0;
  int pass_count = 0;
  int lost_possession_count = 0;
  int shot_count = 0;
  float total_ball_dist = 0.0f;
};
static EpisodeMetrics g_current_episode_metrics;
static EpisodeMetrics g_episode_metrics_sum;
static int g_metrics_episodes = 0;

static void print_action_stats() {
  int total = 0;
  for (int i = 0; i < 20; i++) total += g_action_counts[i];
  if (total == 0) return;
  printf("\n=== Action Frequency (%d total actions) ===\n", total);
  const char* names[] = {
    "idle", "left", "top_left", "top", "top_right", "right",
    "bot_right", "bot", "bot_left", "long_pass", "high_pass",
    "short_pass", "shot", "keeper_rush", "sliding", "pressure",
    "team_press", "switch", "sprint", "dribble"
  };
  for (int i = 0; i < 20; i++) {
    if (g_action_counts[i] > 0) {
      float pct = 100.0f * g_action_counts[i] / total;
      printf("  %12s: %6d (%5.1f%%)\n", names[i], g_action_counts[i], pct);
    }
  }
  printf("\n=== Episode Returns (last %d episodes) ===\n", g_episode_idx);
  float mean = 0;
  int n = g_episode_idx < 100 ? g_episode_idx : 100;
  for (int i = 0; i < n; i++) mean += g_episode_rewards[i];
  if (n > 0) mean /= n;
  printf("  Mean return (last %d): %.3f\n", n, mean);

  if (g_metrics_episodes > 0) {
    auto& s = g_episode_metrics_sum;
    int ne = g_metrics_episodes;
    printf("\n=== Evaluation Metrics (%d episodes) ===\n", ne);
    printf("  Goals for/against:     %.1f / %.1f\n",
           static_cast<float>(s.goals_for) / ne,
           static_cast<float>(s.goals_against) / ne);
    printf("  Possession rate:       %.1f%%\n",
           s.total_frames > 0 ? 100.0f * s.possession_frames / s.total_frames : 0.0f);
    printf("  Pass success rate:     %.1f%%\n",
           (s.pass_count + s.lost_possession_count) > 0
             ? 100.0f * s.pass_count / (s.pass_count + s.lost_possession_count) : 0.0f);
    printf("  Shots per game:        %.1f\n", static_cast<float>(s.shot_count) / ne);
    printf("  Avg ball dist (p0):    %.3f\n",
           s.total_frames > 0 ? s.total_ball_dist / s.total_frames : 0.0f);
  }
}

static void print_periodic_metrics() {
  if (g_metrics_episodes == 0) return;
  auto& s = g_episode_metrics_sum;
  int ne = g_metrics_episodes;
  printf("[ep %4d] goals: %.1f/%.1f | poss: %.0f%% | pass: %.0f%% | shots: %.1f | reward: %.2f\n",
    ne,
    static_cast<float>(s.goals_for) / ne,
    static_cast<float>(s.goals_against) / ne,
    s.total_frames > 0 ? 100.0f * s.possession_frames / s.total_frames : 0.0f,
    (s.pass_count + s.lost_possession_count) > 0
      ? 100.0f * s.pass_count / (s.pass_count + s.lost_possession_count) : 0.0f,
    static_cast<float>(s.shot_count) / ne,
    g_episode_idx > 0 ? g_episode_rewards[(g_episode_idx - 1) % 100] : 0.0f);
}

template <typename DEVICE, typename SPEC, typename RNG>
static void initial_state(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&,
                           typename SPEC::PARAMETERS&,
                           STATE_TYPE& state, RNG&) {
  std::memset(&state, 0, sizeof(state));
  state.prev_ball_dist = 100.0f;
  state.prev_ball_to_goal_dist = 100.0f;
  state.done = false;
  if (!g_rl_env) return;

  auto& scenario = g_rl_env->scenario_config;
  g_rl_env->reset(scenario, false);
  g_rl_env->step();

  SharedInfo info = safe_get_info();
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

template <typename DEVICE, typename SPEC, typename ACTION_SPEC, typename RNG>
static float step(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&,
                   typename SPEC::PARAMETERS&,
                   const STATE_TYPE& state,
                   const Matrix<ACTION_SPEC>& action,
                   STATE_TYPE& next,
                   RNG&) {
  if (!g_rl_env) {
    next.done = true;
    return 0.0f;
  }

  // Map continuous [0,1] to discrete action (0-19)
  auto map_to_action = [](float raw) -> int {
    raw = raw < 0.0f ? 0.0f : (raw > 1.0f ? 1.0f : raw);
    int action_id = static_cast<int>(raw * 20.0f);
    return action_id < 0 ? 0 : (action_id > 19 ? 19 : action_id);
  };

  // Apply action ONLY to player nearest to ball
  float raw = rl_tools::get(action, 0, 0);
  int rl_action_id = map_to_action(raw);
  int nearest = 0;
  float min_dist = 1e9f;
  for (int i = 0; i < 11; i++) {
    float dx = state.ball_pos[0] - state.left_pos[i * 2];
    float dy = state.ball_pos[1] - state.left_pos[i * 2 + 1];
    float d = dx * dx + dy * dy;
    if (d < min_dist) { min_dist = d; nearest = i; }
  }
  g_rl_env->action(rl_action_id, true, nearest);
  if (rl_action_id >= 0 && rl_action_id < 20) g_action_counts[rl_action_id]++;

  g_rl_env->step();

  SharedInfo info = safe_get_info();
  extract_info_to_state(info, state.step_count + 1, next);
  next.step_count = state.step_count + 1;

  // ---- Reward signal ----
  float step_reward = 0.0f;

  // 1. Goal reward (strongest signal)
  if (next.score[0] > state.score[0]) step_reward += 10.0f;
  if (next.score[1] > state.score[1]) step_reward -= 10.0f;

  // 2. Ball possession
  if (next.ball_owned_team == 0) step_reward += 0.05f;

  // 3. Ball approach
  float ball_dist_delta = state.prev_ball_dist - next.prev_ball_dist;
  step_reward += ball_dist_delta * 0.3f;

  // 4. Goal approach
  float goal_dist_delta = state.prev_ball_to_goal_dist - next.prev_ball_to_goal_dist;
  step_reward += goal_dist_delta * 0.2f;

  // 5. Shot proximity bonus
  if (next.left_pos[0] > 0.7f) step_reward += 0.01f;

  // 6. Small per-step penalty
  step_reward -= 0.001f;

  // NEVER set done=true
  next.done = false;

  // Track metrics
  g_current_episode_metrics.total_frames++;
  if (next.score[0] > state.score[0]) g_current_episode_metrics.goals_for++;
  if (next.score[1] > state.score[1]) g_current_episode_metrics.goals_against++;
  if (next.ball_owned_team == 0) g_current_episode_metrics.possession_frames++;
  if (next.ball_owned_team == 0 && state.ball_owned_team != 0) g_current_episode_metrics.pass_count++;
  if (next.ball_owned_team != 0 && state.ball_owned_team == 0) g_current_episode_metrics.lost_possession_count++;

  // Log every 500 steps
  static int g_log_counter = 0;
  g_log_counter++;
  if (g_log_counter % 500 == 0) {
    auto& s = g_current_episode_metrics;
    if (s.total_frames > 0) {
      printf("[step %5d] goals: %d/%d | poss: %.0f%% | reward: %.2f\n",
        g_log_counter, s.goals_for, s.goals_against,
        100.0f * s.possession_frames / s.total_frames,
        g_current_episode_reward);
    }
  }

  return step_reward;
}

template <typename DEVICE, typename SPEC, typename ACTION_SPEC, typename RNG>
static float reward(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&,
                     typename SPEC::PARAMETERS&,
                     const STATE_TYPE& state,
                     const Matrix<ACTION_SPEC>&,
                     const STATE_TYPE& next,
                     RNG&) {
  float r = 0.0f;
  if (next.score[0] > state.score[0]) r += 10.0f;
  if (next.score[1] > state.score[1]) r -= 10.0f;
  if (next.ball_owned_team == 0) r += 0.05f;
  float ball_dist_delta = state.prev_ball_dist - next.prev_ball_dist;
  r += ball_dist_delta * 0.3f;
  float goal_dist_delta = state.prev_ball_to_goal_dist - next.prev_ball_to_goal_dist;
  r += goal_dist_delta * 0.2f;
  if (next.left_pos[0] > 0.7f) r += 0.01f;
  r -= 0.001f;
  return r;
}

template <typename DEVICE, typename SPEC, typename OBS_SPEC, typename RNG>
static void observe(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&,
                     const typename SPEC::PARAMETERS&,
                     const STATE_TYPE& state,
                     const typename rl::environments::GameEnvWrapper<SPEC>::Observation&,
                     Matrix<OBS_SPEC>& observation, RNG&) {
  typename SPEC::TI idx = 0;
  for (int i = 0; i < 3; i++) rl_tools::set(observation, 0, idx++, state.ball_pos[i]);
  for (int i = 0; i < 3; i++) rl_tools::set(observation, 0, idx++, state.ball_dir[i]);
  for (int i = 0; i < 3; i++) rl_tools::set(observation, 0, idx++, state.ball_rot[i]);
  for (int i = 0; i < 22; i++) rl_tools::set(observation, 0, idx++, state.left_pos[i]);
  for (int i = 0; i < 22; i++) rl_tools::set(observation, 0, idx++, state.left_dir[i]);
  for (int i = 0; i < 11; i++) rl_tools::set(observation, 0, idx++, state.left_tired[i]);
  for (int i = 0; i < 11; i++) rl_tools::set(observation, 0, idx++, state.left_active[i]);
  for (int i = 0; i < 22; i++) rl_tools::set(observation, 0, idx++, state.right_pos[i]);
  for (int i = 0; i < 22; i++) rl_tools::set(observation, 0, idx++, state.right_dir[i]);
  for (int i = 0; i < 11; i++) rl_tools::set(observation, 0, idx++, state.right_tired[i]);
  for (int i = 0; i < 11; i++) rl_tools::set(observation, 0, idx++, state.right_active[i]);
  rl_tools::set(observation, 0, idx++, state.score[0]);
  rl_tools::set(observation, 0, idx++, state.score[1]);
  rl_tools::set(observation, 0, idx++, static_cast<float>(state.game_mode));
  rl_tools::set(observation, 0, idx++, static_cast<float>(state.ball_owned_team));
  rl_tools::set(observation, 0, idx++, static_cast<float>(state.ball_owned_player));
  rl_tools::set(observation, 0, idx++, static_cast<float>(state.steps_left));
  while (idx < 128) rl_tools::set(observation, 0, idx++, 0.0f);
}

template <typename DEVICE, typename SPEC, typename RNG>
static bool terminated(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&,
                        typename SPEC::PARAMETERS&,
                        const STATE_TYPE& state, RNG&) {
  return state.done;
}

}  // namespace rl_tools
RL_TOOLS_NAMESPACE_WRAPPER_END

#endif
