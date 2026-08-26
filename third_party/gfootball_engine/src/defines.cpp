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

#include "defines.hpp"

#include "backtrace.h"
#include "base/log.hpp"
#include "game_env.hpp"
#include "main.hpp"

EnvState::EnvState(GameEnv* game, const std::string& state,
                   const std::string reference)
    : load(!state.empty()),
      state(state),
      reference(reference),
      scenario_config(&game->scenario_config),
      context(game->context) {
}

void EnvState::process(std::string& value) {
  if (canonicalSkip()) return;
  int s = value.size();
  process(s);
  value.resize(s);
  for (char& c : value) {
    process(c);
  }
}

void EnvState::process(void** collection, int size, void*& element) {
  if (canonicalSkip()) return;
  DO_VALIDATION;
  if (load) {
    DO_VALIDATION;
    int index;
    process(index);
    if (index == -1) {
      DO_VALIDATION;
      element = 0;
    } else {
      if (index >= size) {
        DO_VALIDATION;
        Log(blunted::e_FatalError, "EnvState", "element", "element index out of bound");
      }
      element = collection[index];
    }
  } else {
    if (element == 0) {
      DO_VALIDATION;
      int index = -1;
      process(index);
    } else {
      for (int x = 0; x < size; x++) {
        DO_VALIDATION;
        if (collection[x] == element) {
          DO_VALIDATION;
          process(x);
          return;
        }
      }
      Log(blunted::e_FatalError, "EnvState", "element", "element not found");
    }
  }
}

void EnvState::process(Team*& value) {
  DO_VALIDATION;
  void* v = value;
  process(reinterpret_cast<void**>(&teams[0]), 2, v);
  value = static_cast<Team*>(v);
}

void EnvState::process(Player*& value) {
  DO_VALIDATION;
  void* v = value;
  process(reinterpret_cast<void**>(&players[0]), players.size(), v);
  value = static_cast<Player*>(v);
}

void EnvState::process(HumanGamer*& value) {
  DO_VALIDATION;
  void* v = value;
  process(reinterpret_cast<void**>(&human_controllers[0]), human_controllers.size(), v);
  value = static_cast<HumanGamer*>(v);
}

void EnvState::process(AIControlledKeyboard*& value) {
  DO_VALIDATION;
  void* v = value;
  process(reinterpret_cast<void**>(&controllers[0]), controllers.size(), v);
  value = static_cast<AIControlledKeyboard*>(v);
}

void EnvState::process(blunted::Animation*& value) {
  DO_VALIDATION;
  void* v = value;
  process(reinterpret_cast<void**>(&animations[0]), animations.size(), v);
  value = static_cast<blunted::Animation*>(v);
}

// 2026-08-26 确定性修复（原因）：radian 布局为 float angle_(4B) + bool
// rotated_(1B) + 3B padding。原走泛型模板整体 memcpy，把 padding 里的堆垃圾
// 一并写进 state；而 EnvState 的比较经 radian::operator real() 只看角度值，
// 形成「判等但字节不同」，跨进程 StateHash 必然漂移（帧同步校验误报的根因，
// 位级比对仪表定位：全部差异对象 type=blunted::radian）。
// 改为逐成员序列化：angle_ + 规范化为 0/1 的 rotated_ + 固定 3 字节零填充。
// 总长仍为 8 字节，与旧 state 格式偏移兼容；load 时读入并丢弃填充字节。
void EnvState::process(blunted::radian& value) {
  if (canonicalSkip()) return;
  DO_VALIDATION;
  process(value.angle_);
  unsigned char rotated = value.rotated_ ? 1 : 0;
  process(rotated);
  if (load) {
    value.rotated_ = rotated != 0;
  }
  // 固定填充：save 写全 0（canonical），load 读入后丢弃，维持旧布局总长。
  unsigned char pad0 = 0;
  process(pad0);
  process(pad0);
  process(pad0);
}

bool EnvState::eos() {
  DO_VALIDATION;
  return pos == state.size();
}

void EnvState::SetPlayers(const std::vector<Player*>& players) {
  DO_VALIDATION;
  this->players = players;
}

void EnvState::SetHumanControllers(
    const std::vector<HumanGamer*>& controllers) {
  DO_VALIDATION;
  this->human_controllers = controllers;
}

void EnvState::SetControllers(const std::vector<AIControlledKeyboard*>& controllers) {
  DO_VALIDATION;
  this->controllers = controllers;
}

void EnvState::SetAnimations(
    const std::vector<blunted::Animation*>& animations) {
  DO_VALIDATION;
  this->animations = animations;
}

void EnvState::SetTeams(Team* team0, Team* team1) {
  DO_VALIDATION;
  this->teams.push_back(team0);
  this->teams.push_back(team1);
}

const std::string& EnvState::GetState() {
  DO_VALIDATION;
  return state;
}
