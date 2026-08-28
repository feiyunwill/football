// Copyright 2026 Google LLC & Contributors
// PPO training: real GameEnv integration, 1 RL player vs AI opponent
// Build: cmake --build build_rl -j 1 --target rl_football_training
// Run:   GFOOTBALL_DATA_DIR=../data xvfb-run -a ./rl_football_training [seed]

#include <rl_tools/operations/cpu_mux.h>

// Engine headers (must come before RLtools to define types used by wrapper)
#include "../../game_env.hpp"
#include "../../main.hpp"

// Environment wrapper (uses GameEnv types)
#include "game_env_wrapper.hpp"

// RLtools algorithms
#include <rl_tools/nn/optimizers/adam/instance/operations_generic.h>
#include <rl_tools/nn/layers/standardize/operations_generic.h>
#include <rl_tools/nn_models/mlp_unconditional_stddev/operations_generic.h>
#include <rl_tools/nn_models/sequential/operations_generic.h>
#include <rl_tools/nn/optimizers/adam/operations_generic.h>

// PPO loop
#include <rl_tools/rl/algorithms/ppo/loop/core/config.h>
#include <rl_tools/rl/loop/steps/evaluation/config.h>
#include <rl_tools/rl/loop/steps/timing/config.h>
#include <rl_tools/rl/algorithms/ppo/loop/core/operations_generic.h>
#include <rl_tools/rl/loop/steps/evaluation/operations_generic.h>
#include <rl_tools/rl/loop/steps/timing/operations_cpu.h>

#include <iostream>
#include <print>
#include <memory>
#include <cstdlib>
#include <chrono>

namespace rlt = rl_tools;

// ===== Global engine pointer (accessed by game_env_wrapper.hpp) =====
GameEnv* g_rl_env = nullptr;

// ===== PPO Configuration =====
template <typename DEVICE, typename TYPE_POLICY, bool DYNAMIC_ALLOCATION>
struct ConfigFactory {
  using TI = typename DEVICE::index_t;
  using T = typename TYPE_POLICY::DEFAULT;

  using GAME_ENV_SPEC = rlt::rl::environments::game_env_wrapper::Specification<T, TI>;
  using ENVIRONMENT = rlt::rl::environments::GameEnvWrapper<GAME_ENV_SPEC>;

  struct LOOP_CORE_PARAMETERS : rlt::rl::algorithms::ppo::loop::core::DefaultParameters<TYPE_POLICY, TI, ENVIRONMENT> {
    static constexpr TI BATCH_SIZE = 256;
    static constexpr TI ACTOR_HIDDEN_DIM = 256;
    static constexpr TI CRITIC_HIDDEN_DIM = 256;
    static constexpr TI ON_POLICY_RUNNER_STEPS_PER_ENV = 512;
    static constexpr TI N_ENVIRONMENTS = 1;  // GameEnv is a singleton
    static constexpr TI TOTAL_STEP_LIMIT = 20000;  // Quick test (increase for real training)
    static constexpr TI STEP_LIMIT = TOTAL_STEP_LIMIT / (ON_POLICY_RUNNER_STEPS_PER_ENV * N_ENVIRONMENTS) + 1;
    static constexpr TI EPISODE_STEP_LIMIT = 3000;
    using ACTOR_OPTIMIZER_PARAMETERS = rlt::nn::optimizers::adam::DEFAULT_PARAMETERS_PYTORCH<TYPE_POLICY>;
    using CRITIC_OPTIMIZER_PARAMETERS = ACTOR_OPTIMIZER_PARAMETERS;
    struct PPO_PARAMETERS : rlt::rl::algorithms::ppo::DefaultParameters<TYPE_POLICY, TI, BATCH_SIZE> {
      static constexpr T ACTION_ENTROPY_COEFFICIENT = 0.01;
      static constexpr TI N_EPOCHS = 4;
      static constexpr T GAMMA = 0.99;
      static constexpr T LAMBDA = 0.95;
      static constexpr T INITIAL_ACTION_STD = 1.0;
      static constexpr bool NORMALIZE_OBSERVATIONS = true;
    };
  };

  using LOOP_CORE_CONFIG = rlt::rl::algorithms::ppo::loop::core::Config<
      TYPE_POLICY, TI, typename DEVICE::SPEC::RANDOM::template ENGINE<>,
      ENVIRONMENT, LOOP_CORE_PARAMETERS,
      rlt::rl::algorithms::ppo::loop::core::ConfigApproximatorsSequential, DYNAMIC_ALLOCATION>;

  // Skip evaluation step (simplifies compilation and avoids engine re-init)
  using LOOP_TIMING_CONFIG = rlt::rl::loop::steps::timing::Config<LOOP_CORE_CONFIG>;
};

// ===== Type aliases =====
using DEVICE = rlt::devices::DEVICE_FACTORY<>;
using T = float;
using TYPE_POLICY = rlt::numeric_types::Policy<float>;
using TI = typename DEVICE::index_t;
static constexpr bool DYNAMIC_ALLOCATION = true;

using CONFIG = ConfigFactory<DEVICE, TYPE_POLICY, DYNAMIC_ALLOCATION>;
using LOOP_CONFIG = CONFIG::LOOP_TIMING_CONFIG;
using LOOP_STATE = typename LOOP_CONFIG::template State<LOOP_CONFIG>;

