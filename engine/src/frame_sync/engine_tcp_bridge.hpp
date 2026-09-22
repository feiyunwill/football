// Copyright 2026 Google LLC & Contributors
// 2026-09-09: real GameEnv observations for TCP bot handover.
#ifndef GFOOTBALL_FRAME_SYNC_ENGINE_TCP_BRIDGE_HPP
#define GFOOTBALL_FRAME_SYNC_ENGINE_TCP_BRIDGE_HPP
#include "frame_sync/engine_tcp_server.hpp"
#include "frame_sync/engine_bridge.hpp"
#include "frame_sync/engine_bot_observer.hpp"
// 2026-09-13: product and legacy initialization share validated formation construction.
// #include "frame_sync/default_scenario.hpp"
#include "frame_sync/default_scenario.hpp"
#include "frame_sync/native_match_scenario.hpp"
namespace frame_sync {
inline void StartTCPGame(GameEnv& env, const MultiplayerConfig& config,
                         const EngineTCPServerLimits& limits = {}) {
  limits.Validate(config);  // Validate before loading/allocating the actual match.
  env.game_config.render = false;
  // 2026-09-13: authority physics agrees with native product handshake.
  // env.game_config.physics_steps_per_frame = 10;
  env.game_config.physics_steps_per_frame = config.native_product ? NativeMatchContract::kPhysicsSteps : 10;
  // 2026-09-13: preserve nominal match duration at 50 Hz.
  // auto scenario = MakeDefaultScenario(config.left_agents, config.right_agents, config.seed);
  auto scenario = config.native_product ? MakeNativeMatchScenario(NativeMatchContract(config.seed,config.left_agents,config.right_agents))
                                       : MakeDefaultScenario(config.left_agents, config.right_agents, config.seed);
  env.start_game(*scenario);
  env.state = GameState::game_running;
}
}  // namespace frame_sync
#endif

// 2026-09-14: superseded implementation retained for milestone review.
// // Copyright 2026 Google LLC & Contributors
// // 2026-09-09: real GameEnv observations for TCP bot handover.
// #ifndef GFOOTBALL_FRAME_SYNC_ENGINE_TCP_BRIDGE_HPP
// #define GFOOTBALL_FRAME_SYNC_ENGINE_TCP_BRIDGE_HPP
// #include "frame_sync/engine_tcp_server.hpp"
// #include "frame_sync/engine_bridge.hpp"
// // 2026-09-13: product and legacy initialization share validated formation construction.
// // #include "frame_sync/default_scenario.hpp"
// #include "frame_sync/default_scenario.hpp"
// #include "frame_sync/native_match_scenario.hpp"
// namespace frame_sync {
// inline void StartTCPGame(GameEnv& env, const MultiplayerConfig& config,
//                          const EngineTCPServerLimits& limits = {}) {
//   limits.Validate(config);  // Validate before loading/allocating the actual match.
//   env.game_config.render = false;
//   // 2026-09-13: authority physics agrees with native product handshake.
//   // env.game_config.physics_steps_per_frame = 10;
//   env.game_config.physics_steps_per_frame = config.native_product ? NativeMatchContract::kPhysicsSteps : 10;
//   // 2026-09-13: preserve nominal match duration at 50 Hz.
//   // auto scenario = MakeDefaultScenario(config.left_agents, config.right_agents, config.seed);
//   auto scenario = config.native_product ? MakeNativeMatchScenario(NativeMatchContract(config.seed,config.left_agents,config.right_agents))
//                                        : MakeDefaultScenario(config.left_agents, config.right_agents, config.seed);
//   env.start_game(*scenario);
//   env.state = GameState::game_running;
// }
// inline std::function<BotGameSnapshot()> MakeGameEnvBotObserver(GameEnv* env,
//                                                              uint16_t left, uint16_t right) {
//   if (!env || left > 11 || right > 11 || left + right == 0)
//     throw std::invalid_argument("invalid bot observation source");
//   return [env, left, right] {
//     const auto info = env->get_info();
//     BotGameSnapshot snapshot;
//     snapshot.ball_x = info.ball_position[0]; snapshot.ball_y = info.ball_position[1];
//     snapshot.num_slots = left + right;
//     snapshot.player_positions.reserve(size_t(left + right) * 2);
//     snapshot.pitch_min_x = -pitchHalfW; snapshot.pitch_max_x = pitchHalfW;
//     snapshot.pitch_min_y = -pitchHalfH; snapshot.pitch_max_y = pitchHalfH;
//     snapshot.goal_x_left = -pitchHalfW; snapshot.goal_x_right = pitchHalfW;
//     for (unsigned side = 0; side < 2; ++side) {
//       const auto& players = side == 0 ? info.left_team : info.right_team;
//       const auto& controllers = side == 0 ? info.left_controllers : info.right_controllers;
//       const auto count = side == 0 ? left : right;
//       for (size_t i = 0; i < count; ++i) {
//         // 2026-09-13: preserve the previous fatal interpretation for review.
// //         if (i >= controllers.size() || controllers[i].controlled_player < 0 ||
// //             size_t(controllers[i].controlled_player) >= players.size())
// //           throw std::runtime_error("bot slot has no selected GameEnv player");
//         // 2026-09-13: -1 is the real GameEnv no-selection sentinel during stoppages.
//         if (i >= controllers.size() || controllers[i].controlled_player < -1 ||
//             (controllers[i].controlled_player >= 0 &&
//              size_t(controllers[i].controlled_player) >= players.size()))
//           throw std::runtime_error("bot slot has invalid GameEnv player metadata");
//         if (controllers[i].controlled_player == -1) {
//           const auto slot = (side == 0 ? 0 : left) + i;
//           snapshot.unavailable_slots |= std::uint32_t(1) << slot;
//           snapshot.player_positions.push_back(0);
//           snapshot.player_positions.push_back(0);
//           continue;
//         }
//         const auto& position = players[controllers[i].controlled_player].player_position;
//         snapshot.player_positions.push_back(position[0]); snapshot.player_positions.push_back(position[1]);
//       }
//     }
//     return snapshot;
//   };
// }
// }  // namespace frame_sync
// #endif
