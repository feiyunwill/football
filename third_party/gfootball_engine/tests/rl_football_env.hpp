// Copyright 2026 Google LLC & Contributors
// POC: 2D 足球环境，兼容 RLtools 接口
// 场景：单个球员控制球，尝试将球踢到目标区域
// 观测：球员位置(2) + 球位置(2) + 球速度(2) + 到球方向(2) = 8 维
// 动作：连续 2D 移动方向（归一化到 [-1, 1]）

#ifndef _HPP_RL_FOOTBALL_ENV
#define _HPP_RL_FOOTBALL_ENV

#include <rl_tools/rl/environments/environments.h>
#include <cmath>
#include <algorithm>

RL_TOOLS_NAMESPACE_WRAPPER_START
namespace rl_tools::rl::environments::football2d {

template <typename T, typename TI = unsigned long>
struct DefaultParameters {
  // 场地尺寸（归一化到 [-1, 1]）
  constexpr static T field_half_x = 1.0;
  constexpr static T field_half_y = 1.0;
  // 球员参数
  constexpr static T player_speed = 0.05;       // 每步最大移动距离
  constexpr static T player_radius = 0.03;
  // 球参数
  constexpr static T ball_radius = 0.02;
  constexpr static T ball_friction = 0.98;       // 每步速度衰减
  constexpr static T ball_max_speed = 0.15;
  constexpr static T kick_power = 0.08;          // 踢球力度
  // 目标区域
  constexpr static T goal_x = 0.9;              // 目标 x 坐标
  constexpr static T goal_half_y = 0.15;        // 目标半宽
  // 奖励
  constexpr static T touch_bonus = 1.0;         // 触球奖励
  constexpr static T goal_bonus = 10.0;         // 进球奖励
  constexpr static T step_penalty = -0.01;      // 每步惩罚
  constexpr static T distance_reward_scale = 0.5; // 距离奖励缩放
  // Episode
  constexpr static TI EPISODE_STEP_LIMIT = 200;
};

template <typename T_T, typename T_TI, typename T_PARAMETERS = DefaultParameters<T_T>>
struct Specification {
  using T = T_T;
  using TI = T_TI;
  using PARAMETERS = T_PARAMETERS;
};

template <typename T_SPEC>
struct State {
  using T = typename T_SPEC::T;
  T player_x, player_y;   // 球员位置
  T ball_x, ball_y;       // 球位置
  T ball_vx, ball_vy;     // 球速度
  bool has_ball;           // 是否控球
  T prev_ball_dist;       // 上一步到球距离（用于奖励）
};

}  // namespace rl_tools::rl::environments::football2d
RL_TOOLS_NAMESPACE_WRAPPER_END

// Environment 主定义
RL_TOOLS_NAMESPACE_WRAPPER_START
namespace rl_tools::rl::environments {

template <typename T_SPEC>
struct Football2D : Environment<typename T_SPEC::T, typename T_SPEC::TI> {
  using SPEC = T_SPEC;
  using T = typename SPEC::T;
  using TI = typename SPEC::TI;
  using State = football2d::State<SPEC>;
  using Parameters = typename SPEC::PARAMETERS;
  struct Observation { static constexpr TI DIM = 8; };  // 8 维观测
  using ObservationPrivileged = Observation;
  static constexpr TI N_AGENTS = 1;
  static constexpr TI ACTION_DIM = 2;  // 2D 移动方向
  static constexpr TI EPISODE_STEP_LIMIT = SPEC::PARAMETERS::EPISODE_STEP_LIMIT;
};

}  // namespace rl_tools::rl::environments
RL_TOOLS_NAMESPACE_WRAPPER_END

