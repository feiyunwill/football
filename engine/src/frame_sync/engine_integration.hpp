// Copyright 2019 Google LLC & Contributors
// Shared frame sync engine integration types:
//   - EngineCallbacks: abstract interface between networking and game engine.
//   - MakeGameEnvCallbacks: bridge to GameEnv.
//   - MultiplayerConfig: session configuration.

#ifndef GFOOTBALL_FRAME_SYNC_ENGINE_INTEGRATION_HPP
#define GFOOTBALL_FRAME_SYNC_ENGINE_INTEGRATION_HPP

#include "frame_sync/protocol.hpp"
#include "frame_sync/client_state.hpp"

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace frame_sync {

// ===== Abstract engine interface =====
// The networking layer doesn't depend on GameEnv directly.
// The host wires these callbacks to connect them.
struct EngineCallbacks {
  // Save current game state as an opaque blob.
  std::function<StateBlob()> save_state;
  // Restore game state from a blob.
  std::function<void(const StateBlob&)> restore_state;
  // Step the engine one frame with the given input.
  std::function<void(const SlotInput&)> step;
  // Compute a state hash for verification.
  std::function<uint64_t()> compute_hash;
};

// Configuration for an integrated multiplayer session.
struct MultiplayerConfig {
  std::string host = "127.0.0.1";
  unsigned short port = 12345;
  uint16_t left_agents = 1;
  uint16_t right_agents = 1;
  uint32_t seed = 42;
  bool is_server = false;
  bool render = true;   // false for headless server
  int frame_rate_hz = 10;
};

// FNV-1a hash for state digest.
inline uint64_t Fnv1aHash(const std::string& data) {
  uint64_t hash = 14695981039346656037ULL;
  for (unsigned char c : data) {
    hash ^= c;
    hash *= 1099511628211ULL;
  }
  return hash;
}

}  // namespace frame_sync

#endif
