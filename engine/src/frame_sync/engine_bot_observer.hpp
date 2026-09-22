// 2026-09-14: TCP and UDP observe the same logical state on the engine owner.
#pragma once
#include "frame_sync/bot_takeover.hpp"
#include "frame_sync/engine_bridge.hpp"
namespace frame_sync {
inline std::function<BotGameSnapshot()> MakeGameEnvBotObserver(GameEnv* env,
                                                               uint16_t left,
                                                               uint16_t right) {
  if (!env || left > 11 || right > 11 || left + right == 0)
    throw std::invalid_argument("invalid bot observation source");
  return [env, left, right] {
    ContextHolder guard(env);
    if (env->scenario_config.left_agents != left ||
        env->scenario_config.right_agents != right)
      throw std::invalid_argument(
          "bot observation slot counts differ from its match");
    BotGameSnapshot snapshot;
    snapshot.tactics = ai::ObserveTacticalFrame(*env);
    const auto& frame = *snapshot.tactics;
    snapshot.ball_x = frame.ball[0];
    snapshot.ball_y = frame.ball[1];
    snapshot.num_slots = frame.slots;
    snapshot.pitch_min_x = std::min(frame.own_goal_x[0], frame.own_goal_x[1]);
    snapshot.pitch_max_x = std::max(frame.own_goal_x[0], frame.own_goal_x[1]);
    snapshot.pitch_min_y = -frame.pitch_half_y;
    snapshot.pitch_max_y = frame.pitch_half_y;
    snapshot.goal_x_left = frame.own_goal_x[0];
    snapshot.goal_x_right = frame.own_goal_x[1];
    snapshot.player_positions.reserve(size_t(frame.slots) * 2);
    for (unsigned slot = 0; slot < frame.slots; ++slot) {
      const int actor = frame.controlled_player[slot];
      if (actor < 0) {
        snapshot.unavailable_slots |= std::uint32_t(1) << slot;
        snapshot.player_positions.push_back(0);
        snapshot.player_positions.push_back(0);
      } else {
        const auto& position =
            frame.players[frame.controlled_team[slot]][actor].position;
        snapshot.player_positions.push_back(position[0]);
        snapshot.player_positions.push_back(position[1]);
      }
    }
    return snapshot;
  };
}
}  // namespace frame_sync
