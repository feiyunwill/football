// Copyright 2026 Google LLC & Contributors
// GameEnvWrapper: wrapping GameEnv as RLtools-compatible environment interface
// Supports N controlled agents (single-agent or multi-agent via shared policy)
//
// Phase 1 (2026-08-28): 1v0 single-agent baseline
// Phase 2 (2026-08-28): N-agent shared policy (11v11 left team)

#ifndef _HPP_GAME_ENV_WRAPPER
#define _HPP_GAME_ENV_WRAPPER

#include "../../game_env.hpp"
#include "../../gamedefines.hpp"
#include "../../main.hpp"

#include <rl_tools/rl/environments/environments.h>
#include <cmath>
#include <vector>
#include <cstring>
#include <print>

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
  static constexpr TI N_AGENTS = 1;     // single shared policy for all 11 players
  static constexpr TI EPISODE_STEP_LIMIT = 1500;  // 150s match (faster episodes)
  static constexpr int LEFT_AGENTS = 11;  // all 11 left players controlled
  static constexpr int RIGHT_AGENTS = 0;  // right team uses built-in AI
  static constexpr int PHYSICS_STEPS = 10;
  static constexpr int N_ACTIONS = 20;  // 0=idle, 1-8=dir, 9-12=pass/shot, 13-19=tactical/dribble
  // Idle action suppression: minimum action id to avoid idle-dominant policy
  static constexpr int MIN_ACTION_ID = 0;
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

// ---- Safe get_info wrapper ----
static SharedInfo safe_get_info() {
  SetGame(g_rl_env);
  return g_rl_env->get_info();
}

// ---- Map continuous [0,1] to discrete football action id ----
// Actions: 0=idle, 1-8=directions, 9=long_pass, 10=high_pass, 11=short_pass,
//          12=shot, 13=keeper_rush, 14=sliding, 15=pressure, 16=team_pressure,
//          17=switch, 18=sprint, 19=dribble
// We map: [0, 0.3) -> direction (1-8), [0.3, 0.6) -> pass/shot (9-12),
//          [0.6, 0.8) -> tactical (13-16), [0.8, 1.0) -> sprint/dribble (17-19)

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

  // Distance to ball
  T dx = state.ball_pos[0] - state.left_pos[0];
  T dy = state.ball_pos[1] - state.left_pos[1];
  state.prev_ball_dist = std::sqrt(dx * dx + dy * dy);

  // Distance to opponent goal (x=1.0 is right goal)
  T gx = 1.0f - state.left_pos[0];
  T gy = 0.0f - state.left_pos[1];
  state.prev_ball_to_goal_dist = std::sqrt(gx * gx + gy * gy);

  state.done = false;
}

using STATE_SPEC = rl::environments::game_env_wrapper::Specification<float, unsigned long>;
using STATE_TYPE = rl::environments::game_env_wrapper::State<STATE_SPEC>;

// ---- Action frequency tracking (for training diagnostics) ----
static int g_action_counts[20] = {};
static int g_episode_count = 0;
static float g_episode_rewards[100] = {};
static int g_episode_idx = 0;
static float g_current_episode_reward = 0.0f;

// ---- Per-episode metrics for evaluation ----
struct EpisodeMetrics {
  int goals_for = 0;
  int goals_against = 0;
  int possession_frames = 0;    // frames where left team has ball
  int total_frames = 0;
  int pass_count = 0;           // ball ownership changes to left team
  int lost_possession_count = 0;
  int shot_count = 0;           // actions 9-12 (pass/shot family)
  float total_ball_dist = 0.0f; // sum of ball distances from player 0
};
static EpisodeMetrics g_current_episode_metrics;
static EpisodeMetrics g_episode_metrics_sum;
static int g_metrics_episodes = 0;

