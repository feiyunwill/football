// Copyright 2026 Google LLC & Contributors
// BotTakeoverManager: manages AI takeover for disconnected client slots.
//
// When a client disconnects, the server creates a bot controller for their slot.
// The bot generates SlotInput (direction + buttons) that is applied via
// DecodeAndApplyFrameInput, just like human input. The HumanController reads
// from AIControlledKeyboard and doesn't distinguish between human and bot input.
//
// Bot AI logic (simple but functional):
//   - Attacking (ball in opponent half): move toward ball, sprint, shoot when near goal
//   - Defending (ball in own half): move toward ball, defend, clear
//   - General: always sprint toward ball when not in possession

#ifndef GFOOTBALL_FRAME_SYNC_BOT_TAKEOVER_HPP
#define GFOOTBALL_FRAME_SYNC_BOT_TAKEOVER_HPP

#include "frame_sync/protocol.hpp"

#include <cmath>
#include <cstdint>
#include <unordered_map>
#include <vector>

namespace frame_sync {

// Simple bot AI state per slot
struct BotState {
  bool active = false;
  uint16_t slot_index = 0;
  int team = 0;           // 0 = left, 1 = right
  float last_ball_x = 0.f;
  float last_ball_y = 0.f;
  float last_player_x = 0.f;
  float last_player_y = 0.f;
  int shoot_cooldown = 0;  // frames until next shot attempt
};

// Minimal game state snapshot for bot decision-making.
// The server provides this each frame from the headless GameEnv.
struct BotGameSnapshot {
  float ball_x = 0.f;
  float ball_y = 0.f;
  // Player positions: [slot_index * 2] = x, [slot_index * 2 + 1] = y
  std::vector<float> player_positions;
  int num_slots = 0;
  // Pitch dimensions (approximate)
  float pitch_min_x = -100.f;
  float pitch_max_x = 100.f;
  float pitch_min_y = -60.f;
  float pitch_max_y = 60.f;
  float goal_x_left = -100.f;   // left team's goal x
  float goal_x_right = 100.f;   // right team's goal x
};

class BotTakeoverManager {
 public:
  // Activate bot for a slot
  void Takeover(uint16_t slot_index, int team) {
    BotState& bot = bots_[slot_index];
    bot.active = true;
    bot.slot_index = slot_index;
    bot.team = team;
    bot.shoot_cooldown = 0;
  }

  // Deactivate bot for a slot
  void Handback(uint16_t slot_index) {
    bots_.erase(slot_index);
  }

  // Check if a slot is bot-controlled
  bool IsBotControlled(uint16_t slot_index) const {
    auto it = bots_.find(slot_index);
    return it != bots_.end() && it->second.active;
  }

  // Generate SlotInput for a bot-controlled slot.
  // Called each frame by the server before StepWithInput.
  // Button indices match e_ButtonFunction enum:
  //   0=LongPass, 1=HighPass, 2=ShortPass, 3=Shot,
  //   4=KeeperRush, 5=Sliding, 6=Pressure, 7=TeamPressure,
  //   8=Switch, 9=Sprint, 10=Dribble
  SlotInput GenerateInput(uint16_t slot_index, const BotGameSnapshot& snapshot) {
    auto it = bots_.find(slot_index);
    if (it == bots_.end() || !it->second.active) {
      return SlotInput::Default();
    }

    BotState& bot = it->second;
    UpdatePlayerPosition(bot, slot_index, snapshot);

    SlotInput input;
    input.dir_x = 0.f;
    input.dir_y = 0.f;
    input.buttons = 0;

    float ball_dx = snapshot.ball_x - bot.last_player_x;
    float ball_dy = snapshot.ball_y - bot.last_player_y;
    float ball_dist = std::sqrt(ball_dx * ball_dx + ball_dy * ball_dy);

    // Determine if we're attacking or defending
    bool attacking = (bot.team == 0 && snapshot.ball_x > 0.f) ||
                     (bot.team == 1 && snapshot.ball_x < 0.f);

    if (attacking) {
      // Offensive: move toward ball, then toward goal
      if (ball_dist > 3.f) {
        // Move toward ball
        if (ball_dist > 0.01f) {
          input.dir_x = ball_dx / ball_dist;
          input.dir_y = ball_dy / ball_dist;
        }
        input.buttons |= (1u << 9);  // Sprint
      } else {
        // Near ball: move toward opponent goal
        float goal_x = (bot.team == 0) ? snapshot.goal_x_right : snapshot.goal_x_left;
        float goal_dx = goal_x - bot.last_player_x;
        float goal_dy = 0.f - bot.last_player_y;  // aim for center of goal
        float goal_dist = std::sqrt(goal_dx * goal_dx + goal_dy * goal_dy);
        if (goal_dist > 0.01f) {
          input.dir_x = goal_dx / goal_dist;
          input.dir_y = goal_dy / goal_dist;
        }
        input.buttons |= (1u << 9);  // Sprint

        // Shoot if close enough and cooldown is zero
        if (ball_dist < 8.f && goal_dist < 25.f && bot.shoot_cooldown <= 0) {
          input.buttons |= (1u << 3);  // Shot
          bot.shoot_cooldown = 30;  // ~3 seconds at 10 fps
        }
      }
    } else {
      // Defensive: move toward ball to intercept
      if (ball_dist > 0.01f) {
        input.dir_x = ball_dx / ball_dist;
        input.dir_y = ball_dy / ball_dist;
      }
      input.buttons |= (1u << 9);  // Sprint

      // Pressure when close to ball
      if (ball_dist < 5.f) {
        input.buttons |= (1u << 6);  // Pressure
      }

      // Clear if very close to own goal
      float own_goal_x = (bot.team == 0) ? snapshot.goal_x_left : snapshot.goal_x_right;
      float own_goal_dist = std::sqrt(
          (bot.last_player_x - own_goal_x) * (bot.last_player_x - own_goal_x) +
          bot.last_player_y * bot.last_player_y);
      if (own_goal_dist < 15.f && ball_dist < 5.f && bot.shoot_cooldown <= 0) {
        input.buttons |= (1u << 0);  // LongPass (clear)
        bot.shoot_cooldown = 40;
      }
    }

    if (bot.shoot_cooldown > 0) --bot.shoot_cooldown;

    return input;
  }

  // Get all bot-controlled slot indices
  std::vector<uint16_t> GetBotSlots() const {
    std::vector<uint16_t> result;
    for (const auto& [slot, bot] : bots_) {
      if (bot.active) result.push_back(slot);
    }
    return result;
  }

  int bot_count() const { return static_cast<int>(bots_.size()); }

 private:
  void UpdatePlayerPosition(BotState& bot, uint16_t slot_index,
                            const BotGameSnapshot& snapshot) {
    if (static_cast<int>(slot_index) < snapshot.num_slots) {
      bot.last_player_x = snapshot.player_positions[slot_index * 2];
      bot.last_player_y = snapshot.player_positions[slot_index * 2 + 1];
    }
    bot.last_ball_x = snapshot.ball_x;
    bot.last_ball_y = snapshot.ball_y;
  }

  std::unordered_map<uint16_t, BotState> bots_;
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_BOT_TAKEOVER_HPP
