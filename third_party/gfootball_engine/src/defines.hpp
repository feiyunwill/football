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

// written by bastiaan konings schuiling 2008 - 2014
// this work is public domain. the code is undocumented, scruffy, untested, and should generally not be used for anything important.
// i do not offer support, so don't ask. to be used for inspiration :)

#ifndef _HPP_DEFINES
#define _HPP_DEFINES

#ifdef WIN32
#define NOMINMAX
#include <windows.h>
#undef NOMINMAX
#endif

#include <compare>
#include <utility>  // std::to_underlying (C++23)
#include <format>   // std::format (C++23)
#include <cstdio>
#include <cstdlib>
#include <cassert>
#include <cstring>

#include <fstream>
#include <cmath>

#include <algorithm>
#include <string>
#include <list>
#include <vector>
#include <map>
#include <deque>

// 2026-08-26 移除 Boost：shared_ptr/weak_ptr 全面改用 std（含 ai.cpp 绑定层）；
// intrusive_ptr 按 RefCounted 体系约定保留。
// #include <boost/shared_ptr.hpp>
#include <memory>
#include <boost/intrusive_ptr.hpp>
// 2026-08-26 移除 Boost（原因）：全仓库无任何 boost::condition 使用点，
// 唯一实例 messagequeue.hpp 已改用 std::condition_variable 并自行包含 <condition_variable>。
// #include <boost/thread/condition.hpp>
// 2026-08-26 移除 Boost（原因）：signals2 全仓库 0 个 signal 实例，纯死 include。
// #include <boost/signals2.hpp>
// #include <boost/signals2/slot.hpp>
// 2026-08-26 移除 Boost（原因）：全部 boost::bind 谓词已改写为 lambda
// （humanoidbase.cpp / humanoid.cpp），bind 头与占位符 using 声明随之移除。
// #include <boost/bind/bind.hpp>
#include "backtrace.h"
#include "base/log.hpp"

#define CHECK(a) assert(a);
#define CHECK_EQ(a, b) assert((a) == (b));

constexpr float EPSILON = 0.000001;

#define X_FIELD_SCALE 54.4
#define Y_FIELD_SCALE -83.6
#define Z_FIELD_SCALE 1
#define MAX_PLAYERS 11

typedef std::string screenshoot;

// 2026-08-26 移除 Boost：占位符 _1/_2 已无使用者（谓词全部 lambda 化）。
// using namespace boost::placeholders;

namespace blunted {
  class Animation;
  // 2026-08-26 确定性修复：radian 专用序列化重载（见 process(blunted::radian&)）
  class radian;
  //using namespace boost;
}

class Player;
class Team;
class HumanGamer;
class AIControlledKeyboard;
class ScenarioConfig;
class GameContext;
class GameEnv;


#include "base/math/vector3.hpp"