static void print_action_stats() {
  int total = 0;
  for (int i = 0; i < 20; i++) total += g_action_counts[i];
  if (total == 0) return;
  std::println("\n=== Action Frequency ({} total actions) ===", total);
  const char* names[] = {
    "idle", "left", "top_left", "top", "top_right", "right",
    "bot_right", "bot", "bot_left", "long_pass", "high_pass",
    "short_pass", "shot", "keeper_rush", "sliding", "pressure",
    "team_press", "switch", "sprint", "dribble"
  };
  for (int i = 0; i < 20; i++) {
    if (g_action_counts[i] > 0) {
      float pct = 100.0f * g_action_counts[i] / total;
      std::println("  {:12s}: {:6d} ({:5.1f}%)", names[i], g_action_counts[i], pct);
    }
  }
  std::println("\n=== Episode Returns (last {} episodes) ===", g_episode_idx);
  float mean = 0;
  int n = g_episode_idx < 100 ? g_episode_idx : 100;
  for (int i = 0; i < n; i++) mean += g_episode_rewards[i];
  if (n > 0) mean /= n;
  std::println("  Mean return (last {}): {:.3f}", n, mean);

  // Print evaluation metrics
  if (g_metrics_episodes > 0) {
    auto& s = g_episode_metrics_sum;
    int ne = g_metrics_episodes;
    std::println("\n=== Evaluation Metrics ({} episodes) ===", ne);
    std::println("  Goals for/against:     {:.1f} / {:.1f}",
                 static_cast<float>(s.goals_for) / ne,
                 static_cast<float>(s.goals_against) / ne);
    std::println("  Possession rate:       {:.1f}%",
                 s.total_frames > 0 ? 100.0f * s.possession_frames / s.total_frames : 0.0f);
    std::println("  Pass success rate:     {:.1f}%",
                 (s.pass_count + s.lost_possession_count) > 0
                   ? 100.0f * s.pass_count / (s.pass_count + s.lost_possession_count) : 0.0f);
    std::println("  Shots per game:        {:.1f}", static_cast<float>(s.shot_count) / ne);
    std::println("  Avg ball dist (p0):    {:.3f}",
                 s.total_frames > 0 ? s.total_ball_dist / s.total_frames : 0.0f);
  }
}

// ---- initial_state: reset engine + extract first observation ----
template <typename DEVICE, typename SPEC, typename RNG>
static void initial_state(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&,
                           typename SPEC::PARAMETERS&,
                           STATE_TYPE& state, RNG&) {
  std::memset(&state, 0, sizeof(state));
  state.prev_ball_dist = 100.0f;
  state.prev_ball_to_goal_dist = 100.0f;
  state.done = false;
  if (!g_rl_env) return;

  // Reset the game engine for a new episode
  auto& scenario = g_rl_env->scenario_config;
  g_rl_env->reset(scenario, false);

  // Step once to advance the match into a valid playing state
  g_rl_env->step();

  // Extract observation (with SetGame safety)
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

// ---- step: apply action, advance engine, extract next state ----
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

  // Map continuous [0,1] to discrete football action id (0-19)
  auto map_to_action = [](float raw) -> int {
    raw = raw < 0.0f ? 0.0f : (raw > 1.0f ? 1.0f : raw);
    int action_id;
    if (raw < 0.3f) {
      action_id = 1 + static_cast<int>(raw / 0.3f * 8.0f);  // directions 1-8
    } else if (raw < 0.55f) {
      action_id = 9 + static_cast<int>((raw - 0.3f) / 0.25f * 4.0f);  // pass/shot 9-12
    } else if (raw < 0.75f) {
      action_id = 13 + static_cast<int>((raw - 0.55f) / 0.2f * 5.0f);  // tactical 13-17
    } else {
      action_id = 18 + static_cast<int>((raw - 0.75f) / 0.25f * 2.0f);  // sprint/dribble 18-19
    }
    return action_id < 0 ? 0 : (action_id > 19 ? 19 : action_id);
  };

  // Single shared policy output — apply same action to all 11 players
  // Each player uses the same action but the engine's built-in AI
  // provides role-specific behavior (GK stays in goal, etc.)
  float raw = rl_tools::get(action, 0, 0);
  int shared_action_id = map_to_action(raw);
  constexpr int N_LEFT = 11;
  for (int i = 0; i < N_LEFT; i++) {
    g_rl_env->action(shared_action_id, true, i);
  }
  if (shared_action_id >= 0 && shared_action_id < 20) g_action_counts[shared_action_id]++;

  // Advance engine by one env step
  g_rl_env->step();

  // Extract next observation
  SharedInfo info = safe_get_info();
  extract_info_to_state(info, next.step_count + 1, next);
  next.step_count = next.step_count + 1;

  // ---- Rich reward signal ----
  float step_reward = 0.0f;

  // 1. Goal reward (strongest signal)
  if (next.score[0] > state.score[0]) step_reward += 10.0f;
  if (next.score[1] > state.score[1]) step_reward -= 10.0f;

  // 2. Ball possession continuity
  if (next.ball_owned_team == 0 && state.ball_owned_team == 0) {
    step_reward += 0.03f;  // sustained possession
  } else if (next.ball_owned_team == 0 && state.ball_owned_team != 0) {
    step_reward += 0.08f;  // interception / regain possession
  } else if (next.ball_owned_team != 0 && state.ball_owned_team == 0) {
    step_reward -= 0.02f;  // lost possession
  }

  // 3. Ball approach (closer to ball = easier to control)
  float ball_dist_delta = state.prev_ball_dist - next.prev_ball_dist;
  step_reward += ball_dist_delta * 0.15f;

  // 4. Goal approach (progressive play toward opponent goal at x=+1)
  float goal_dist_delta = state.prev_ball_to_goal_dist - next.prev_ball_to_goal_dist;
  step_reward += goal_dist_delta * 0.2f;

  // 5. Ball velocity toward goal (ball moving in the right direction)
  if (next.ball_owned_team == 0) {
    // Ball direction x-component: positive = toward opponent goal
    float ball_dx = next.ball_dir[0];
    step_reward += ball_dx * 0.05f;
  }

  // 6. Shot proximity bonus (close to goal + has ball)
  if (next.ball_owned_team == 0 && next.left_pos[0] > 0.7f) {
    step_reward += 0.02f;
  }

  // 7. Team spread (encourage players to spread out, not cluster)
  float spread_bonus = 0.0f;
  for (int i = 1; i < 11; i++) {
    float dx = next.left_pos[i * 2] - next.left_pos[0];
    float dy = next.left_pos[i * 2 + 1] - next.left_pos[1];
    float dist = std::sqrt(dx * dx + dy * dy);
    if (dist > 0.05f && dist < 0.8f) spread_bonus += 0.002f;
  }
  step_reward += spread_bonus;

  // 8. Small per-step penalty (encourage fast play)
  step_reward -= 0.001f;

  g_current_episode_reward += step_reward;

  // ---- Track evaluation metrics ----
  g_current_episode_metrics.total_frames++;
  if (next.score[0] > state.score[0]) g_current_episode_metrics.goals_for++;
  if (next.score[1] > state.score[1]) g_current_episode_metrics.goals_against++;
  if (next.ball_owned_team == 0) g_current_episode_metrics.possession_frames++;
  if (next.ball_owned_team == 0 && state.ball_owned_team != 0) g_current_episode_metrics.pass_count++;
  if (next.ball_owned_team != 0 && state.ball_owned_team == 0) g_current_episode_metrics.lost_possession_count++;
  if (shared_action_id >= 9 && shared_action_id <= 12) g_current_episode_metrics.shot_count++;
  g_current_episode_metrics.total_ball_dist += next.prev_ball_dist;

  // Termination: only on episode step limit (let agent play full episodes)
  if (next.step_count >= static_cast<typename SPEC::TI>(SPEC::PARAMETERS::EPISODE_STEP_LIMIT)) {
    next.done = true;
  }

  // Track episode return + accumulate metrics
  if (next.done) {
    g_episode_rewards[g_episode_idx % 100] = g_current_episode_reward;
    g_episode_idx++;
    g_episode_count++;
    g_current_episode_reward = 0.0f;
    // Accumulate metrics for averaging
    g_episode_metrics_sum.goals_for += g_current_episode_metrics.goals_for;
    g_episode_metrics_sum.goals_against += g_current_episode_metrics.goals_against;
    g_episode_metrics_sum.possession_frames += g_current_episode_metrics.possession_frames;
    g_episode_metrics_sum.total_frames += g_current_episode_metrics.total_frames;
    g_episode_metrics_sum.pass_count += g_current_episode_metrics.pass_count;
    g_episode_metrics_sum.lost_possession_count += g_current_episode_metrics.lost_possession_count;
    g_episode_metrics_sum.shot_count += g_current_episode_metrics.shot_count;
    g_episode_metrics_sum.total_ball_dist += g_current_episode_metrics.total_ball_dist;
    g_metrics_episodes++;
    g_current_episode_metrics = {};
  }

  return 1.0f;
}

