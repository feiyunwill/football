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

#include "checkpoint.hpp"
#include <iostream>
#include <cstdio>  // 2026-08-30: printf instead of std::println to avoid _Float128 linker errors
#include <memory>
#include <cstdlib>
#include <chrono>
#include <cstring>
#include <string>

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
    static constexpr TI TOTAL_STEP_LIMIT = 100000;  // ~55 min at 30 SPS
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

  // Configure 11v11 scenario with proper formations
  auto& scenario = g_rl_env->scenario_config;
  scenario.left_agents = 11;  // all left players are RL-controlled
  scenario.right_agents = 0;  // right team uses built-in AI
  scenario.real_time = false;
  scenario.deterministic = true;
  scenario.end_episode_on_score = false;  // let episodes run full length
  scenario.game_duration = 3000;

  // Standard 4-4-2 formation for 11 players
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
  printf("GameEnv initialized (headless, 11v11 shared policy)\n");
}

// ===== Training entry =====
auto run(TI seed, bool eval_mode = false,
         const std::string& load_path = "",
         const std::string& save_prefix = "",
         TI save_interval = 10000) {
  DEVICE device;
  printf("=== Football PPO %s (Real Engine) ===\n", eval_mode ? "Evaluation" : "Training");
  printf("Seed: %lu\n", static_cast<unsigned long>(seed));

  // Initialize engine
  init_game_env();

  LOOP_STATE ts;
  rlt::malloc(device, ts);

  // Load checkpoint if specified
  if (!load_path.empty()) {
    printf("Loading checkpoint: %s\n", load_path.c_str());
    if (!rl_tools::checkpoint::load_checkpoint(device, ts, load_path.c_str())) {
      fprintf(stderr, "Failed to load checkpoint, starting from scratch\n");
      rlt::init(device, ts, seed);
    }
  } else {
    rlt::init(device, ts, seed);
  }

  // ---- Play mode ----
  if (eval_mode) {
    printf("\n--- Play mode: running trained policy ---\n");
    TI step_count = 0;
    while (!rlt::step(device, ts)) {
      step_count++;
      SharedInfo info = rl_tools::safe_get_info();
      if (step_count % 10 == 0) {
        printf("[%4lu] ball:(%.2f,%.2f) score:%d/%d poss:%s\n",
          static_cast<unsigned long>(step_count),
          info.ball_position[0], info.ball_position[1],
          info.left_goals, info.right_goals,
          info.ball_owned_team == 0 ? "yes" : "no");
      }
    }
    printf("Play complete! Final score: %d/%d\n",
      g_rl_env->get_info().left_goals, g_rl_env->get_info().right_goals);
    rl_tools::print_action_stats();
    rlt::free(device, ts);
    return 0;
  }

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
      printf("Loop step: %4lu, env step: %6lu, SPS: %.1f (wall: %.0fs)\n",
             static_cast<unsigned long>(step_count),
             static_cast<unsigned long>(total_env_steps), sps, wall_sec);
    }

    // Auto-save checkpoint
    if (!save_prefix.empty() && ts.step > 0 && (ts.step % save_interval == 0)) {
      std::string ckpt_path = save_prefix + "_step" + std::to_string(ts.step) + ".tar";
      rl_tools::checkpoint::save_checkpoint(device, ts, ckpt_path.c_str());
    }
  }

  auto wall_end = std::chrono::steady_clock::now();
  float total_wall = std::chrono::duration<float>(wall_end - wall_start).count();
  printf("Training complete! Steps: %lu, Wall: %.1fs, SPS: %.1f\n",
         static_cast<unsigned long>(ts.step), total_wall,
         static_cast<float>(ts.step) / total_wall);
  rl_tools::print_action_stats();

  // Save final checkpoint
  if (!save_prefix.empty()) {
    std::string final_path = save_prefix + "_final.tar";
    rl_tools::checkpoint::save_checkpoint(device, ts, final_path.c_str());
  }

  rlt::free(device, ts);
  return 0;
}

int main(int argc, char** argv) {
  TI seed = 42;
  bool eval_mode = false;
  std::string load_path;
  std::string save_prefix;
  TI save_interval = 10000;

  for (int i = 1; i < argc; i++) {
    std::string arg = argv[i];
    if (arg == "--eval") {
      eval_mode = true;
    } else if (arg == "--load" && i + 1 < argc) {
      load_path = argv[++i];
    } else if (arg == "--save" && i + 1 < argc) {
      save_prefix = argv[++i];
    } else if (arg == "--save-interval" && i + 1 < argc) {
      save_interval = static_cast<TI>(std::stoul(argv[++i]));
    } else if (arg == "--help" || arg == "-h") {
      printf("Usage: %s [options] [seed]\n", argv[0]);
      printf("  --eval                Run evaluation mode\n");
      printf("  --load <path.tar>     Load checkpoint before training\n");
      printf("  --save <prefix>       Save checkpoints with prefix\n");
      printf("  --save-interval <N>   Save every N steps (default: 10000)\n");
      return 0;
    } else {
      seed = static_cast<TI>(std::stoul(arg));
    }
  }

  try {
    return run(seed, eval_mode, load_path, save_prefix, save_interval);
  } catch (const std::exception& e) {
    fprintf(stderr, "Error: %s\n", e.what());
    return 1;
  } catch (...) {
    fprintf(stderr, "Unknown error\n");
    return 1;
  }
}
