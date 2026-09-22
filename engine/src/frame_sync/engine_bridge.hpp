// Copyright 2019 Google LLC & Contributors
// Bridge: Create EngineCallbacks from a GameEnv instance.
// This header depends on the full engine (game_env.hpp), unlike
// engine_integration.hpp which is lightweight.

#ifndef GFOOTBALL_FRAME_SYNC_ENGINE_BRIDGE_HPP
#define GFOOTBALL_FRAME_SYNC_ENGINE_BRIDGE_HPP

#include "frame_sync/engine_integration.hpp"
#include "game_env.hpp"
#include "frame_sync/state_hash.hpp"
#include <stdexcept>

#include <string>
#include <cstdint>
#include <vector>

namespace frame_sync {

// Create EngineCallbacks that bridge to a GameEnv instance.
// The GameEnv must already be initialized and in a valid state.
inline EngineCallbacks MakeGameEnvCallbacks(GameEnv* env) {
  EngineCallbacks callbacks;

  callbacks.save_state = [env]() -> StateBlob {
    std::string state = env->get_state("");
    return StateBlob(state.begin(), state.end());
  };

  callbacks.restore_state = [env](const StateBlob& blob) {
    std::string state(blob.begin(), blob.end());
    env->set_state(state);
  };

  // 2026-09-09: preserve slot ownership; one callback is one whole frame.
  //   // 2026-08-31 修复：StepWithInput 期望 num_slots * SLOT_INPUT_BYTES 字节的缓冲区。
  //   // 将单个 SlotInput 复制到所有槽位，打包为连续缓冲区。
  //   callbacks.step = [env](const SlotInput& input) {
  //     int left = env->scenario_config.left_agents;
  //     int right = env->scenario_config.right_agents;
  //     int total = left + right;
  //     if (total <= 0) return;
  //     std::vector<SlotInput> all_slots(total, input);
  //     env->StepWithInput(all_slots.data(),
  //                        total * sizeof(SlotInput));
  //   };
  //
  callbacks.step_frame = [env](std::span<const SlotInput> inputs) {
    const int total = env->scenario_config.left_agents + env->scenario_config.right_agents;
    if (total <= 0 || inputs.size() != static_cast<size_t>(total))
      throw std::invalid_argument("frame input count does not match the session");
    env->StepWithInput(inputs.data(), inputs.size_bytes());
  };
  callbacks.step = [env, step = callbacks.step_frame](const SlotInput& input) {
    if (env->scenario_config.left_agents + env->scenario_config.right_agents != 1)
      throw std::invalid_argument("single input callback requires a single slot");
    step(std::span<const SlotInput>(&input, 1));
  };

  callbacks.compute_hash = [env]() -> uint64_t {
    std::string digest = env->get_state_digest();
    // 2026-09-09: FNV differed from the UDP/Python SHA-256 state hash.
    // return Fnv1aHash(digest);
    return ComputeStateHash(digest.data(), digest.size());
  };

  return callbacks;
}

}  // namespace frame_sync

#endif
