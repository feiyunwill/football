// Copyright 2019 Google LLC & Contributors
// Bridge: Create EngineCallbacks from a GameEnv instance.
// This header depends on the full engine (game_env.hpp), unlike
// engine_integration.hpp which is lightweight.

#ifndef GFOOTBALL_FRAME_SYNC_ENGINE_BRIDGE_HPP
#define GFOOTBALL_FRAME_SYNC_ENGINE_BRIDGE_HPP

#include "frame_sync/engine_integration.hpp"
#include "game_env.hpp"

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

  // 2026-08-31 修复：StepWithInput 期望 num_slots * SLOT_INPUT_BYTES 字节的缓冲区。
  // 将单个 SlotInput 复制到所有槽位，打包为连续缓冲区。
  callbacks.step = [env](const SlotInput& input) {
    int left = env->scenario_config.left_agents;
    int right = env->scenario_config.right_agents;
    int total = left + right;
    if (total <= 0) return;
    std::vector<SlotInput> all_slots(total, input);
    env->StepWithInput(all_slots.data(),
                       total * sizeof(SlotInput));
  };

  callbacks.compute_hash = [env]() -> uint64_t {
    std::string digest = env->get_state_digest();
    return Fnv1aHash(digest);
  };

  return callbacks;
}

}  // namespace frame_sync

#endif
