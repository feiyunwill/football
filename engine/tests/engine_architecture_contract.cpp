// 2026-09-09: real match lifecycle, rejected API input and SDL host integration.
#include "frame_sync/default_scenario.hpp"
#include "frame_sync/standalone_controls.hpp"
#include "frame_sync/input_codec.hpp"
#include "game_env.hpp"

#include <SDL_ttf.h>
#include <GL/gl.h>
#include <climits>
#include <array>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

namespace {
int assertions = 0;
void Require(bool condition, const char* message) {
  ++assertions;
  if (!condition) throw std::runtime_error(message);
}
template<class Error = std::logic_error, class Function>
void Reject(Function function, const char* message) {
  bool rejected = false;
  try { function(); } catch (const Error&) { rejected = true; }
  Require(rejected, message);
  Require(GetGame() == nullptr, "Rejected API call leaked TLS selection");
}
void Start(GameEnv& environment, bool render, uint32_t seed) {
  environment.game_config.render = render;
  environment.game_config.render_resolution_x = 320;
  environment.game_config.render_resolution_y = 180;
  auto scenario = frame_sync::MakeDefaultScenario(1, 1, seed);
  environment.start_game(*scenario);
  environment.state = game_running;
}
void Step(GameEnv& environment, int frame) {
  environment.action(frame % 8 < 4 ? game_right : game_left, true, 0);
  if (frame % 7 == 0) environment.action(game_short_pass, true, 0);
  environment.step();
}

void Lifecycle(bool render, uint32_t seed) {
  const int fonts_before = TTF_WasInit();
  GameEnv environment;
  Reject([&] { environment.pause(); }, "Unstarted environment accepted pause");
  Reject([&] { environment.resume(); }, "Unstarted environment accepted resume");
  Reject([&] { environment.finish(); }, "Unstarted environment accepted finish");
  Start(environment, render, seed);
  // 2026-09-09: a stoppage clears touch history; observe kicks as they happen.
  // for (int frame = 0; frame < 60; ++frame) Step(environment, frame);
  bool kicked = false;
  for (int frame = 0; frame < 60; ++frame) {
    Step(environment, frame);
    ContextHolder selected(&environment);
    kicked |= environment.context->gameTask->GetMatch()->GetLastTouchTeamID(e_TouchType_Intentional_Kicked) >= 0;
  }
  {
    ContextHolder selected(&environment);
    auto* match = environment.context->gameTask->GetMatch();
    Require(match->GetActualTime_ms() >= 6000, "Real match pipeline did not run");
    // 2026-09-09: intentional touch must be seen during the flow, not only at its last frame.
    // Require(match->GetLastTouchTeamID(e_TouchType_Intentional_Kicked) >= 0,
    Require(kicked,
            "Match never produced an intentional ball kick");
  }
  const auto running = environment.get_state_digest();
  const auto step = environment.get_info().step;
  environment.pause();
  environment.pause();
  Require(environment.state == game_paused, "Pause did not transition state");
  const auto paused = environment.get_state_digest();
  const auto saved = environment.get_state("paused match");
  for (int attempt = 0; attempt < 10; ++attempt) {
    environment.action(game_sprint, true, 0);
    environment.step();
    environment.StepWithInput(nullptr, 0);
    if (render) environment.render();
    Require(environment.get_info().step == step, "Paused match advanced its logical frame");
    Require(environment.get_state_digest() == paused, "Paused match accepted input or changed simulation");
  }
  environment.resume();
  environment.resume();
  Require(environment.get_state_digest() == running, "Resume changed the pre-pause state");
  for (int frame = 60; frame < 80; ++frame) Step(environment, frame);
  const auto expected = environment.get_state_digest();
  Require(environment.set_state(saved) == "paused match", "Paused snapshot metadata was lost");
  Require(environment.state == game_paused, "Snapshot lost the paused lifecycle state");
  environment.step();
  Require(environment.get_state_digest() == paused, "Restored paused match continued ticking");
  environment.resume();
  for (int frame = 60; frame < 80; ++frame) Step(environment, frame);
  Require(environment.get_state_digest() == expected, "Pause/restore altered the subsequent trajectory");
  environment.finish();
  environment.finish();
  const auto ended = environment.get_state_digest();
  Require(environment.state == game_done, "Finish did not transition state");
  Reject([&] { environment.step(); }, "Finished match accepted a step");
  Reject([&] { environment.StepWithInput(nullptr, 0); }, "Finished match accepted authoritative input");
  Reject([&] { environment.action(game_right, true, 0); }, "Finished match accepted an action");
  Reject([&] { environment.pause(); }, "Finished match could be paused");
  Reject([&] { environment.resume(); }, "Finished match could be resumed");
  Require(environment.get_state_digest() == ended, "Rejected calls mutated the finished match");
  Require(environment.get_info().left_team.size() == 11, "Finished observation is unavailable");
  if (render) {
    environment.render();
    Require(environment.get_frame().size() == 320 * 180 * 3, "Finished match cannot be rendered");
  }
  auto scenario = frame_sync::MakeDefaultScenario(1, 1, seed);
  environment.reset(*scenario, false);
  Require(environment.state == game_running, "Reset did not restart a finished match");
  Step(environment, 0);
  environment.close();
  environment.close();
  Require(!environment.context && GetGame() == nullptr, "Destroy retained a selected context");
  Require(TTF_WasInit() == fonts_before, "Lifecycle leaked font subsystem ownership");
}

void InvalidInputs() {
  GameEnv environment;
  Start(environment, false, 42);
  Step(environment, 0);
  const auto before = environment.get_state_digest();
  for (bool left : {false, true}) {
    for (int player : {INT_MIN, -1, MAX_PLAYERS, INT_MAX}) {
      Reject<std::out_of_range>([&] { environment.action(game_right, left, player); }, "Invalid action slot accepted");
      Reject<std::out_of_range>([&] { environment.sticky_action_state(game_right, left, player); }, "Invalid sticky slot accepted");
    }
    for (int action : {INT_MIN, -1, int(game_builtin_ai) + 1, INT_MAX}) {
      Reject<std::invalid_argument>([&] { environment.action(action, left, 0); }, "Unknown action accepted");
      Reject<std::invalid_argument>([&] { environment.sticky_action_state(action, left, 0); }, "Unknown sticky action accepted");
    }
  }
  Reject<std::invalid_argument>([&] { environment.sticky_action_state(game_shot, true, 0); }, "Non-sticky action accepted");
  std::array<frame_sync::SlotInput, 2> slots{};
  Reject<std::invalid_argument>([&] { environment.StepWithInput(nullptr, sizeof(slots)); }, "Null authoritative frame accepted");
  for (size_t size : {size_t(0), sizeof(slots) - 1, sizeof(slots) + 1})
    Reject<std::invalid_argument>([&] { environment.StepWithInput(slots.data(), size); }, "Malformed authoritative frame accepted");
  slots[0].dir_x = 1;
  for (float invalid : {2.f, std::numeric_limits<float>::infinity(), std::numeric_limits<float>::quiet_NaN()}) {
    slots[1].dir_y = invalid;
    Reject<std::invalid_argument>([&] { environment.StepWithInput(slots.data(), sizeof(slots)); }, "Invalid final slot accepted");
    Require(environment.get_state_digest() == before, "Invalid later slot partially applied the frame");
  }
  slots[1].dir_y = 0;
  slots[1].buttons = 0x8000;
  Reject<std::invalid_argument>([&] { environment.StepWithInput(slots.data(), sizeof(slots)); }, "Unknown button bits accepted");
  Require(environment.get_state_digest() == before, "Rejected frame changed simulation or input");
  const std::vector<std::function<void(ScenarioConfig&)>> invalid_scenarios = {
      [](auto& config) { config.left_team.clear(); },
      [](auto& config) { config.right_team.resize(12); },
      [](auto& config) { config.left_agents = -1; },
      [](auto& config) { config.right_agents = INT_MAX; },
      [](auto& config) { for (auto& player : config.left_team) player.controllable = false; },
      [](auto& config) { config.ball_position.coords[0] = std::numeric_limits<float>::infinity(); },
      [](auto& config) { config.left_team[0].position.coords[1] = std::numeric_limits<float>::quiet_NaN(); },
      [](auto& config) { config.right_team_difficulty = -1; },
      [](auto& config) { config.game_duration = 0; },
  };
  for (const auto& invalidate : invalid_scenarios) {
    auto scenario = frame_sync::MakeDefaultScenario(1, 1, 42);
    invalidate(*scenario);
    Reject<std::invalid_argument>([&] { environment.reset(*scenario, false); }, "Invalid scenario destroyed live match");
    Require(environment.get_state_digest() == before, "Rejected reset changed the existing match");
    GameEnv unstarted;
    Reject<std::invalid_argument>([&] { unstarted.start_game(*scenario); }, "Invalid startup scenario accepted");
    Require(unstarted.context == nullptr, "Invalid configuration created partial resources");
  }
  for (int invalid : {-1, 0, INT_MAX}) {
    environment.game_config.physics_steps_per_frame = invalid;
    Reject<std::invalid_argument>([&] { environment.step(); }, "Invalid physics step count accepted");
    Reject<std::invalid_argument>([&] { environment.get_info(); }, "Observation used an invalid timestep");
  }
  environment.game_config.physics_steps_per_frame = 10;
  Require(environment.get_state_digest() == before, "Rejected configuration mutated simulation");
  for (int invalid : {0, -1, INT_MAX}) {
    GameEnv unstarted;
    unstarted.game_config.render_resolution_x = invalid;
    Reject<std::invalid_argument>([&] { unstarted.start_game(); }, "Invalid resolution accepted");
    Require(unstarted.context == nullptr, "Invalid resolution created a context");
  }
  Step(environment, 1);
  Require(environment.get_state_digest() != before, "Valid match could not continue after rejected calls");
}

void StartupFailure(const std::string& failure) {
  const int fonts_before = TTF_WasInit();
  GameEnv environment;
  environment.game_config.render = failure == "sdl";
  environment.game_config.render_resolution_x = 320;
  environment.game_config.render_resolution_y = 180;
  // The parent supplies an isolated invalid font or SDL driver, in this process only.
  Reject<std::runtime_error>([&] { environment.start_game(); }, "Broken startup did not propagate an exception");
  Require(!environment.context, "Failed startup retained partial resources");
  Require(TTF_WasInit() == fonts_before, "Failed startup leaked font initialization");
  unsetenv("GFOOTBALL_FONT");
  unsetenv("SDL_VIDEODRIVER");
  Start(environment, false, 42);
  Step(environment, 0);
  environment.close();
  Require(TTF_WasInit() == fonts_before, "Retry after failed startup leaked resources");
}

void SdlEvents() {
  GameEnv environment;
  // 2026-09-09: non-four-byte RGB rows exercise real screenshot buffer bounds.
  // Start(environment, true, 42);
  environment.game_config.render = true;
  environment.game_config.render_resolution_x = 321;
  environment.game_config.render_resolution_y = 181;
  auto scenario = frame_sync::MakeDefaultScenario(1, 1, 42);
  environment.start_game(*scenario);
  environment.state = game_running;
  Step(environment, 0);
  Require(environment.get_frame().size() == 321 * 181 * 3, "SDL screenshot contains row padding");
  {
    ContextHolder selected(&environment);
    Require(SDL_GL_GetCurrentWindow() != nullptr, "SDL path did not create an actual window/context");
    Require(glGetError() == GL_NO_ERROR, "SDL initialization produced a GL error");
  }
  SDL_FlushEvents(SDL_FIRSTEVENT, SDL_LASTEVENT);
  auto event = [&](Uint32 type, SDL_Keycode key, Uint8 repeat = 0) {
    SDL_Event input{};
    input.type = type;
    input.key.keysym.sym = key;
    input.key.repeat = repeat;
    Require(SDL_PushEvent(&input) == 1, "SDL rejected an injected host event");
    SDL_Event received{};
    bool found = false, running = true;
    while (SDL_PollEvent(&received)) {
      if (received.type == type) found = true;
      running = frame_sync::HandleStandaloneEvent(environment, received);
      if (!running) break;
    }
    Require(found, "Real SDL event queue did not deliver the event");
    return running;
  };
  const auto before = environment.get_state_digest();
  Require(event(SDL_KEYDOWN, SDLK_ESCAPE), "Pause exited the application");
  Require(environment.state == game_paused, "Escape did not pause the match");
  Require(event(SDL_KEYDOWN, SDLK_ESCAPE, 1), "Key repeat exited the application");
  Require(environment.state == game_paused, "Key repeat toggled pause");
  environment.step();
  environment.render();
  Require(event(SDL_KEYDOWN, SDLK_p), "Resume exited the application");
  Require(environment.get_state_digest() == before, "SDL pause/resume changed simulation");
  Require(!event(SDL_QUIT, 0), "Window close did not stop the application");
  Require(environment.state == game_done, "SDL close did not end the match");
  environment.close();
  Require(GetGame() == nullptr, "SDL teardown left a selected environment");
}

void HalfTime() {
  GameEnv environment;
  auto scenario = frame_sync::MakeDefaultScenario(0, 0, 42);
  scenario->second_half = 3;
  environment.start_game(*scenario);
  environment.state = game_running;
  bool reached_second_half = false;
  for (int frame = 0; frame < 80; ++frame) {
    environment.step();
    ContextHolder selected(&environment);
    reached_second_half |= environment.context->gameTask->GetMatch()->GetMatchPhase() == e_MatchPhase_2ndHalf;
  }
  Require(reached_second_half, "Configured half time never switched match phase");
  auto restored = frame_sync::MakeDefaultScenario(0, 0, 42);
  environment.reset(*restored, false);
  for (int frame = 0; frame < 80; ++frame) environment.step();
  ContextHolder selected(&environment);
  Require(environment.context->gameTask->GetMatch()->GetMatchPhase() == e_MatchPhase_1stHalf,
          "Disabled-half sentinel caused an early half-time transition");
}

void AuthoritativeInputEquivalence() {
  GameEnv direct, framed;
  auto scenario = frame_sync::MakeDefaultScenario(2, 2, 42);
  for (auto* environment : {&direct, &framed}) {
    environment->start_game(*scenario);
    environment->state = game_running;
  }
  std::array<frame_sync::SlotInput, 4> inputs{};
  for (int frame = 0; frame < 40; ++frame) {
    for (bool left : {false, true}) {
      for (int player = 0; player < 2; ++player) {
        direct.action((frame + player) % 2 ? game_left : game_right, left, player);
        if ((frame + player) % 7 == 0) direct.action(game_short_pass, left, player);
      }
    }
    {
      ContextHolder selected(&direct);
      Require(frame_sync::EncodeFrameInput(direct.context->controllers, 2, 2, inputs.data(), sizeof(inputs)) == sizeof(inputs),
              "Encoding live local controllers lost slots");
    }
    framed.StepWithInput(inputs.data(), sizeof(inputs));
    direct.step();
    Require(framed.get_state_digest() == direct.get_state_digest(),
            "Authoritative frame differs from equivalent local controller actions");
  }
  ContextHolder selected(&framed);
  Require(!framed.context->controllers[0]->Disabled() && !framed.context->controllers[MAX_PLAYERS]->Disabled(),
          "Authoritative input left its assigned controllers in builtin-AI mode");
}
}  // namespace

int main(int argc, char** argv) {
  try {
    const std::string mode = argc > 1 ? argv[1] : "headless";
    if (mode == "sdl") SdlEvents();
    else if (mode == "font-failure" || mode == "sdl-failure")
      StartupFailure(mode == "sdl-failure" ? "sdl" : "font");
    else {
      Lifecycle(mode == "render", argc > 2 ? std::stoul(argv[2]) : 42);
      // 2026-09-09: cover both the sentinel and a real half-time transition.
      // if (mode == "headless") InvalidInputs();
      // 2026-09-09: compare the complete local and authoritative input routes.
      // if (mode == "headless") { InvalidInputs(); HalfTime(); }
      if (mode == "headless") { InvalidInputs(); HalfTime(); AuthoritativeInputEquivalence(); }
    }
    std::cout << "{\"passed\":true,\"assertions\":" << assertions << ",\"skipped\":0}" << std::endl;
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Architecture contract: " << error.what() << std::endl;
    return 1;
  }
}
