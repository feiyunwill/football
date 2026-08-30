// Copyright 2019 Google LLC & Contributors
// Headless match runner: runs AI vs AI match without rendering.
// Verifies the engine + AI can play complete matches without crash.
// Usage: ./headless_match [left_agents] [right_agents] [seed] [num_frames]

#include "game_env.hpp"
#include "main.hpp"

#include <chrono>
#include <iostream>
#include <print>

int main(int argc, char* argv[]) {
  uint16_t left = 1;
  uint16_t right = 1;
  uint32_t seed = 42;
  int num_frames = 3000;  // 5 minutes at 10 fps

  if (argc >= 2) left = static_cast<uint16_t>(std::stoi(argv[1]));
  if (argc >= 3) right = static_cast<uint16_t>(std::stoi(argv[2]));
  if (argc >= 4) seed = static_cast<uint32_t>(std::stoul(argv[3]));
  if (argc >= 5) num_frames = std::stoi(argv[4]);

  std::println("Headless match: {}v{}, seed={}, frames={}", left, right, seed, num_frames);

  // Initialize game environment (headless)
  GameEnv env;
  env.game_config.render = false;
  env.game_config.physics_steps_per_frame = 10;
  env.game_config.render_resolution_x = 1280;
  env.game_config.render_resolution_y = 720;

  try {
    env.start_game();

    auto scenario = ScenarioConfig::make();
    scenario->left_agents = left;
    scenario->right_agents = right;
    scenario->game_engine_random_seed = seed;
    scenario->real_time = false;

    env.reset(*scenario, false);
    env.state = GameState::game_running;

    std::println("GameEnv initialized. Running match...");

    auto start_time = std::chrono::steady_clock::now();

    for (int i = 0; i < num_frames; ++i) {
      env.step();

      // Print progress every 500 frames
      if ((i + 1) % 500 == 0) {
        auto elapsed = std::chrono::steady_clock::now() - start_time;
        auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count();
        float fps = (i + 1) * 1000.0f / elapsed_ms;
        std::println("  Frame {}/{} ({:.1f} fps)", i + 1, num_frames, fps);
      }
    }

    auto total_time = std::chrono::steady_clock::now() - start_time;
    auto total_ms = std::chrono::duration_cast<std::chrono::milliseconds>(total_time).count();

    std::println("\n===== Match Complete =====");
    std::println("Duration: {:.1f}s ({:.1f} fps)", total_ms / 1000.0f,
                 num_frames * 1000.0f / total_ms);
    std::println("All {} frames completed without crash.", num_frames);

    return 0;

  } catch (const std::exception& e) {
    std::cerr << "Error: " << e.what() << std::endl;
    return 1;
  }
}