class EnvState {
 public:
  EnvState(GameEnv* game_env, const std::string& state, const std::string reference = "");
  const ScenarioConfig* getConfig() { return scenario_config; }
  const GameContext* getContext() { return context; }
  void process(std::string &value);
  void process(blunted::Animation* &value);
  template<typename T> void process(std::vector<T>& collection) {
    if (canonicalSkip()) return;
    int size = collection.size();
    process(size);
    collection.resize(size);
    for (auto& el : collection) {
      process(el);
    }
  }
  template<typename T> void process(std::list<T>& collection) {
    if (canonicalSkip()) return;
    int size = collection.size();
    process(size);
    collection.resize(size);
    for (auto& el : collection) {
      process(el);
    }
  }
  void process(Player*& value);
  void process(HumanGamer*& value);
  // 2026-08-26 确定性修复：radian 整体 memcpy 会把 padding 堆垃圾写进 state
  // （跨进程 StateHash 漂移的根因），改为逐成员序列化，见 defines.cpp。
  void process(blunted::radian& value);
  void process(AIControlledKeyboard*& value);
  void process(Team*& value);
  bool isFailure() {
    return failure;
  }
  bool enabled() {
    return this->disable_cnt == 0;
  }
  void setValidate(bool validate) {
    this->disable_cnt += validate ? -1 : 1;
  }
  // 2026-08-26 canonical 摘要模式：save 方向跳过 setValidate(false) 包住的不稳定
  // 区段（相机/球员颜色缓冲/边裁/HID），使跨进程 state digest 可比较；load 与
  // reference 比对行为不受影响。排除集随 setValidate 调用点自动维护。
  void setCanonical(bool canonical) {
    this->canonical = canonical;
  }
  bool canonicalSkip() {
    return this->canonical && !this->load && this->disable_cnt != 0;
  }
  void setCrash(bool crash) {
    this->crash = crash;
  }
  // 2026-08-26 位级差异调试模式：compare 时对每个序列化对象额外做 memcmp 比对
  // （不受 disable_cnt/failure 影响，也不置 failure），把「operator!= 判等但字节
  // 不同」的对象（结构体 padding、非规范 bool 等）记录进 divergence_log，
  // 用于定位跨进程 state 字节漂移的来源字段。
  void setBitwise(bool bitwise) {
    this->bitwise = bitwise;
  }
  bool Load() { return load; }
  int getpos() {
    return pos;
  }
  bool eos();
  template<typename T> void process(T& obj) {
    if (canonicalSkip()) return;
    if (load) {
      if (pos + sizeof(T) > state.size()) {
        Log(blunted::e_FatalError, "EnvState", "state", "state is invalid");
      }
      memcpy(&obj, &state[pos], sizeof(T));
      pos += sizeof(T);
    } else {
      state.resize(pos + sizeof(T));
      memcpy(&state[pos], &obj, sizeof(T));
      if (!failure && disable_cnt == 0 && !reference.empty() && (*(T*) &state[pos]) != (*(T*) &reference[pos])) {
        failure = true;
        std::cout << "Position:  " << pos << std::endl;
        std::cout << "Type:      " << typeid(obj).name() << std::endl;
        std::cout << "Value:     " << obj << std::endl;
        std::cout << "Reference: " << (*(T*) &reference[pos]) << std::endl;
        if (crash) {
          Log(blunted::e_FatalError, "EnvState", "state", "Reference mismatch");
        } else {
          print_stacktrace();
        }
      }
      pos += sizeof(T);
      // 2026-08-26 位级差异调试：memcmp 比对（operator!= 会把非零 bool、
      // -0.0、结构体 padding 等判等），记录 pos/typeid/长度/双方十六进制。
      // 仅在 setBitwise(true) 时生效，上限 256 条防刷屏。
      if (bitwise && divergence_log.size() < 256 && !reference.empty() &&
          static_cast<size_t>(pos) <= reference.size() &&
          memcmp(&state[pos - sizeof(T)], &reference[pos - sizeof(T)],
                 sizeof(T)) != 0) {
        std::string entry = "pos=" + std::to_string(pos - sizeof(T)) +
                            " type=" + typeid(obj).name() +
                            " size=" + std::to_string(sizeof(T)) + " A=";
        const unsigned char* pa =
            reinterpret_cast<const unsigned char*>(&state[pos - sizeof(T)]);
        const unsigned char* pb =
            reinterpret_cast<const unsigned char*>(&reference[pos - sizeof(T)]);
        size_t n = sizeof(T) < 32 ? sizeof(T) : 32;
        for (size_t i = 0; i < n; i++) {
          entry += std::format("{:02x}", pa[i]);
        }
        entry += " B=";
        for (size_t i = 0; i < n; i++) {
          entry += std::format("{:02x}", pb[i]);
        }
        divergence_log.push_back(entry);
      }
      if (pos > 10000000) {
        Log(blunted::e_FatalError, "EnvState", "state", "state is too big");
      }
    }
  }
  void SetPlayers(const std::vector<Player*>& players);
  void SetHumanControllers(const std::vector<HumanGamer*>& controllers);
  void SetControllers(const std::vector<AIControlledKeyboard*>& controllers);
  void SetAnimations(const std::vector<blunted::Animation*>& animations);
  void SetTeams(Team* team0, Team* team1);
  const std::string& GetState();
  // 2026-08-26 位级差异调试：setBitwise(true) 的 compare 之后读取差异记录
  const std::vector<std::string>& GetDivergenceLog() {
    return divergence_log;
  }
 protected:
  bool failure = false;
  bool stack = true;
  bool load = false;
  bool canonical = false;
  // 2026-08-26 位级差异调试（见 setBitwise）
  bool bitwise = false;
  std::vector<std::string> divergence_log;
  char disable_cnt = 0;
  bool crash = false;
  std::vector<Player*> players;
  std::vector<blunted::Animation*> animations;
  std::vector<Team*> teams;
  std::vector<HumanGamer*> human_controllers;
  std::vector<AIControlledKeyboard*> controllers;
  std::string state;
  std::string reference;
  int pos = 0;
  ScenarioConfig* scenario_config;
  GameContext* context;
 private:
  void process(void** collection, int size, void*& element);
};

