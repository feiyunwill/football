// Standalone single-player game: keyboard vs AI, no network required.
// Build: cmake --build . -j 1 --target standalone_game
// Run:   GFOOTBALL_DATA_DIR=../data ./standalone_game [--headless]

#include "game_env.hpp"
#include "main.hpp"
#include "gfootball_actions.h"

#include <SDL.h>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <memory>
#include <string>
#include <algorithm>

// ===== Keyboard → SlotInput =====
struct KeyboardState {
  float dir_x = 0.f;
  float dir_y = 0.f;
  uint16_t buttons = 0;

  void update(const Uint8* keys) {
    dir_x = 0.f;
    dir_y = 0.f;
    if (keys[SDL_SCANCODE_LEFT]  || keys[SDL_SCANCODE_A]) dir_x -= 1.f;
    if (keys[SDL_SCANCODE_RIGHT] || keys[SDL_SCANCODE_D]) dir_x += 1.f;
    if (keys[SDL_SCANCODE_UP]    || keys[SDL_SCANCODE_W]) dir_y += 1.f;
    if (keys[SDL_SCANCODE_DOWN]  || keys[SDL_SCANCODE_S]) dir_y -= 1.f;

    float len = std::sqrt(dir_x * dir_x + dir_y * dir_y);
    if (len > 1.f) { dir_x /= len; dir_y /= len; }

    buttons = 0;
    if (keys[SDL_SCANCODE_Z]) buttons |= (1 << e_ButtonFunction_ShortPass);
    if (keys[SDL_SCANCODE_X]) buttons |= (1 << e_ButtonFunction_HighPass);
    if (keys[SDL_SCANCODE_C]) buttons |= (1 << e_ButtonFunction_LongPass);
    if (keys[SDL_SCANCODE_V]) buttons |= (1 << e_ButtonFunction_Shot);
    if (keys[SDL_SCANCODE_B]) buttons |= (1 << e_ButtonFunction_Sliding);
    if (keys[SDL_SCANCODE_LSHIFT] || keys[SDL_SCANCODE_RSHIFT])
      buttons |= (1 << e_ButtonFunction_Sprint);
    if (keys[SDL_SCANCODE_SPACE])
      buttons |= (1 << e_ButtonFunction_Pressure);
    if (keys[SDL_SCANCODE_TAB])
      buttons |= (1 << e_ButtonFunction_Switch);
    if (keys[SDL_SCANCODE_N])
      buttons |= (1 << e_ButtonFunction_TeamPressure);
    if (keys[SDL_SCANCODE_M])
      buttons |= (1 << e_ButtonFunction_Dribble);
  }

  // Apply keyboard state as a single action to the controlled player (index 0).
  // Direction: pick the best 8-directional match.
  // Buttons: fire the first pressed button action.
  int get_action() const {
    // Direction
    if (dir_x == 0.f && dir_y == 0.f) return game_idle;
    if (dir_x < -0.5f && dir_y > 0.5f) return game_top_left;
    if (dir_x > 0.5f && dir_y > 0.5f) return game_top_right;
    if (dir_x < -0.5f && dir_y < -0.5f) return game_bottom_left;
    if (dir_x > 0.5f && dir_y < -0.5f) return game_bottom_right;
    if (dir_y > 0.5f) return game_top;
    if (dir_y < -0.5f) return game_bottom;
    if (dir_x < -0.5f) return game_left;
    if (dir_x > 0.5f) return game_right;
    return game_idle;
  }

  int get_button_action() const {
    if (buttons & (1 << e_ButtonFunction_ShortPass))   return game_short_pass;
    if (buttons & (1 << e_ButtonFunction_HighPass))    return game_high_pass;
    if (buttons & (1 << e_ButtonFunction_LongPass))    return game_long_pass;
    if (buttons & (1 << e_ButtonFunction_Shot))        return game_shot;
    if (buttons & (1 << e_ButtonFunction_Sliding))     return game_sliding;
    if (buttons & (1 << e_ButtonFunction_Pressure))    return game_pressure;
    if (buttons & (1 << e_ButtonFunction_TeamPressure))return game_team_pressure;
    if (buttons & (1 << e_ButtonFunction_Switch))      return game_switch;
    if (buttons & (1 << e_ButtonFunction_Sprint))      return game_sprint;
    if (buttons & (1 << e_ButtonFunction_Dribble))     return game_dribble;
    return -1;
  }
};