// ===== GameEnv lifecycle =====
void init_game_env() {
  if (g_rl_env) return;
  g_rl_env = new GameEnv();
  g_rl_env->start_game();

  // Configure 1v0 scenario with proper formations
  // Without left_team/right_team entries, GetTeamState crashes on
  // left_controllers.resize(0) then accessing index 0.
  auto& scenario = g_rl_env->scenario_config;
  scenario.left_agents = 1;
  scenario.right_agents = 0;
  scenario.real_time = false;
  scenario.deterministic = true;
  scenario.end_episode_on_score = true;
  scenario.game_duration = 3000;

  // Standard 4-4-2 formation for 11 players
  // (x, y env coords, role, lazy, controllable)
  scenario.left_team = {
    FormationEntry(0.0f,   0.0f,  e_PlayerRole_GK, false, true),
    FormationEntry(-0.4f, -0.3f,  e_PlayerRole_LB, false, false),
    FormationEntry(-0.15f,-0.3f,  e_PlayerRole_CB, false, false),
    FormationEntry(0.15f, -0.3f,  e_PlayerRole_CB, false, false),
    FormationEntry(0.4f,  -0.3f,  e_PlayerRole_RB, false, false),
    FormationEntry(-0.4f, 0.0f,  e_PlayerRole_LM, false, false),
    FormationEntry(-0.15f,0.0f,  e_PlayerRole_CM, false, false),
    FormationEntry(0.15f, 0.0f,  e_PlayerRole_CM, false, false),
    FormationEntry(0.4f,  0.0f,  e_PlayerRole_RM, false, false),
    FormationEntry(-0.15f,0.3f,  e_PlayerRole_CF, false, false),
    FormationEntry(0.15f, 0.3f,  e_PlayerRole_CF, false, false),
  };
  scenario.right_team = {
    FormationEntry(0.0f,   0.0f,  e_PlayerRole_GK, false, false),
    FormationEntry(-0.4f, -0.3f,  e_PlayerRole_LB, false, false),
    FormationEntry(-0.15f,-0.3f,  e_PlayerRole_CB, false, false),
    FormationEntry(0.15f, -0.3f,  e_PlayerRole_CB, false, false),
    FormationEntry(0.4f,  -0.3f,  e_PlayerRole_RB, false, false),
    FormationEntry(-0.4f, 0.0f,  e_PlayerRole_LM, false, false),
    FormationEntry(-0.15f,0.0f,  e_PlayerRole_CM, false, false),
    FormationEntry(0.15f, 0.0f,  e_PlayerRole_CM, false, false),
    FormationEntry(0.4f,  0.0f,  e_PlayerRole_RM, false, false),
    FormationEntry(-0.15f,0.3f,  e_PlayerRole_CF, false, false),
    FormationEntry(0.15f, 0.3f,  e_PlayerRole_CF, false, false),
  };

  // Headless mode
  g_rl_env->game_config.render = false;

  g_rl_env->reset(scenario, false);
  std::println("GameEnv initialized (headless, 1v0)");
}

// ===== Training entry =====
auto run(TI seed) {
  DEVICE device;
  std::println("=== Football PPO Training (Real Engine) ===");
  std::println("Seed: {}", seed);

  // Initialize engine
  init_game_env();

  LOOP_STATE ts;
  rlt::malloc(device, ts);
  rlt::init(device, ts, seed);

  TI step_count = 0;
  TI total_env_steps = 0;
  auto wall_start = std::chrono::steady_clock::now();
  while (!rlt::step(device, ts)) {
    step_count++;
    total_env_steps += CONFIG::LOOP_CORE_CONFIG::CORE_PARAMETERS::ON_POLICY_RUNNER_STEPS_PER_ENV
                     * CONFIG::LOOP_CORE_CONFIG::CORE_PARAMETERS::N_ENVIRONMENTS;
    auto wall_now = std::chrono::steady_clock::now();
    float wall_sec = std::chrono::duration<float>(wall_now - wall_start).count();
    float sps = (wall_sec > 0.0f) ? static_cast<float>(total_env_steps) / wall_sec : 0.0f;
    if (step_count % 5 == 0) {
      std::println("Loop step: {:4d}, env step: {:6d}, SPS: {:.1f} (wall: {:.0f}s)",
                   step_count, total_env_steps, sps, wall_sec);
    }
  }

  auto wall_end = std::chrono::steady_clock::now();
  float total_wall = std::chrono::duration<float>(wall_end - wall_start).count();
  std::println("Training complete! Steps: {}, Wall: {:.1f}s, SPS: {:.1f}",
               ts.step, total_wall, static_cast<float>(ts.step) / total_wall);
  rl_tools::print_action_stats();
  rlt::free(device, ts);
  return 0;
}

int main(int argc, char** argv) {
  TI seed = 42;
  if (argc > 1) {
    seed = static_cast<TI>(std::stoul(argv[1]));
  }

  try {
    return run(seed);
  } catch (const std::exception& e) {
    std::cerr << "Error: " << e.what() << std::endl;
    return 1;
  } catch (...) {
    std::cerr << "Unknown error" << std::endl;
    return 1;
  }
}
