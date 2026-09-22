#include "systems/graphics/render_service.hpp"
#include "game_load.hpp"
// Copyright 2019 Google LLC & Bastiaan Konings
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#undef NDEBUG

#include "game_env.hpp"

#include <fenv.h>

#include <cerrno>
#include <chrono>
#include <ctime>
#include <iostream>
#include <ratio>
#include <stdexcept>
// 2026-09-10: printable HUD text validation uses std::any_of directly.
#include <algorithm>
#include <cmath>
#include "frame_sync/default_scenario.hpp"

#include "ai/ai_keyboard.hpp"
#include "file.h"
#include "frame_sync/input_codec.hpp"
#include "gametask.hpp"

using std::string;

namespace {
// 2026-09-09: reject caller errors before allocating or mutating a live match.
void ValidateRuntimeConfig(const GameConfig& config) {
  if (config.physics_steps_per_frame < 1 || config.physics_steps_per_frame > 1000)
    throw std::invalid_argument("physics_steps_per_frame must be in [1, 1000]");
  if (config.render_resolution_x < 1 || config.render_resolution_y < 1 ||
      config.render_resolution_x > 8192 || config.render_resolution_y > 8192 ||
      int64_t(config.render_resolution_x) * config.render_resolution_y > 16777216)
    throw std::invalid_argument("Render resolution exceeds the supported pixel budget");
}

void ValidateScenario(const ScenarioConfig& scenario) {
  auto valid_position = [](const Vector3& value) {
    for (int axis = 0; axis < 3; ++axis)
      if (!std::isfinite(value.coords[axis]) || std::abs(value.coords[axis]) > 10)
        throw std::invalid_argument("Scenario coordinates must be finite and within ten field units");
  };
  auto valid_team = [&](const std::vector<FormationEntry>& team, int agents) {
    if (team.empty() || team.size() > MAX_PLAYERS || agents < 0 || agents > MAX_PLAYERS)
      throw std::invalid_argument("Scenario requires 1..11 players and 0..11 agents per team");
    int controllable = 0;
    for (const auto& player : team) {
      valid_position(player.position);
      valid_position(player.start_position);
      if (!SnapshotEnumValid(player.role, static_cast<int>(player.role)))
        throw std::invalid_argument("Invalid player role");
      controllable += player.controllable;
    }
    if (agents > controllable)
      throw std::invalid_argument("Scenario has fewer controllable players than agents");
  };
  valid_position(scenario.ball_position);
  valid_team(scenario.left_team, scenario.left_agents);
  valid_team(scenario.right_team, scenario.right_agents);
  for (float difficulty : {scenario.left_team_difficulty, scenario.right_team_difficulty})
    if (!std::isfinite(difficulty) || difficulty < 0 || difficulty > 1)
      throw std::invalid_argument("Team difficulty must be in [0, 1]");
  if (scenario.game_duration < 1 || scenario.second_half < 0)
    throw std::invalid_argument("Scenario duration must be positive and half time nonnegative");
}

void ValidateAction(int action, int player) {
  if (player < 0 || player >= MAX_PLAYERS)
    throw std::out_of_range("Controller slot must be in [0, 10]");
  if (action < game_idle || action > game_builtin_ai)
    throw std::invalid_argument("Unknown action");
}
// 2026-09-14: a prepared SDL/runtime context does not yet own a match.
// Call only while ContextHolder owns this environment's recursive mutex.
void RequireInitializedMatch(const GameEnv& env) {
  if (!env.context->gameTask || !env.context->gameTask->GetMatch())
    throw std::logic_error("Match is not initialized; reset before using match APIs");
}

}  // namespace

// 2026-09-09: the selected engine is scoped to an API call, including nesting.
ContextHolder::ContextHolder(GameEnv* game)
    : game_(game), previous_(GetGame()), lock_(game->mutex_) {
  if (!game_->context) throw std::logic_error("Game environment is not started");
  SetGame(game_);
  if (previous_ != game_) game_->context->graphicsSystem.SetContext();
}

ContextHolder::~ContextHolder() {
  if (previous_ == game_ && game_->context) return;
  if (game_->context) game_->context->graphicsSystem.DisableContext();
  SetGame(previous_ == game_ ? nullptr : previous_);
  if (auto* graphics = GetGraphicsSystem()) graphics->SetContext();
}

GameEnv::~GameEnv() { close(); }