int main(int argc, char* argv[]) {
  bool render = true;
  uint32_t seed = 42;

  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--headless") render = false;
    if (arg == "--seed" && i + 1 < argc) seed = std::stoul(argv[++i]);
  }

  fprintf(stderr, "Standalone Game (render=%s, seed=%u)\n",
          render ? "on" : "off", seed);
  fprintf(stderr,
    "Keyboard controls:\n"
    "  WASD / Arrow keys  - Move\n"
    "  Z - Short pass     X - High pass     C - Long pass\n"
    "  V - Shoot          B - Sliding        Space - Pressure\n"
    "  Shift - Sprint     Tab - Switch       M - Dribble\n"
    "  ESC - Quit\n");

  // ===== Init GameEnv =====
  GameEnv env;
  env.game_config.render = render;
  env.game_config.physics_steps_per_frame = 10;
  env.game_config.render_resolution_x = 1280;
  env.game_config.render_resolution_y = 720;

  auto scenario = ScenarioConfig::make();
  scenario->left_agents = 1;     // 1 human-controlled player
  scenario->right_agents = 0;    // AI controls right team
  scenario->game_engine_random_seed = seed;
  scenario->real_time = false;
  scenario->game_duration = 3000;

  // Full 4-4-2 formation
  scenario->left_team = {
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
  scenario->right_team = {
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

  try {
    env.start_game(*scenario);
    env.state = GameState::game_running;
    fprintf(stderr, "GameEnv ready. Starting match...\n");
  } catch (const std::exception& e) {
    fprintf(stderr, "Failed to start game: %s\n", e.what());
    return 1;
  }

  // ===== Game loop =====
  auto logic_period  = std::chrono::milliseconds(1000 / 10);   // 10 Hz logic
  auto render_period = std::chrono::milliseconds(1000 / 60);   // 60 Hz render

  KeyboardState kb_state;
  bool running = true;
  int frame_count = 0;
  auto fps_timer = std::chrono::steady_clock::now();
  double current_fps = 0.0;
  auto last_logic_time  = std::chrono::steady_clock::now();
  auto last_render_time = std::chrono::steady_clock::now();

  while (running) {
    auto now = std::chrono::steady_clock::now();

    // ===== SDL Events + Keyboard =====
    if (render) {
      SDL_Event event;
      while (SDL_PollEvent(&event)) {
        switch (event.type) {
          case SDL_QUIT:
            running = false;
            break;
          case SDL_KEYDOWN:
            if (event.key.keysym.sym == SDLK_ESCAPE) running = false;
            break;
        }
      }
      const Uint8* keys = SDL_GetKeyboardState(nullptr);
      kb_state.update(keys);
    }

    // ===== Logic tick (10 Hz) =====
    auto logic_elapsed = now - last_logic_time;
    if (logic_elapsed >= logic_period) {
      last_logic_time = now;

      // Apply keyboard input: direction to player 0, button action if pressed
      if (render) {
        int dir_action = kb_state.get_action();
        env.action(dir_action, true, 0);
        int btn = kb_state.get_button_action();
        if (btn >= 0) env.action(btn, true, 0);
      }

      // Step the game
      env.step();

      // Save interpolation state for smooth rendering
      if (render) {
        GetGameTask()->GetMatch()->SaveInterpolationState();
      }
    }

    // ===== Render (60 Hz) =====
    auto render_elapsed = now - last_render_time;
    if (render && render_elapsed >= render_period) {
      last_render_time = now;

      float t = static_cast<float>(
          std::chrono::duration<double>(render_elapsed).count()) /
        static_cast<float>(
          std::chrono::duration<double>(logic_period).count());
      t = std::clamp(t, 0.0f, 1.0f);

      GetGameTask()->GetMatch()->PutInterpolated(t);
      env.render();

      frame_count++;
      auto fps_now = std::chrono::steady_clock::now();
      double fps_elapsed = std::chrono::duration<double>(fps_now - fps_timer).count();
      if (fps_elapsed >= 1.0) {
        current_fps = frame_count / fps_elapsed;
        frame_count = 0;
        fps_timer = fps_now;

        char title[128];
        snprintf(title, sizeof(title), "Football | FPS: %.0f",
                 current_fps);
        SDL_Window* win = SDL_GL_GetCurrentWindow();
        if (win) SDL_SetWindowTitle(win, title);
      }

      SDL_Window* win = SDL_GL_GetCurrentWindow();
      if (win) SDL_GL_SwapWindow(win);
    }

    // ===== Sleep to avoid busy-wait =====
    auto elapsed = std::chrono::steady_clock::now() - now;
    auto min_period = std::min(logic_period, render_period);
    if (elapsed < min_period)
      std::this_thread::sleep_for(min_period - elapsed);
  }

  fprintf(stderr, "Game over. Shutting down...\n");
  return 0;
}
