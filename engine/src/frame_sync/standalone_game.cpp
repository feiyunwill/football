// 2026-09-13: standalone uses the shared product initial state.
// #include "frame_sync/native_client_loop.hpp"
#include "frame_sync/native_client_loop.hpp"
#include "frame_sync/native_match_scenario.hpp"
#include "frame_sync/native_presentation.hpp"
// Standalone single-player game: keyboard vs AI, no network required.
// Build: cmake --build . -j 1 --target standalone_game
// Run:   GFOOTBALL_DATA_DIR=../data ./standalone_game [--headless]

#include "game_env.hpp"
#include "main.hpp"
#include "gfootball_actions.h"
#include "frame_sync/standalone_controls.hpp"

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

// 2026-09-13: replaced legacy action-only and duplicate-presentation loop.
// int main(int argc, char* argv[]) {
//   bool render = true;
//   uint32_t seed = 42;
// 
//   for (int i = 1; i < argc; ++i) {
//     std::string arg = argv[i];
//     if (arg == "--headless") render = false;
//     if (arg == "--seed" && i + 1 < argc) seed = std::stoul(argv[++i]);
//   }
// 
//   fprintf(stderr, "Standalone Game (render=%s, seed=%u)\n",
//           render ? "on" : "off", seed);
//   fprintf(stderr,
//     "Keyboard controls:\n"
//     "  WASD / Arrow keys  - Move\n"
//     "  Z - Short pass     X - High pass     C - Long pass\n"
//     "  V - Shoot          B - Sliding        Space - Pressure\n"
//     "  Shift - Sprint     Tab - Switch       M - Dribble\n"
//     // 2026-09-09: pause keeps the current match; quitting explicitly ends it.
//     // "  ESC - Quit\n");
//     "  ESC / P - Pause or resume     Q - Quit\n");
// 
//   // ===== Init GameEnv =====
//   GameEnv env;
//   env.game_config.render = render;
//   env.game_config.physics_steps_per_frame = 10;
//   env.game_config.render_resolution_x = 1280;
//   env.game_config.render_resolution_y = 720;
// 
//   auto scenario = ScenarioConfig::make();
//   scenario->left_agents = 1;     // 1 human-controlled player
//   scenario->right_agents = 0;    // AI controls right team
//   scenario->game_engine_random_seed = seed;
//   scenario->real_time = false;
//   scenario->game_duration = 3000;
// 
//   // Full 4-4-2 formation
//   scenario->left_team = {
//     FormationEntry(0.0f,   0.0f,  e_PlayerRole_GK, false, true),
//     FormationEntry(-0.4f, -0.3f,  e_PlayerRole_LB, false, false),
//     FormationEntry(-0.15f,-0.3f,  e_PlayerRole_CB, false, false),
//     FormationEntry(0.15f, -0.3f,  e_PlayerRole_CB, false, false),
//     FormationEntry(0.4f,  -0.3f,  e_PlayerRole_RB, false, false),
//     FormationEntry(-0.4f, 0.0f,  e_PlayerRole_LM, false, false),
//     FormationEntry(-0.15f,0.0f,  e_PlayerRole_CM, false, false),
//     FormationEntry(0.15f, 0.0f,  e_PlayerRole_CM, false, false),
//     FormationEntry(0.4f,  0.0f,  e_PlayerRole_RM, false, false),
//     FormationEntry(-0.15f,0.3f,  e_PlayerRole_CF, false, false),
//     FormationEntry(0.15f, 0.3f,  e_PlayerRole_CF, false, false),
//   };
//   scenario->right_team = {
//     FormationEntry(0.0f,   0.0f,  e_PlayerRole_GK, false, true),
//     FormationEntry(-0.4f, -0.3f,  e_PlayerRole_LB, false, false),
//     FormationEntry(-0.15f,-0.3f,  e_PlayerRole_CB, false, false),
//     FormationEntry(0.15f, -0.3f,  e_PlayerRole_CB, false, false),
//     FormationEntry(0.4f,  -0.3f,  e_PlayerRole_RB, false, false),
//     FormationEntry(-0.4f, 0.0f,  e_PlayerRole_LM, false, false),
//     FormationEntry(-0.15f,0.0f,  e_PlayerRole_CM, false, false),
//     FormationEntry(0.15f, 0.0f,  e_PlayerRole_CM, false, false),
//     FormationEntry(0.4f,  0.0f,  e_PlayerRole_RM, false, false),
//     FormationEntry(-0.15f,0.3f,  e_PlayerRole_CF, false, false),
//     FormationEntry(0.15f, 0.3f,  e_PlayerRole_CF, false, false),
//   };
// 
//   try {
//     env.start_game(*scenario);
//     env.state = GameState::game_running;
//     fprintf(stderr, "GameEnv ready. Starting match...\n");
//   } catch (const std::exception& e) {
//     fprintf(stderr, "Failed to start game: %s\n", e.what());
//     return 1;
//   }
// 
//   // ===== Game loop =====
//   auto logic_period  = std::chrono::milliseconds(1000 / 10);   // 10 Hz logic
//   auto render_period = std::chrono::milliseconds(1000 / 60);   // 60 Hz render
// 
//   KeyboardState kb_state;
//   bool running = true;
//   int frame_count = 0;
//   auto fps_timer = std::chrono::steady_clock::now();
//   double current_fps = 0.0;
//   auto last_logic_time  = std::chrono::steady_clock::now();
//   auto last_render_time = std::chrono::steady_clock::now();
// 
//   while (running) {
//     auto now = std::chrono::steady_clock::now();
// 
//     // ===== SDL Events + Keyboard =====
//     if (render) {
//       SDL_Event event;
//       while (SDL_PollEvent(&event)) {
//         // 2026-09-09: use the same lifecycle event path exercised by integration tests.
//         // switch (event.type) {
//         //   case SDL_QUIT: running = false; break;
//         //   case SDL_KEYDOWN:
//         //     if (event.key.keysym.sym == SDLK_ESCAPE) running = false;
//         //     break;
//         // }
//         running = frame_sync::HandleStandaloneEvent(env, event);
//         if (!running) break;
//       }
//       if (!running) break;
//       const Uint8* keys = SDL_GetKeyboardState(nullptr);
//       kb_state.update(keys);
//     }
// 
//     // ===== Logic tick (10 Hz) =====
//     auto logic_elapsed = now - last_logic_time;
//     if (logic_elapsed >= logic_period) {
//       last_logic_time = now;
// 
//       // Apply keyboard input: direction to player 0, button action if pressed
//       if (render) {
//         int dir_action = kb_state.get_action();
//         env.action(dir_action, true, 0);
//         int btn = kb_state.get_button_action();
//         if (btn >= 0) env.action(btn, true, 0);
//       }
// 
//       // Step the game
//       env.step();
//       // 2026-09-09: native matches also end at their configured episode length.
//       if (env.get_info().step + 1 >= env.scenario_config.game_duration) {
//         env.finish();
//         break;
//       }
// 
//       // Save interpolation state for smooth rendering
//       if (render) {
//         // 2026-09-09: public env calls no longer leave an implicit TLS selection.
//         ContextHolder render_context(&env);
//         GetGameTask()->GetMatch()->SaveInterpolationState();
//       }
//     }
// 
//     // ===== Render (60 Hz) =====
//     auto render_elapsed = now - last_render_time;
//     if (render && render_elapsed >= render_period) {
//       last_render_time = now;
// 
//       float t = static_cast<float>(
//           std::chrono::duration<double>(render_elapsed).count()) /
//         static_cast<float>(
//           std::chrono::duration<double>(logic_period).count());
//       t = std::clamp(t, 0.0f, 1.0f);
// 
//       // 2026-09-09: select this environment for direct Match rendering calls.
//       ContextHolder render_context(&env);
//       GetGameTask()->GetMatch()->PutInterpolated(t);
//       env.render();
// 
//       frame_count++;
//       auto fps_now = std::chrono::steady_clock::now();
//       double fps_elapsed = std::chrono::duration<double>(fps_now - fps_timer).count();
//       if (fps_elapsed >= 1.0) {
//         current_fps = frame_count / fps_elapsed;
//         frame_count = 0;
//         fps_timer = fps_now;
// 
//         char title[128];
//         // 2026-09-09: visible pause state with the resume/quit controls.
//         // snprintf(title, sizeof(title), "Football | FPS: %.0f", current_fps);
//         snprintf(title, sizeof(title), env.state == game_paused ?
//                  "Football | Paused (P / Esc to resume, Q to quit)" : "Football | FPS: %.0f",
//                  current_fps);
//         SDL_Window* win = SDL_GL_GetCurrentWindow();
//         if (win) SDL_SetWindowTitle(win, title);
//       }
// 
//       SDL_Window* win = SDL_GL_GetCurrentWindow();
//       if (win) SDL_GL_SwapWindow(win);
//     }
// 
//     // ===== Sleep to avoid busy-wait =====
//     auto elapsed = std::chrono::steady_clock::now() - now;
//     auto min_period = std::min(logic_period, render_period);
//     if (elapsed < min_period)
//       std::this_thread::sleep_for(min_period - elapsed);
//   }
// 
//   fprintf(stderr, "Game over. Shutting down...\n");
//   return 0;
// }
int main(int argc, char* argv[]) {
  try {
    bool render = true;
    uint32_t seed = 42, frame_limit = 0;
    for (int i = 1; i < argc; ++i) {
      const std::string arg = argv[i];
      if (arg == "--headless") render = false;
      else if (arg == "--seed" && i + 1 < argc)
        seed = frame_sync::NativeNumber(argv[++i], UINT32_MAX);
      else if (arg == "--frames" && i + 1 < argc) {
        frame_limit = frame_sync::NativeNumber(argv[++i], UINT32_MAX - 1024);
        if (!frame_limit) throw std::invalid_argument("Frame limit must be positive");
      } else throw std::invalid_argument("usage: standalone [--headless] [--seed N] [--frames N]");
    }
    GameEnv env;
    env.game_config.render = render;
    // 2026-09-13: this display entry point never consumes CPU RGB observations.
    env.game_config.capture_frames = false;
    // 2026-09-13: two fixed 10 ms physics ticks per input.
    // env.game_config.physics_steps_per_frame = 10;
    env.game_config.physics_steps_per_frame = frame_sync::NativeMatchContract::kPhysicsSteps;
    env.game_config.render_resolution_x = 1280;
    env.game_config.render_resolution_y = 720;
    // 2026-09-13: use the canonical product formation, seed policy and 15000-frame duration.
    // auto scenario = ScenarioConfig::make();
    // scenario->left_agents = 1;     // 1 human-controlled player
    // scenario->right_agents = 0;    // AI controls right team
    // scenario->game_engine_random_seed = seed;
    // scenario->real_time = false;
    // scenario->game_duration = 3000;
    // 
    // // Full 4-4-2 formation
    // scenario->left_team = {
    //   FormationEntry(0.0f,   0.0f,  e_PlayerRole_GK, false, true),
    //   FormationEntry(-0.4f, -0.3f,  e_PlayerRole_LB, false, false),
    //   FormationEntry(-0.15f,-0.3f,  e_PlayerRole_CB, false, false),
    //   FormationEntry(0.15f, -0.3f,  e_PlayerRole_CB, false, false),
    //   FormationEntry(0.4f,  -0.3f,  e_PlayerRole_RB, false, false),
    //   FormationEntry(-0.4f, 0.0f,  e_PlayerRole_LM, false, false),
    //   FormationEntry(-0.15f,0.0f,  e_PlayerRole_CM, false, false),
    //   FormationEntry(0.15f, 0.0f,  e_PlayerRole_CM, false, false),
    //   FormationEntry(0.4f,  0.0f,  e_PlayerRole_RM, false, false),
    //   FormationEntry(-0.15f,0.3f,  e_PlayerRole_CF, false, false),
    //   FormationEntry(0.15f, 0.3f,  e_PlayerRole_CF, false, false),
    // };
    // scenario->right_team = {
    //   FormationEntry(0.0f,   0.0f,  e_PlayerRole_GK, false, true),
    //   FormationEntry(-0.4f, -0.3f,  e_PlayerRole_LB, false, false),
    //   FormationEntry(-0.15f,-0.3f,  e_PlayerRole_CB, false, false),
    //   FormationEntry(0.15f, -0.3f,  e_PlayerRole_CB, false, false),
    //   FormationEntry(0.4f,  -0.3f,  e_PlayerRole_RB, false, false),
    //   FormationEntry(-0.4f, 0.0f,  e_PlayerRole_LM, false, false),
    //   FormationEntry(-0.15f,0.0f,  e_PlayerRole_CM, false, false),
    //   FormationEntry(0.15f, 0.0f,  e_PlayerRole_CM, false, false),
    //   FormationEntry(0.4f,  0.0f,  e_PlayerRole_RM, false, false),
    //   FormationEntry(-0.15f,0.3f,  e_PlayerRole_CF, false, false),
    //   FormationEntry(0.15f, 0.3f,  e_PlayerRole_CF, false, false),
    // };
    // 
    // // 2026-09-13: preserve the product formation, but allow switching to field players.
    // // Previously only the two goalkeepers had controllable=true.
    // for (auto* team : {&scenario->left_team, &scenario->right_team})
    //   for (auto& entry : *team) entry.controllable = true;
    auto scenario = frame_sync::MakeNativeMatchScenario(frame_sync::NativeMatchContract(seed,1,0));
    env.start_game(*scenario);
    env.state = GameState::game_running;
    fprintf(stderr, "GameEnv ready. Starting match...\n");
    fprintf(stderr, "Controls: WASD/arrows move; Z/X/C pass; V shoot; Shift sprint; "
                    "Tab switch; M dribble; P/K/Escape pause; Q quit.\n");
// 2026-09-13: bind sampled input to fixed simulation deadlines.
//     frame_sync::NativeWindowInput window(env);
    // 2026-09-13: local history is shared with the SDL main thread.
    // frame_sync::NativeWindowInput window(env);
    frame_sync::NativeWindowInput window(env, true);
    window.Run([&] {
      auto& local_input = window.local_input();
      // 2026-09-13: presentation interval matches physical endpoints.
      // frame_sync::NativePresentation<GameEnv> presentation(env, render, std::chrono::milliseconds(100));
      frame_sync::NativePresentation<GameEnv> presentation(env, render, std::chrono::milliseconds(20));
      presentation.Initialize(frame_sync::NativeNow());
      // 2026-09-13: input sampling and physics run at product cadence.
      // frame_sync::NativeLoopClock clock(frame_sync::NativeNow(), 10, 60);
      frame_sync::NativeLoopClock clock(frame_sync::NativeNow(), frame_sync::NativeMatchContract::kHz, 60);
  // 2026-09-13: retain terminal state while draining a bounded group of fixed steps.
  //     uint32_t steps = 0;
      uint32_t steps = 0;
      bool finished = false;
      int pictures = 0;
      auto fps_start = frame_sync::NativeNow();
      while (true) {
        if (clock.PollDue(frame_sync::NativeNow())) {
          // 2026-09-13: window.Poll(true);
          window.Poll();
  // 2026-09-13: bind sampled input to fixed simulation deadlines.
  //         const auto commands = window.buffer().TakeCommands();
          const auto commands = local_input.TakeCommands();
          if (commands[0]) break;
          if (commands[1] || commands[2]) {
            if (env.state == game_paused) {
              env.resume();
  // 2026-09-13: bind sampled input to fixed simulation deadlines.
  //             window.buffer().SetSuspended(false);
              // 2026-09-13: local_input.SetSuspended(false, frame_sync::NativeNow());
              local_input.SetSuspended(false);
              presentation.Resume(frame_sync::NativeNow());
              clock.RestartLogic(frame_sync::NativeNow());
            } else {
              env.pause();
  // 2026-09-13: bind sampled input to fixed simulation deadlines.
  //             window.buffer().SetSuspended(true);
              // 2026-09-13: local_input.SetSuspended(true, frame_sync::NativeNow());
              local_input.SetSuspended(true);
              presentation.Pause(frame_sync::NativeNow());
            }
          }
        }
  // 2026-09-13: slow rendering must not discard elapsed simulation ticks; return to input after eight steps.
  //       if (env.state != game_paused && clock.LogicDue(frame_sync::NativeNow())) {
        for (unsigned work = 0; env.state != game_paused && work < 8 &&
             clock.FixedLogicDue(frame_sync::NativeNow()); ++work) {
  // 2026-09-13: bind sampled input to fixed simulation deadlines.
  //         const std::array<frame_sync::SlotInput, 1> inputs{window.buffer().Take()};
          const std::array<frame_sync::SlotInput, 1> inputs{local_input.Take(clock.LastFixedDeadline())};
          presentation.BeginTick(frame_sync::NativeNow());
          presentation.BeforeStep();
          env.StepWithInput(inputs.data(), sizeof(inputs));
          presentation.CommitTick(frame_sync::NativeNow());
          ++steps;
          if ((frame_limit && steps >= frame_limit) ||
              env.get_info().step + 1 >= env.scenario_config.game_duration) {
  // 2026-09-13: stop the outer owner once the bounded catchup reaches the final frame.
  //           env.finish();
  //           break;
            env.finish();
            finished = true;
            break;
          }
        }
  // 2026-09-13: drain simulation debt before another expensive draw; paused presentation continues.
  //       if (render && clock.RenderDue(frame_sync::NativeNow())) {
        if (finished) break;
        if (render && (env.state == game_paused || !clock.LogicPending(frame_sync::NativeNow())) &&
            clock.RenderDue(frame_sync::NativeNow())) {
  // 2026-09-13: sample UI input at bounded render work opportunities.
  //         presentation.Render(frame_sync::NativeNow());
          // 2026-09-13: window.Render([&] { presentation.Render(frame_sync::NativeNow()); }, true);
          window.Render([&] { presentation.Render(frame_sync::NativeNow()); });
          ++pictures;
          const auto now = frame_sync::NativeNow();
          if (now - fps_start >= 1000000000) {
            char title[128];
            snprintf(title, sizeof(title), env.state == game_paused ?
                "Football | Paused (P / K / Escape to resume)" : "Football | FPS: %.0f",
                pictures * 1000000000.0 / double(now - fps_start));
            window.Title(title);
            pictures = 0; fps_start = now;
          }
        }
        clock.Wait(env.state != game_paused, render);
      }
      fprintf(stderr, "Standalone session steps=%u\n", steps);
    });
    return 0;
  } catch (const std::exception& error) {
    fprintf(stderr, "Standalone game failed: %s\n", error.what());
    return 1;
  }
}
