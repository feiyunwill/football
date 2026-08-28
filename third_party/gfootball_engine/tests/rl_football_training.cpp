// Copyright 2026 Google LLC & Contributors
// POC: C++ PPO 训练 — 2D 足球单智能体控球
// 编译: cd third_party/gfootball_engine && cmake -S tests -B build_rl -DENABLE_RLTOOLS=ON && cmake --build build_rl -j 2
// 运行: ./build_rl/rl_football_training [seed]

#ifdef RL_TOOLS_STATIC_MEM
#define RL_TOOLS_DISABLE_DYNAMIC_MEMORY_ALLOCATIONS
#endif

#include <rl_tools/operations/cpu_mux.h>

// 环境
#include "rl_football_env.hpp"

// RL 算法
#include <rl_tools/nn/optimizers/adam/instance/operations_generic.h>
#include <rl_tools/nn/layers/standardize/operations_generic.h>
#include <rl_tools/nn_models/mlp_unconditional_stddev/operations_generic.h>
#include <rl_tools/nn_models/sequential/operations_generic.h>
#include <rl_tools/nn/optimizers/adam/operations_generic.h>

// PPO 循环
#include <rl_tools/rl/algorithms/ppo/loop/core/config.h>
#include <rl_tools/rl/loop/steps/evaluation/config.h>
#include <rl_tools/rl/loop/steps/timing/config.h>
#include <rl_tools/rl/algorithms/ppo/loop/core/operations_generic.h>
#include <rl_tools/rl/loop/steps/evaluation/operations_generic.h>
#include <rl_tools/rl/loop/steps/timing/operations_cpu.h>

#include <iostream>
#include <utility>

namespace rlt = rl_tools;

// ===== 环境与算法配置 =====

template <typename DEVICE, typename TYPE_POLICY, bool DYNAMIC_ALLOCATION>
struct ConfigFactory {
  using TI = typename DEVICE::index_t;
  using T = typename TYPE_POLICY::DEFAULT;

  // 2D 足球环境
  using FOOTBALL_SPEC = rlt::rl::environments::football2d::Specification<T, TI>;
  using ENVIRONMENT = rlt::rl::environments::Football2D<FOOTBALL_SPEC>;

  // PPO 参数
  struct LOOP_CORE_PARAMETERS : rlt::rl::algorithms::ppo::loop::core::DefaultParameters<TYPE_POLICY, TI, ENVIRONMENT> {
    static constexpr TI BATCH_SIZE = 128;
    static constexpr TI ACTOR_HIDDEN_DIM = 64;
    static constexpr TI CRITIC_HIDDEN_DIM = 64;
    static constexpr TI ON_POLICY_RUNNER_STEPS_PER_ENV = 512;
    static constexpr TI N_ENVIRONMENTS = 4;
    static constexpr TI TOTAL_STEP_LIMIT = 200000;
    static constexpr TI STEP_LIMIT = TOTAL_STEP_LIMIT / (ON_POLICY_RUNNER_STEPS_PER_ENV * N_ENVIRONMENTS) + 1;
    static constexpr TI EPISODE_STEP_LIMIT = 200;
    using ACTOR_OPTIMIZER_PARAMETERS = rlt::nn::optimizers::adam::DEFAULT_PARAMETERS_PYTORCH<TYPE_POLICY>;
    using CRITIC_OPTIMIZER_PARAMETERS = ACTOR_OPTIMIZER_PARAMETERS;
    struct PPO_PARAMETERS : rlt::rl::algorithms::ppo::DefaultParameters<TYPE_POLICY, TI, BATCH_SIZE> {
      static constexpr T ACTION_ENTROPY_COEFFICIENT = 0.01;
      static constexpr TI N_EPOCHS = 2;
      static constexpr T GAMMA = 0.99;
      static constexpr T INITIAL_ACTION_STD = 1.0;
      static constexpr bool NORMALIZE_OBSERVATIONS = true;
    };
  };

  using LOOP_CORE_CONFIG = rlt::rl::algorithms::ppo::loop::core::Config<
      TYPE_POLICY, TI, typename DEVICE::SPEC::RANDOM::template ENGINE<>,
      ENVIRONMENT, LOOP_CORE_PARAMETERS,
      rlt::rl::algorithms::ppo::loop::core::ConfigApproximatorsSequential, DYNAMIC_ALLOCATION>;

  template <typename NEXT>
  struct LOOP_EVAL_PARAMETERS : rlt::rl::loop::steps::evaluation::Parameters<TYPE_POLICY, TI, NEXT> {
    static constexpr TI EVALUATION_INTERVAL = 10;
    static constexpr TI NUM_EVALUATION_EPISODES = 50;
    static constexpr TI N_EVALUATIONS = NEXT::CORE_PARAMETERS::STEP_LIMIT / EVALUATION_INTERVAL;
  };

  using LOOP_EVAL_CONFIG = rlt::rl::loop::steps::evaluation::Config<LOOP_CORE_CONFIG, LOOP_EVAL_PARAMETERS<LOOP_CORE_CONFIG>>;
  using LOOP_TIMING_CONFIG = rlt::rl::loop::steps::timing::Config<LOOP_EVAL_CONFIG>;
};

// ===== 训练主函数 =====

using DEVICE = rlt::devices::DEVICE_FACTORY<>;
using T = float;
using TYPE_POLICY = rlt::numeric_types::Policy<float>;
using TI = typename DEVICE::index_t;
static constexpr bool DYNAMIC_ALLOCATION = true;

using CONFIG = ConfigFactory<DEVICE, TYPE_POLICY, DYNAMIC_ALLOCATION>;
using LOOP_CONFIG = CONFIG::LOOP_TIMING_CONFIG;
using LOOP_STATE = typename LOOP_CONFIG::template State<LOOP_CONFIG>;

auto run(TI seed) {
  DEVICE device;
  std::cout << "=== Football2D PPO Training ===" << std::endl;
  std::cout << "Seed: " << seed << std::endl;

  LOOP_STATE ts;
  rlt::malloc(device, ts);
  rlt::init(device, ts, seed);

  TI step_count = 0;
  while (!rlt::step(device, ts)) {
    step_count++;
    if (step_count % 100 == 0) {
      std::cout << "Step " << step_count << "/" << CONFIG::LOOP_CORE_CONFIG::CORE_PARAMETERS::STEP_LIMIT << std::endl;
    }
  }

  std::cout << "Training complete! Total steps: " << ts.step << std::endl;
  rlt::free(device, ts);
  return 0;
}

int main(int argc, char** argv) {
  TI seed = 42;
  if (argc > 1) {
    seed = static_cast<TI>(std::stoul(argv[1]));
  }
  return run(seed);
}