void GameEnv::pause() {
  ContextHolder guard(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  if (state == game_paused) return;
  if (state != game_running) throw std::logic_error("Only a running match can be paused");
  state = game_paused;
}

void GameEnv::resume() {
  ContextHolder guard(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  if (state == game_running) return;
  if (state != game_paused) throw std::logic_error("Only a paused match can be resumed");
  state = game_running;
}

void GameEnv::finish() {
  ContextHolder guard(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  state = game_done;
}

void GameEnv::close() noexcept {
  std::lock_guard lock(mutex_);
  if (!context) return;
  GameEnv* previous = GetGame();
  SetGame(this);
  context->tracker_disabled = 1;
  context->graphicsSystem.SetContext();
  quit_game();
  delete context;
  context = nullptr;
  keyboard_ = nullptr;
  state = game_done;
  waiting_for_game_count = 0;
  last_step_rendered_frames_ = 1;
  SetGame(previous == this ? nullptr : previous);
  if (auto* graphics = GetGraphicsSystem()) graphics->SetContext();
}

void GameEnv::do_step(int count) {
  DO_VALIDATION;
  while (count--) {
    DO_VALIDATION;
    context->gameTask->ProcessPhase();
  }
  if (context->gameTask->GetMatch()->IsInPlay()) {
    DoValidation(__LINE__, __FILE__);
  }
}

float Position::env_coord(int index) const {
  switch (index) {
    DO_VALIDATION;
    case 0:
      return value[0] / X_FIELD_SCALE;
    case 1:
      return value[1] / Y_FIELD_SCALE;
    case 2:
      return value[2] / Z_FIELD_SCALE;
    default:
      Log(e_FatalError, "football", "main", "index out of range");
      return 0;
  }
}

std::string Position::debug() {
  DO_VALIDATION;
  return std::to_string(value[0]) + "," + std::to_string(value[1]) + "," +
         std::to_string(value[2]);
}

void GameEnv::setConfig(ScenarioConfig& scenario_config) {
  DO_VALIDATION;
  // 2026-09-09: scale an owned copy; repeated reset must not scale caller data twice.
  // scenario_config.ball_position.coords[0] *= X_FIELD_SCALE;
  // scenario_config.ball_position.coords[1] *= Y_FIELD_SCALE;
  this->scenario_config = scenario_config;
  this->scenario_config.cache_computed = false;
  this->scenario_config.ball_position.coords[0] *= X_FIELD_SCALE;
  this->scenario_config.ball_position.coords[1] *= Y_FIELD_SCALE;
  std::vector<SideSelection> setup = GetMenuTask()->GetControllerSetup();
  CHECK(setup.size() == 2 * MAX_PLAYERS);
  int controller = 0;
  for (int x = 0; x < scenario_config.left_agents; x++) {
    DO_VALIDATION;
    setup[controller++].side = -1;
  }
  while (controller < MAX_PLAYERS) {
    DO_VALIDATION;
    setup[controller++].side = 0;
  }
  for (int x = 0; x < scenario_config.right_agents; x++) {
    DO_VALIDATION;
    setup[controller++].side = 1;
  }
  while (controller < 2 * MAX_PLAYERS) {
    DO_VALIDATION;
    setup[controller++].side = 0;
  }
  // 2026-09-09: the owned configuration was assigned before coordinate conversion.
  // this->scenario_config = scenario_config;
  GetMenuTask()->SetControllerSetup(setup);
}

// 2026-09-09: both startup paths share initialization and a valid default formation.
// void GameEnv::start_game() {
//   assert(context == nullptr);
//   install_stacktrace();
//   std::cout.precision(17);
//   context = new GameContext();
//   ContextHolder c(this);
//   // feenableexcept(FE_INVALID | FE_DIVBYZERO | FE_OVERFLOW);
//   std::cout << std::unitbuf;
//
//   char* data_dir = getenv("GFOOTBALL_DATA_DIR");
//   if (data_dir) {
//     DO_VALIDATION;
//     GetGameConfig().data_dir = data_dir;
//   }
//   // 2026-08-31: Auto-detect data_dir and font when env vars are not set.
//   // Search relative to executable location and common relative paths.
//   if (GetGameConfig().data_dir.empty()) {
//     // Try common relative paths from build directories
//     const char* candidates[] = {
//       "data",                          // build_integration/data
//       "../data",                        // build_integration/../data
//       "../../data",                     // deeper nested build dirs
//       "engine/data",                    // from repo root
//     };
//     for (auto candidate : candidates) {
//       namespace fs = std::filesystem;
//       if (fs::exists(fs::path(candidate) / "media")) {
//         GetGameConfig().data_dir = fs::absolute(candidate).string();
//         break;
//       }
//     }
//   }
//   Properties* config = new Properties();
//   config->Set("match_duration", 0.027);
//   char* font_file = getenv("GFOOTBALL_FONT");
//   if (font_file) {
//     DO_VALIDATION;
//     config->Set("font_filename", font_file);
//   } else {
//     // Try to find the font file relative to data_dir
//     namespace fs = std::filesystem;
//     std::string font_path = "media/fonts/alegreya/AlegreyaSansSC-ExtraBold.ttf";
//     std::string full_path = GetGameConfig().updatePath(font_path);
//     if (fs::exists(full_path)) {
//       config->Set("font_filename", full_path);
//     }
//   }
//   config->Set("game", 0);
//   run_game(config, game_config.render);
//   auto scenario_config = ScenarioConfig::make();
//   reset(*scenario_config, false);
//   DO_VALIDATION;
// }
//
void GameEnv::start_game() {
  auto scenario = frame_sync::MakeDefaultScenario(1, 0, 42);
  start_game(*scenario);
}

// 2026-09-14: preserve the original atomic startup as a compatibility wrapper.
// 
// void GameEnv::start_game(ScenarioConfig& scenario_config) {
//   // 2026-09-09: double start reports an API error without corrupting the live game.
//   // assert(context == nullptr);
//   std::lock_guard lock(mutex_);
//   if (context) throw std::logic_error("Game environment is already started");
//   ValidateRuntimeConfig(game_config);
//   ValidateScenario(scenario_config);
//   state = game_created;
//   // 2026-09-09: a library must not replace its host/sanitizer's signal handlers.
//   // install_stacktrace();
//   std::cout.precision(17);
//   context = new GameContext();
//   try {
//   ContextHolder c(this);
//   std::cout << std::unitbuf;
// 
//   char* data_dir = getenv("GFOOTBALL_DATA_DIR");
//   if (data_dir) {
//     DO_VALIDATION;
//     GetGameConfig().data_dir = data_dir;
//   }
//   if (GetGameConfig().data_dir.empty()) {
//     const char* candidates[] = {
//       "data",
//       "../data",
//       "../../data",
//       "engine/data",
//     };
//     for (auto candidate : candidates) {
//       namespace fs = std::filesystem;
//       if (fs::exists(fs::path(candidate) / "media")) {
//         GetGameConfig().data_dir = fs::absolute(candidate).string();
//         break;
//       }
//     }
//   }
//   Properties* config = new Properties();
//   config->Set("match_duration", 0.027);
//   char* font_file = getenv("GFOOTBALL_FONT");
//   if (font_file) {
//     DO_VALIDATION;
//     config->Set("font_filename", font_file);
//   } else {
//     namespace fs = std::filesystem;
//     std::string font_path = "media/fonts/alegreya/AlegreyaSansSC-ExtraBold.ttf";
//     std::string full_path = GetGameConfig().updatePath(font_path);
//     if (fs::exists(full_path)) {
//       config->Set("font_filename", full_path);
//     }
//   }
//   config->Set("game", 0);
//   run_game(config, game_config.render);
//   // Use the caller's scenario_config directly — single reset(), no double-reset crash.
//   reset(scenario_config, false);
//   DO_VALIDATION;
//   } catch (...) {
//     close();
//     throw;
//   }
// }

void GameEnv::prepare_game(ScenarioConfig& scenario_config) {
  // 2026-09-09: double start reports an API error without corrupting the live game.
  // assert(context == nullptr);
  std::lock_guard lock(mutex_);
  if (context) throw std::logic_error("Game environment is already started");
  ValidateRuntimeConfig(game_config);
  ValidateScenario(scenario_config);
  state = game_created;
  // 2026-09-09: a library must not replace its host/sanitizer's signal handlers.
  // install_stacktrace();
  std::cout.precision(17);
  context = new GameContext();
  try {
  ContextHolder c(this);
  std::cout << std::unitbuf;

  char* data_dir = getenv("GFOOTBALL_DATA_DIR");
  if (data_dir) {
    DO_VALIDATION;
    GetGameConfig().data_dir = data_dir;
  }
  if (GetGameConfig().data_dir.empty()) {
    const char* candidates[] = {
      "data",
      "../data",
      "../../data",
      "engine/data",
    };
    for (auto candidate : candidates) {
      namespace fs = std::filesystem;
      if (fs::exists(fs::path(candidate) / "media")) {
        GetGameConfig().data_dir = fs::absolute(candidate).string();
        break;
      }
    }
  }
  Properties* config = new Properties();
  config->Set("match_duration", 0.027);
  char* font_file = getenv("GFOOTBALL_FONT");
  if (font_file) {
    DO_VALIDATION;
    config->Set("font_filename", font_file);
  } else {
    namespace fs = std::filesystem;
    std::string font_path = "media/fonts/alegreya/AlegreyaSansSC-ExtraBold.ttf";
    std::string full_path = GetGameConfig().updatePath(font_path);
    if (fs::exists(full_path)) {
      config->Set("font_filename", full_path);
    }
  }
  config->Set("game", 0);
  run_game(config, game_config.render);
  // 2026-09-14: match loading runs later on the game/GL worker, after UI service starts.
  DO_VALIDATION;
  } catch (...) {
    close();
    throw;
  }
}

void GameEnv::start_game(ScenarioConfig& scenario_config) {
  std::lock_guard lock(mutex_);
  prepare_game(scenario_config);
  try {
    reset(scenario_config, false);
  } catch (...) {
    close();
    throw;
  }
}

SharedInfo GameEnv::get_info() {
  // 2026-09-09: every public operation selects and restores its own environment.
  ContextHolder guard(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  ValidateRuntimeConfig(game_config);
  GetTracker()->setDisabled(true);
  SharedInfo info;
  GetGameTask()->GetMatch()->GetState(&info);
  info.step = context->step;
  GetTracker()->setDisabled(false);
  return info;
}

screenshoot GameEnv::get_frame() {
  // 2026-09-13: enforce the same capture contract for real and headless renderers.
  if (!game_config.capture_frames)
    throw std::logic_error("Frame capture is disabled");
  // 2026-09-09: scoped environment selection.
  // SetGame(this);
  ContextHolder guard(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  return GetGraphicsSystem()->GetScreen();
}

bool GameEnv::sticky_action_state(int action, bool left_team, int player) {
  // 2026-09-09: scoped environment selection.
  // SetGame(this);
  ContextHolder guard(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  ValidateAction(action, player);
  // 2026-09-09: validate the slot before indexing either controller bank.
  // int controller_id = player + (left_team ? 0 : 11);
  int controller_id = player + (left_team ? 0 : MAX_PLAYERS);
  auto controller =
      static_cast<AIControlledKeyboard*>(GetControllers()[controller_id]);
  switch (Action(action)) {
    case game_left:
      return controller->GetOriginalDirection() == Vector3(-1, 0, 0);
    case game_top_left:
      return controller->GetOriginalDirection() == Vector3(-1, 1, 0);
    case game_top:
      return controller->GetOriginalDirection() == Vector3(0, 1, 0);
    case game_top_right:
      return controller->GetOriginalDirection() == Vector3(1, 1, 0);
    case game_right:
      return controller->GetOriginalDirection() == Vector3(1, 0, 0);
    case game_bottom_right:
      return controller->GetOriginalDirection() == Vector3(1, -1, 0);
    case game_bottom:
      return controller->GetOriginalDirection() == Vector3(0, -1, 0);
    case game_bottom_left:
      return controller->GetOriginalDirection() == Vector3(-1, -1, 0);
    case game_keeper_rush:
      return controller->GetButton(e_ButtonFunction_KeeperRush);
    case game_pressure:
      return controller->GetButton(e_ButtonFunction_Pressure);
    case game_team_pressure:
      return controller->GetButton(e_ButtonFunction_TeamPressure);
    case game_sprint:
      return controller->GetButton(e_ButtonFunction_Sprint);
    case game_dribble:
      return controller->GetButton(e_ButtonFunction_Dribble);
    default:
      // 2026-09-09: a caller error must not terminate the embedding process.
      // Log(e_FatalError, "football", "main", "invalid sticky action");
      throw std::invalid_argument("Action is not sticky");
  }
  return false;
}

void GameEnv::action(int action, bool left_team, int player) {
  // 2026-09-09: scoped environment selection.
  // SetGame(this);
  ContextHolder guard(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  ValidateAction(action, player);
  if (state == game_done) throw std::logic_error("Match has ended; reset before applying input");
  if (state == game_paused) return;
  GetTracker()->setDisabled(true);
  // 2026-09-09: use the validated bank size.
  // int controller_id = player + (left_team ? 0 : 11);
  int controller_id = player + (left_team ? 0 : MAX_PLAYERS);
  auto controller = static_cast<AIControlledKeyboard*>(GetControllers()[controller_id]);
  controller->SetDisabled(false);
  switch (Action(action)) {
    case game_idle:
      break;
    case game_left:
      controller->SetDirection(Vector3(-1, 0, 0));
      break;
    case game_top_left:
      controller->SetDirection(Vector3(-1, 1, 0));
      break;
    case game_top:
      controller->SetDirection(Vector3(0, 1, 0));
      break;
    case game_top_right:
      controller->SetDirection(Vector3(1, 1, 0));
      break;
    case game_right:
      controller->SetDirection(Vector3(1, 0, 0));
      break;
    case game_bottom_right:
      controller->SetDirection(Vector3(1, -1, 0));
      break;
    case game_bottom:
      controller->SetDirection(Vector3(0, -1, 0));
      break;
    case game_bottom_left:
      controller->SetDirection(Vector3(-1, -1, 0));
      break;

    case game_long_pass:
      controller->SetButton(e_ButtonFunction_LongPass, true);
      break;
    case game_high_pass:
      controller->SetButton(e_ButtonFunction_HighPass, true);
      break;
    case game_short_pass:
      controller->SetButton(e_ButtonFunction_ShortPass, true);
      break;
    case game_shot:
      controller->SetButton(e_ButtonFunction_Shot, true);
      break;
    case game_keeper_rush:
      controller->SetButton(e_ButtonFunction_KeeperRush, true);
      break;
    case game_sliding:
      controller->SetButton(e_ButtonFunction_Sliding, true);
      break;
    case game_pressure:
      controller->SetButton(e_ButtonFunction_Pressure, true);
      break;
    case game_team_pressure:
      controller->SetButton(e_ButtonFunction_TeamPressure, true);
      break;
    case game_switch:
      controller->SetButton(e_ButtonFunction_Switch, true);
      break;
    case game_sprint:
      controller->SetButton(e_ButtonFunction_Sprint, true);
      break;
    case game_dribble:
      controller->SetButton(e_ButtonFunction_Dribble, true);
      break;
    case game_release_direction:
      controller->SetDirection(Vector3(0, 0, 0));
      break;
    case game_release_long_pass:
      controller->SetButton(e_ButtonFunction_LongPass, false);
      break;
    case game_release_high_pass:
      controller->SetButton(e_ButtonFunction_HighPass, false);
      break;
    case game_release_short_pass:
      controller->SetButton(e_ButtonFunction_ShortPass, false);
      break;
    case game_release_shot:
      controller->SetButton(e_ButtonFunction_Shot, false);
      break;
    case game_release_keeper_rush:
      controller->SetButton(e_ButtonFunction_KeeperRush, false);
      break;
    case game_release_sliding:
      controller->SetButton(e_ButtonFunction_Sliding, false);
      break;
    case game_release_pressure:
      controller->SetButton(e_ButtonFunction_Pressure, false);
      break;
    case game_release_team_pressure:
      controller->SetButton(e_ButtonFunction_TeamPressure, false);
      break;
    case game_release_switch:
      controller->SetButton(e_ButtonFunction_Switch, false);
      break;
    case game_release_sprint:
      controller->SetButton(e_ButtonFunction_Sprint, false);
      break;
    case game_release_dribble:
      controller->SetButton(e_ButtonFunction_Dribble, false);
      break;
    case game_builtin_ai:
      controller->SetDisabled(true);
      break;
  }
  GetTracker()->setDisabled(false);
}

std::string GameEnv::get_state(const std::string& pickle) {
  ContextHolder c(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  EnvState reader(this, "");
  string mutable_picke = pickle;
  reader.process(mutable_picke);
  // 2026-09-14: ContextHolder already owns this snapshot operation.
  ProcessStateInternal(&reader);
  // 2026-09-09: v2 snapshots carry format, length and corruption checks.
  // return reader.GetState();
  return blunted::snapshot::Encode(reader.GetState());
}

// 2026-08-26 确定性调试：与 get_state 同构，但把 reference 传入 EnvState 构造器，
// 启用 save 模式逐字段比对（见 defines.hpp process(T&)），第一个不一致字段即打印。
std::string GameEnv::compare_state(const std::string& reference) {
  ContextHolder c(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  // 2026-09-09: diagnostic offsets refer to the validated payload.
  // EnvState reader(this, "", reference);
  EnvState reader(this, "", std::string(blunted::snapshot::Decode(reference)));
  string pickle = "";
  reader.process(pickle);
  // 2026-09-14: ContextHolder already owns this snapshot operation.
  ProcessStateInternal(&reader);
  // 2026-09-09: v2 snapshots carry format, length and corruption checks.
  // return reader.GetState();
  return blunted::snapshot::Encode(reader.GetState());
}

// 2026-08-26 位级差异调试：在 compare_state 基础上启用 memcmp 级比对，
// 返回 divergence_log（见 defines.hpp setBitwise）。
std::vector<std::string> GameEnv::compare_state_bitwise(
    const std::string& reference) {
  ContextHolder c(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  // 2026-09-09: diagnostic offsets refer to the validated payload.
  // EnvState reader(this, "", reference);
  EnvState reader(this, "", std::string(blunted::snapshot::Decode(reference)));
  reader.setBitwise(true);
  string pickle = "";
  reader.process(pickle);
  // 2026-09-14: ContextHolder already owns this snapshot operation.
  ProcessStateInternal(&reader);
  return reader.GetDivergenceLog();
}

// 2026-08-26 canonical 状态摘要：跳过 setValidate(false) 不稳定区段；不含
// get_state 开头的 pickle 长度头，digest 自 env.state 字段起。
std::string GameEnv::get_state_digest() {
  ContextHolder c(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  EnvState reader(this, "");
  reader.setCanonical(true);
  // 2026-09-14: ContextHolder already owns this snapshot operation.
  ProcessStateInternal(&reader);
  return reader.GetState();
}

// 2026-09-09: failed state restoration rolls back to the complete prior state.
// std::string GameEnv::set_state(const std::string& state) {
//   // 2026-09-09: scoped environment selection.
//   // SetGame(this);
//   ContextHolder guard(this);
//   EnvState writer(this, state);
//   string pickle;
//   writer.process(pickle);
//   ProcessState(&writer);
//   if (!writer.eos()) {
//     Log(e_FatalError, "football", "main", "corrupted state");
//   }
//   return pickle;
// }
//
std::string GameEnv::set_state(const std::string& snapshot) {
  ContextHolder guard(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  // Validate the envelope before any simulation state is touched.
  const auto payload = blunted::snapshot::Decode(snapshot);
  const auto backup = get_state("");
  const auto backup_config = scenario_config;
  auto restore = [&](std::string_view bytes) {
    EnvState reader(this, std::string(bytes));
    std::string pickle;
    reader.process(pickle);
    // 2026-09-14: ContextHolder already owns this snapshot operation.
  ProcessStateInternal(&reader);
    reader.require(reader.eos(), "Trailing snapshot data");
    return pickle;
  };
  try {
    return restore(payload);
  } catch (...) {
    const auto failure = std::current_exception();
    // Match::ProcessState unwinds temporary mirroring before reaching this
    // boundary. Restore the scenario first because its identity is checked.
    scenario_config = backup_config;
    try {
      restore(blunted::snapshot::Decode(backup));
    } catch (...) {
      close();
      throw std::runtime_error("Snapshot recovery failed; environment was closed");
    }
    std::rethrow_exception(failure);
  }
}

void GameEnv::step() {
  // 2026-09-09: every public operation selects and restores its own environment.
  ContextHolder guard(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  if (state == game_done) throw std::logic_error("Match has ended; reset before stepping");
  if (state == game_paused) return;
  ValidateRuntimeConfig(game_config);
  DO_VALIDATION;
  // We do 10 environment steps per second, while game does 100 frames of
  // physics animation.
  int steps_to_do = GetGameConfig().physics_steps_per_frame;
  if (GetScenarioConfig().real_time) {
    DO_VALIDATION;
    auto start = std::chrono::system_clock::now();
    for (int x = 1; x <= steps_to_do; x++) {
      DO_VALIDATION;
      do_step(1);
      bool render_current_step =
          x * last_step_rendered_frames_ / steps_to_do !=
          (x - 1) * last_step_rendered_frames_ / steps_to_do;
      if (render_current_step) {
        render();
      }
    }
    auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now() - start);
    if (elapsed.count() > 9 * (steps_to_do + 1) &&
        last_step_rendered_frames_ > 1) {
      DO_VALIDATION;
      last_step_rendered_frames_--;
    } else if (elapsed.count() < 9 * (steps_to_do - 1) &&
               last_step_rendered_frames_ < steps_to_do) {
      DO_VALIDATION;
      last_step_rendered_frames_++;
    }
  } else {
    do_step(steps_to_do);
    if (GetGameConfig().render) {
      render();
    }
  }
  if (context->gameTask->GetMatch()->IsInPlay()) {
    DO_VALIDATION;
    GetTracker()->setDisabled(true);
    context->step++;
    for (auto controller : GetControllers()) {
      DO_VALIDATION;
      controller->ResetNotSticky();
    }
    GetTracker()->setDisabled(false);
  }
}

void GameEnv::StepWithInput(const void* frame_input_buffer, size_t buffer_size) {
  // 2026-09-09: every public operation selects and restores its own environment.
  ContextHolder guard(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  if (state == game_done) throw std::logic_error("Match has ended; reset before stepping");
  if (state == game_paused) return;
  ValidateRuntimeConfig(game_config);
  DO_VALIDATION;
  int left = scenario_config.left_agents;
  int right = scenario_config.right_agents;
  frame_sync::DecodeAndApplyFrameInput(
      frame_input_buffer, buffer_size,
      context->controllers, left, right);
  int steps_to_do = GetGameConfig().physics_steps_per_frame;
  do_step(steps_to_do);
  if (context->gameTask->GetMatch()->IsInPlay()) {
    DO_VALIDATION;
    GetTracker()->setDisabled(true);
    context->step++;
    for (auto controller : GetControllers()) {
      DO_VALIDATION;
      controller->ResetNotSticky();
    }
    GetTracker()->setDisabled(false);
  }
}

// 2026-09-14: preserve the prior public wrapper for review.
// void GameEnv::ProcessState(EnvState* state) {
//   // 2026-09-14: public serialization also owns its context and match precondition.
//   ContextHolder guard(this);
//   RequireInitializedMatch(*this);
//   if (!state) throw std::invalid_argument("State serializer must not be null");
// 2026-09-14: normal public serialization locks its owner; the tracker rendezvous
// calls the private serializer while the other thread deliberately holds its lock.
void GameEnv::ProcessState(EnvState* state) {
  ContextHolder guard(this);
  ProcessStateInternal(state);
}
void GameEnv::ProcessStateInternal(EnvState* state) {
  RequireInitializedMatch(*this);
  if (!state) throw std::invalid_argument("State serializer must not be null");
  state->process(this->state);
  // 2026-09-09: include the explicit paused state in snapshot validation.
  // state->require(this->state >= game_created && this->state <= game_done, "Invalid environment state");
  state->require(SnapshotEnumValid(this->state, this->state), "Invalid environment state");
  state->process(waiting_for_game_count);
  context->ProcessState(state);
  context->gameTask->GetMatch()->ProcessState(state);
}

// 2026-09-09: balance tracker nesting after rendering exceptions.
//
// void GameEnv::render(bool swap_buffer) {
//   // 2026-09-09: every public operation selects and restores its own environment.
//   ContextHolder guard(this);
//   GetTracker()->setDisabled(true);
//   context->gameTask->PrepareRender();
//   context->graphicsSystem.GetTask()->Render(swap_buffer);
//   GetTracker()->setDisabled(false);
// }

void GameEnv::render(bool swap_buffer) {
  ContextHolder guard(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  GetTracker()->setDisabled(true);
  struct RestoreTracker {
    ~RestoreTracker() { GetTracker()->setDisabled(false); }
  } tracker_guard;
  context->gameTask->PrepareRender();
  context->graphicsSystem.GetTask()->Render(swap_buffer);
  render_presented_ = true;
}

// 2026-09-10: status is presentation data, never a physical pause mutation.
void GameEnv::set_match_status(const std::string& text) {
  if (text.size() > 96 || std::any_of(text.begin(), text.end(), [](unsigned char c) {
        return c < 32 || c > 126;
      })) throw std::invalid_argument("Match status requires at most 96 printable ASCII characters");
  ContextHolder guard(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  if (!game_config.render || !context->gameTask->GetMatch())
    throw std::logic_error("Match status requires an initialized rendering match");
  GetTracker()->setDisabled(true);
  struct RestoreTracker {
    ~RestoreTracker() { GetTracker()->setDisabled(false); }
  } tracker_guard;
  context->gameTask->GetMatch()->SetControlStatus(text);
}

void GameEnv::save_render_state(bool from_display) {
  ContextHolder guard(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  if (!game_config.render || !context->gameTask->GetMatch())
    throw std::logic_error("Interpolation requires an initialized rendering match");
  if (from_display && !render_presented_)
    throw std::logic_error("No rendered pose to preserve");
  GetTracker()->setDisabled(true);
  struct RestoreTracker {
    ~RestoreTracker() { GetTracker()->setDisabled(false); }
  } tracker_guard;
  render_state_saved_ = false;
  context->gameTask->GetMatch()->SaveInterpolationState(from_display);
  render_state_saved_ = true;
}

void GameEnv::render_interpolated(float alpha, bool swap_buffer) {
  if (!std::isfinite(alpha) || alpha < 0.0f || alpha > 1.0f)
    throw std::invalid_argument("Interpolation alpha must be finite and within [0, 1]");
  ContextHolder guard(this);
  // 2026-09-14: reject prepared/loading access before any match mutation.
  RequireInitializedMatch(*this);
  if (!game_config.render || !render_state_saved_)
    throw std::logic_error("Interpolation requires a captured rendering pose");
  GetTracker()->setDisabled(true);
  struct RestoreTracker {
    ~RestoreTracker() { GetTracker()->setDisabled(false); }
  } tracker_guard;
  context->gameTask->PrepareRender(alpha);
  context->graphicsSystem.GetTask()->Render(swap_buffer);
  render_presented_ = true;
}

void GameEnv::reset(ScenarioConfig& game_config, bool animations) {
  // 2026-09-10: reset render history only under the environment owner guard.
  // render_state_saved_ = render_presented_ = false;
  DO_VALIDATION;
  ContextHolder c(this);
  // 2026-09-10: rejected reset parameters must preserve captured render poses.
  // render_state_saved_ = render_presented_ = false;
  ValidateRuntimeConfig(this->game_config);
// 2026-09-14: rollback partial match resources without closing a window still served by another thread.
//   ValidateScenario(game_config);
//   render_state_saved_ = render_presented_ = false;
  ValidateScenario(game_config);
  // 2026-09-14: cancellation before mutation preserves a previous complete match.
  GameLoadCheckpoint("reset.begin");
  const auto previous_rng = context->rng;
  const auto previous_visual_rng = context->rng_non_deterministic;
  // 2026-09-14: cached visuals and their RNG advance commit as one reset.
  const bool previous_pitch_loaded = context->already_loaded;
  const bool previous_stadium_render = bool(context->stadiumRender);
  const bool previous_goals = bool(context->goalsNode);
  const int previous_tracker = context->tracker_disabled;
  GameLoadCleanup rollback([&] {
    // The runtime/window stays alive until its UI owner has joined the worker.
    GetGameTask()->StopMatch();
    if (auto* pending = GetMenuTask()->GetMatchData()) {
      delete pending;
      GetMenuTask()->SetMatchData(nullptr);
    }
    context->animPositionCache.clear();
    context->anims.reset();
    context->colorCoords.clear();
    // 2026-09-14: discard only caches created by this failed reset.
    // A cached stadium already has randomized adboards; retaining it would
    // skip those random draws after restoring the pre-reset generator.
    if (!previous_stadium_render && context->stadiumRender) {
      context->stadiumRender->Exit();
      context->stadiumRender.reset();
    }
    if (!previous_goals && context->goalsNode) {
      context->scene3D->DeleteNode(context->goalsNode);
      context->goalsNode->Exit();
      context->goalsNode.reset();
    }
    context->already_loaded = previous_pitch_loaded;
    context->rng = previous_rng;
    context->rng_non_deterministic = previous_visual_rng;
    context->tracker_disabled = previous_tracker;
    context->step = -1;
    state = game_created;
  });
  render_state_saved_ = render_presented_ = false;
  // Reset call disables tracker.
  GetTracker()->setDisabled(true);
  context->step = -1;
  waiting_for_game_count = 0;
  setConfig(game_config);
  GameLoadCheckpoint("reset.controllers");
  for (auto controller : GetControllers()) {
    DO_VALIDATION;
    controller->SetDisabled(true);
  }
  GameLoadCheckpoint("reset.cache");
  context->geometry_manager.RemoveUnused();
  context->surface_manager.RemoveUnused();
  context->texture_manager.RemoveUnused();
  context->vertices_manager.RemoveUnused();
  GameLoadCheckpoint("reset.pages");
  GetMenuTask()->GetWindowManager()->GetRoot()->SetRecursiveZPriority(0);
  DO_VALIDATION;
  GetMenuTask()->GetWindowManager()->GetPagePath()->Clear();
  bool already_loaded = GetGameTask()->StopMatch();
  GameLoadCheckpoint("reset.match-data");
  GetMenuTask()->SetMatchData(new MatchData());
  if (!already_loaded) {
    // We show loading page only the first time when env. is started.
    GameLoadCheckpoint("reset.loading-page");
    GetMenuTask()->GetWindowManager()->GetPageFactory()->CreatePage(1, 0);
  }
// 2026-09-14: retain the previous uninterrupted loading-page draw.
//   if (GetGameConfig().render) {
//     GetTracker()->setDisabled(true);
//     context->graphicsSystem.GetTask()->Render(true);
//     GetTracker()->setDisabled(false);
//   }
  if (GetGameConfig().render) {
    // 2026-09-14: the existing renderer service checks cancellation at owned
    // draw boundaries; the callback only reads cancellation/transport state.
    blunted::ScopedRenderService service([](void*) {
      GameLoadCheckpoint("reset.render");
    }, nullptr);
    GameLoadCheckpoint("reset.render.begin");
    GetTracker()->setDisabled(true);
    context->graphicsSystem.GetTask()->Render(true);
    GetTracker()->setDisabled(false);
    GameLoadCheckpoint("reset.render.done");
  }
  GetGameTask()->StartMatch(animations);
  // 2026-09-09: reset is the only transition from a finished match to play.
  if (state == game_done || state == game_paused) state = game_running;
  rollback.release();
}
