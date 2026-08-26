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

#ifndef _GAME_ENV
#define _GAME_ENV

#include <cstddef>
#include "onthepitch/match.hpp"
#include "gamedefines.hpp"
#include "gfootball_actions.h"
#include "main.hpp"

class AIControlledKeyboard;
class GameTask;

typedef std::vector<std::string> StringVector;

class ContextHolder {
 public:
  ContextHolder(GameEnv* game) : game(game) {
     SetGame(game);
     GetGraphicsSystem()->SetContext();
  }
  ~ContextHolder() {
    if (GetGame() != game) {
      Log(e_FatalError, "football", "main", "game state was corrupted");
    }
    GetGraphicsSystem()->DisableContext();
  }
 private:
  const GameEnv* game;
};

// Game environment. This is the class that can be used directly from Python.
struct GameEnv {
  GameEnv() { DO_VALIDATION;}
  // Start the game (in separate process).
  void start_game();

  // Get the current state of the game (observation).
  SharedInfo get_info();

  // Get the current rendered frame.
  screenshoot get_frame();

  // Executes the action inside the game.
  bool sticky_action_state(int action, bool left_team, int player);
  void action(int action, bool left_team, int player);
  void reset(ScenarioConfig& game_config, bool init_animation);
  void render(bool swap_buffer = true);
  std::string get_state(const std::string& pickle);
  std::string set_state(const std::string& state);
  // 2026-08-26 确定性调试：以 reference 为基准序列化当前状态（EnvState save 模式
  // 比对），在第一个不一致字段处打印 Position/Type/Value/Reference；返回当前状态。
  std::string compare_state(const std::string& reference);
  // 2026-08-26 位级差异调试：同 compare_state，但额外启用 memcmp 级比对，
  // 返回全部「判等但字节不同」对象的记录（pos/type/size/A/B 十六进制），
  // 用于定位结构体 padding / 非规范 bool 造成的跨进程字节漂移。
  std::vector<std::string> compare_state_bitwise(const std::string& reference);
  // 2026-08-26 canonical 状态摘要：与 get_state 同构，但跳过 setValidate(false)
  // 标记的不稳定区段，输出仅含比赛逻辑状态，供帧同步 StateHash 校验使用。
  // 不可作为 set_state 的输入（字节布局与全量序列化不同）。
  std::string get_state_digest();
  void tracker_setup(long start, long end) { GetTracker()->setup(start, end); }
  void step();
  // Server headless: apply authoritative frame input and run one env step (no render).
  void StepWithInput(const void* frame_input_buffer, size_t buffer_size);
  void ProcessState(EnvState* state);
  ScenarioConfig& config();

 private:
  void setConfig(ScenarioConfig& scenario_config);
  void do_step(int count);
  void getObservations();
  AIControlledKeyboard* keyboard_ = nullptr;
  bool disable_graphics_ = false;
  int last_step_rendered_frames_ = 1;
 public:
  ScenarioConfig scenario_config;
  GameConfig game_config;
  GameContext* context = nullptr;
  GameState state = game_created;
  int waiting_for_game_count = 0;
};

#endif