// 3-d position of object (available from python).
struct Position {
  Position(float x = 0.0, float y = 0.0, float z = 0.0, bool env_coords = false) {
    if (env_coords) {
      value[0] = X_FIELD_SCALE * x;
      value[1] = Y_FIELD_SCALE * y;
      value[2] = Z_FIELD_SCALE * z;
    } else {
      value[0] = x;
      value[1] = y;
      value[2] = z;
    }
  }
  Position(const Position& other) {
    value[0] = other.value[0];
    value[1] = other.value[1];
    value[2] = other.value[2];
  }
  Position& operator=(float* position) {
    value[0] = position[0];
    value[1] = position[1];
    value[2] = position[2];
    return *this;
  }
  bool operator == (const Position& f) const {
    return value[0] == f.value[0] &&
        value[1] == f.value[1] &&
        value[2] == f.value[2];
  }
  // Returns environment coordinates, ie [-1,1] for x (0),
  // [-0.42,0.42] for y (1).
  float env_coord(int index) const;
  std::string debug();
 private:
  float value[3];
};

enum e_PlayerRole {
  e_PlayerRole_GK,
  e_PlayerRole_CB,
  e_PlayerRole_LB,
  e_PlayerRole_RB,
  e_PlayerRole_DM,
  e_PlayerRole_CM,
  e_PlayerRole_LM,
  e_PlayerRole_RM,
  e_PlayerRole_AM,
  e_PlayerRole_CF,
};
constexpr std::strong_ordering operator<=>(e_PlayerRole a, e_PlayerRole b) {
  return std::to_underlying(a) <=> std::to_underlying(b);
}

enum e_GameMode {
  e_GameMode_Normal,
  e_GameMode_KickOff,
  e_GameMode_GoalKick,
  e_GameMode_FreeKick,
  e_GameMode_Corner,
  e_GameMode_ThrowIn,
  e_GameMode_Penalty,
};
constexpr std::strong_ordering operator<=>(e_GameMode a, e_GameMode b) {
  return std::to_underlying(a) <=> std::to_underlying(b);
}

enum e_PlayerColor {
  e_PlayerColor_Blue,
  e_PlayerColor_Green,
  e_PlayerColor_Red,
  e_PlayerColor_Yellow,
  e_PlayerColor_Purple,
  e_PlayerColor_Default
};
constexpr std::strong_ordering operator<=>(e_PlayerColor a, e_PlayerColor b) {
  return std::to_underlying(a) <=> std::to_underlying(b);
}

enum e_Team {
  e_Left,
  e_Right,
};
constexpr std::strong_ordering operator<=>(e_Team a, e_Team b) {
  return std::to_underlying(a) <=> std::to_underlying(b);
}

// Information about the player (available from python).
struct PlayerInfo {
  PlayerInfo() { }
  PlayerInfo(const PlayerInfo& f) {
    player_position = f.player_position;
    player_direction = f.player_direction;
    has_card = f.has_card;
    is_active = f.is_active;
    tired_factor = f.tired_factor;
    role = f.role;
    designated_player = f.designated_player;
  }
  bool operator == (const PlayerInfo& f) const {
    return player_position == f.player_position &&
        player_direction == f.player_direction &&
        has_card == f.has_card &&
        is_active == f.is_active &&
        tired_factor == f.tired_factor &&
        role == f.role &&
        designated_player == f.designated_player;
  }
  Position player_position;
  Position player_direction;
  bool has_card = false;
  bool is_active = true;
  bool designated_player = false;
  float tired_factor = 0.0f; // In the [0..1] range.
  e_PlayerRole role = e_PlayerRole_GK;
};

struct ControllerInfo {
  ControllerInfo() { }
  ControllerInfo(int controlled_player) : controlled_player(controlled_player) { }
  bool operator == (const ControllerInfo& f) const {
    return controlled_player == f.controlled_player;
  }
  int controlled_player = -1;
};

// All the information about the current state (available from python).
struct SharedInfo {
  Position ball_position;
  Position ball_direction;
  Position ball_rotation;
  std::vector<PlayerInfo> left_team;
  std::vector<PlayerInfo> right_team;
  std::vector<ControllerInfo> left_controllers;
  std::vector<ControllerInfo> right_controllers;
  int left_goals, right_goals;
  e_GameMode game_mode;
  bool is_in_play = false;
  int ball_owned_team = 0;
  int ball_owned_player = 0;
  int step = 0;
};

#endif