// 环境操作函数
RL_TOOLS_NAMESPACE_WRAPPER_START
namespace rl_tools {

// malloc / free / init
template <typename DEVICE, typename SPEC>
static void malloc(DEVICE&, const rl::environments::Football2D<SPEC>&) {}
template <typename DEVICE, typename SPEC>
static void free(DEVICE&, const rl::environments::Football2D<SPEC>&) {}
template <typename DEVICE, typename SPEC>
static void init(DEVICE&, const rl::environments::Football2D<SPEC>&) {}
template <typename DEVICE, typename SPEC, typename RNG>
static void sample_initial_parameters(DEVICE&, const rl::environments::Football2D<SPEC>&,
                                       typename rl::environments::Football2D<SPEC>::Parameters&, RNG&) {}
template <typename DEVICE, typename SPEC>
static void initial_parameters(DEVICE&, const rl::environments::Football2D<SPEC>&,
                                typename rl::environments::Football2D<SPEC>::Parameters&) {}

// 初始状态
template <typename DEVICE, typename SPEC, typename RNG>
static void initial_state(DEVICE& dev, const rl::environments::Football2D<SPEC>&,
                           typename rl::environments::Football2D<SPEC>::Parameters&,
                           typename rl::environments::football2d::State<SPEC>& state, RNG& rng) {
  using T = typename SPEC::T;
  // 球员随机位置
  state.player_x = random::uniform_real_distribution(dev.random, (T)-0.5, (T)0.5, rng);
  state.player_y = random::uniform_real_distribution(dev.random, (T)-0.5, (T)0.5, rng);
  // 球随机位置
  state.ball_x = random::uniform_real_distribution(dev.random, (T)-0.8, (T)0.8, rng);
  state.ball_y = random::uniform_real_distribution(dev.random, (T)-0.8, (T)0.8, rng);
  state.ball_vx = 0;
  state.ball_vy = 0;
  state.has_ball = false;
  T dx = state.ball_x - state.player_x;
  T dy = state.ball_y - state.player_y;
  state.prev_ball_dist = std::sqrt(dx * dx + dy * dy);
}

template <typename DEVICE, typename SPEC, typename RNG>
static void sample_initial_state(DEVICE& dev, const rl::environments::Football2D<SPEC>& env,
                                  typename rl::environments::Football2D<SPEC>::Parameters& params,
                                  typename rl::environments::football2d::State<SPEC>& state, RNG& rng) {
  initial_state(dev, env, params, state, rng);
}

// Step：执行动作，返回时间步长
template <typename DEVICE, typename SPEC, typename STATE_SPEC, typename ACTION_SPEC, typename RNG>
static typename SPEC::T step(DEVICE& dev, const rl::environments::Football2D<SPEC>&,
                              typename rl::environments::Football2D<SPEC>::Parameters&,
                              const typename rl::environments::football2d::State<STATE_SPEC>& state,
                              const Matrix<ACTION_SPEC>& action,
                              typename rl::environments::football2d::State<STATE_SPEC>& next_state,
                              RNG&) {
  using T = typename SPEC::T;
  using P = typename SPEC::PARAMETERS;

  // 解析动作：2D 归一化方向
  T ax = math::clamp(dev.math, get(action, 0, 0), (T)-1, (T)1);
  T ay = math::clamp(dev.math, get(action, 0, 1), (T)-1, (T)1);

  // 球员移动
  T move_len = std::sqrt(ax * ax + ay * ay);
  if (move_len > 0.001) {
    T scale = std::min(move_len, (T)1) / move_len * P::player_speed;
    next_state.player_x = state.player_x + ax * scale;
    next_state.player_y = state.player_y + ay * scale;
  } else {
    next_state.player_x = state.player_x;
    next_state.player_y = state.player_y;
  }

  // 边界限制
  next_state.player_x = math::clamp(dev.math, next_state.player_x, -P::field_half_x, P::field_half_x);
  next_state.player_y = math::clamp(dev.math, next_state.player_y, -P::field_half_y, P::field_half_y);

  // 球物理：速度衰减
  next_state.ball_vx = state.ball_vx * P::ball_friction;
  next_state.ball_vy = state.ball_vy * P::ball_friction;
  next_state.ball_x = state.ball_x + next_state.ball_vx;
  next_state.ball_y = state.ball_y + next_state.ball_vy;

  // 球边界反弹
  if (next_state.ball_x < -P::field_half_x || next_state.ball_x > P::field_half_x) {
    next_state.ball_vx = -next_state.ball_vx * 0.5;
    next_state.ball_x = math::clamp(dev.math, next_state.ball_x, -P::field_half_x, P::field_half_x);
  }
  if (next_state.ball_y < -P::field_half_y || next_state.ball_y > P::field_half_y) {
    next_state.ball_vy = -next_state.ball_vy * 0.5;
    next_state.ball_y = math::clamp(dev.math, next_state.ball_y, -P::field_half_y, P::field_half_y);
  }

  // 碰撞检测：球员触球
  T dx = next_state.ball_x - next_state.player_x;
  T dy = next_state.ball_y - next_state.player_y;
  T dist = std::sqrt(dx * dx + dy * dy);
  T contact_dist = P::player_radius + P::ball_radius;

  next_state.has_ball = false;
  if (dist < contact_dist) {
    // 触球：球获得球员运动方向的速度
    if (move_len > 0.001) {
      T kick_scale = P::kick_power / std::max(move_len, (T)0.001);
      next_state.ball_vx = ax * kick_scale;
      next_state.ball_vy = ay * kick_scale;
    }
    // 限制球速
    T ball_speed = std::sqrt(next_state.ball_vx * next_state.ball_vx + next_state.ball_vy * next_state.ball_vy);
    if (ball_speed > P::ball_max_speed) {
      T s = P::ball_max_speed / ball_speed;
      next_state.ball_vx *= s;
      next_state.ball_vy *= s;
    }
    next_state.has_ball = true;
  }

  next_state.prev_ball_dist = dist;

  return (T)1.0;  // 时间步长
}

// Reward
template <typename DEVICE, typename SPEC, typename STATE_SPEC, typename ACTION_SPEC, typename RNG>
static typename SPEC::T reward(DEVICE& dev, const rl::environments::Football2D<SPEC>&,
                                typename rl::environments::Football2D<SPEC>::Parameters&,
                                const typename rl::environments::football2d::State<STATE_SPEC>& state,
                                const Matrix<ACTION_SPEC>&,
                                const typename rl::environments::football2d::State<STATE_SPEC>& next_state,
                                RNG&) {
  using T = typename SPEC::T;
  using P = typename SPEC::PARAMETERS;

  T r = P::step_penalty;

  // 距离奖励：接近球
  T dist_improvement = state.prev_ball_dist - next_state.prev_ball_dist;
  r += dist_improvement * P::distance_reward_scale;

  // 触球奖励
  if (next_state.has_ball) {
    r += P::touch_bonus;
  }

  // 进球奖励：球到达目标区域
  if (next_state.ball_x > P::goal_x &&
      std::abs(next_state.ball_y) < P::goal_half_y) {
    r += P::goal_bonus;
  }

  return r;
}

// Observe：生成 8 维观测
template <typename DEVICE, typename SPEC, typename STATE_SPEC, typename OBS_SPEC, typename RNG>
static void observe(DEVICE&, const rl::environments::Football2D<SPEC>&,
                     const typename rl::environments::Football2D<SPEC>::Parameters&,
                     const typename rl::environments::football2d::State<STATE_SPEC>& state,
                     const typename rl::environments::Football2D<SPEC>::Observation&,
                     Matrix<OBS_SPEC>& observation, RNG&) {
  using T = typename SPEC::T;

  // 到球方向（归一化）
  T dx = state.ball_x - state.player_x;
  T dy = state.ball_y - state.player_y;
  T dist = std::sqrt(dx * dx + dy * dy);
  T dir_x = dist > 0.001 ? dx / dist : 0;
  T dir_y = dist > 0.001 ? dy / dist : 0;

  set(observation, 0, 0, state.player_x);
  set(observation, 0, 1, state.player_y);
  set(observation, 0, 2, state.ball_x);
  set(observation, 0, 3, state.ball_y);
  set(observation, 0, 4, state.ball_vx);
  set(observation, 0, 5, state.ball_vy);
  set(observation, 0, 6, dir_x);
  set(observation, 0, 7, dir_y);
}

// Terminated
template <typename DEVICE, typename SPEC, typename STATE_SPEC, typename RNG>
static bool terminated(DEVICE&, const rl::environments::Football2D<SPEC>&,
                        typename rl::environments::Football2D<SPEC>::Parameters&,
                        const typename rl::environments::football2d::State<STATE_SPEC>&, RNG&) {
  return false;  // 由 EPISODE_STEP_LIMIT 控制
}

}  // namespace rl_tools
RL_TOOLS_NAMESPACE_WRAPPER_END

#endif
