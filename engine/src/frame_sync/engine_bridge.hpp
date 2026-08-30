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

namespace frame_sync {

// FNV-1a hash for state digest.
inline uint64_t Fnv1aHash(const std::string& data) {
  uint64_t hash = 14695981039346656037ULL;
  for (unsigned char c : data) {
    hash ^= c;
    hash *= 1099511628211ULL;
  }
  return hash;
}

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

  callbacks.step = [env](const SlotInput& input) {
    env->StepWithInput(&input, sizeof(input));
  };

  callbacks.compute_hash = [env]() -> uint64_t {
    std::string digest = env->get_state_digest();
    return Fnv1aHash(digest);
  };

  return callbacks;
}

}  // namespace frame_sync

#endif