// ---- reward: shaped reward with ball approach + goal + possession ----
template <typename DEVICE, typename SPEC, typename ACTION_SPEC, typename RNG>
static float reward(DEVICE&, const rl::environments::GameEnvWrapper<SPEC>&,
                     typename SPEC::PARAMETERS&,
                     const STATE_TYPE& state,
                     const Matrix<ACTION_SPEC>&,
                     const STATE_TYPE& next,
                     RNG&) {
  float r = 0.0f;

  // 1. Goal reward (strongest signal)
  if (next.score[0] > state.score[0]) r += 10.0f;
  if (next.score[1] > state.score[1]) r -= 10.0f;

  // 2. Ball possession reward (encourage keeping the ball)
  if (next.ball_owned_team == 0) r += 0.05f;

  // 3. Ball approach reward (shaping: move toward ball)
  float ball_dist_delta = state.prev_ball_dist - next.prev_ball_dist;
  r += ball_dist_delta * 0.3f;

  // 4. Goal approach reward (shaping: move toward opponent goal at x=+1)
  float goal_dist_delta = state.prev_ball_to_goal_dist - next.prev_ball_to_goal_dist;
  r += goal_dist_delta * 0.2f;

  // 5. Shot proximity bonus (if close to goal, encourage shooting)
  // The right goal is at x=+1.0 in env coords
  float player_x = next.left_pos[0];  // player 0 x position
  if (player_x > 0.7f) {
    r += 0.01f;  // close to goal bonus
  }

  // 6. Small per-step penalty (encourage fast play)
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
  // Pad to OBS_DIM (128)
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
