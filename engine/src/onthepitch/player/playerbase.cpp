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

// written by bastiaan konings schuiling 2008 - 2015
// this work is public domain. the code is undocumented, scruffy, untested, and should generally not be used for anything important.
// i do not offer support, so don't ask. to be used for inspiration :)

#include "player.hpp"

#include "../match.hpp"
#include "../ecs_components.hpp"

#include "controller/elizacontroller.hpp"
#include "controller/strategies/strategy.hpp"

#include "../../main.hpp"
#include "../../utils.hpp"

#include "../../base/geometry/triangle.hpp"

PlayerBase::PlayerBase(Match *match, PlayerData *playerData)
    : match(match),
      playerData(playerData),
      stable_id(GetContext().stablePlayerCount++) {
  DO_VALIDATION;
  lastTouchTime_ms = 0;
  lastTouchType = e_TouchType_None;
  fatigueFactorInv = 1.0;
}

PlayerBase::~PlayerBase() {
  DO_VALIDATION;
  if (isActive) Deactivate();
}

void PlayerBase::Mirror() {
  humanoid->Mirror();
}

void PlayerBase::Deactivate() {
  DO_VALIDATION;
  ResetSituation(GetPosition());

  if (humanoid) humanoid->Hide();
  isActive = false;
  externalController = nullptr;
}

IController *PlayerBase::GetController() {
  DO_VALIDATION;
  if (ExternalControllerActive()) {
    return externalController->GetHumanController();
  } else {
    return controller.get();
  }
}

void PlayerBase::RequestCommand(PlayerCommandQueue &commandQueue) {
  DO_VALIDATION;
  if (ExternalControllerActive()) {
    externalController->GetHumanController()->RequestCommand(commandQueue);
  } else {
    controller->RequestCommand(commandQueue);
  }
}

void PlayerBase::SetExternalController(HumanGamer *externalController) {
  DO_VALIDATION;
  this->externalController = externalController;
  if (this->externalController) {
    DO_VALIDATION;
    this->externalController->GetHumanController()->Reset();
    this->externalController->GetHumanController()->SetPlayer(this);
  } else {
    controller->Reset();
  }
}

HumanController *PlayerBase::ExternalController() {
  DO_VALIDATION;
  return externalController ? externalController->GetHumanController() : nullptr;
}

bool PlayerBase::ExternalControllerActive() {
  DO_VALIDATION;
  return externalController && !externalController->GetHumanController()->Disabled();
}

void PlayerBase::Process() {
  DO_VALIDATION;
  if (isActive) {
    DO_VALIDATION;
    if (ExternalControllerActive()) externalController->GetHumanController()->Process(); else controller->Process();
    humanoid->Process();
  } else {
    if (humanoid) humanoid->Hide();
  }
}

void PlayerBase::PreparePutBuffers() {
  DO_VALIDATION;
  humanoid->PreparePutBuffers();
}

void PlayerBase::FetchPutBuffers() {
  DO_VALIDATION;
  humanoid->FetchPutBuffers();
}

void PlayerBase::Put(bool mirror) {
  DO_VALIDATION;
  humanoid->Put(mirror);
}

// 2026-09-04 ms-16.1: 逻辑渲染分离 — 队伍/裁判插值支持
void PlayerBase::SaveInterpolationState() {
  DO_VALIDATION;
  humanoid->SaveInterpolationState();
}

void PlayerBase::PutInterpolated(float t, bool mirror) {
  DO_VALIDATION;
  humanoid->PutInterpolated(t, mirror);
}

float PlayerBase::GetStat(PlayerStat name) const {
  return playerData->GetStat(name);
}

float PlayerBase::GetMaxVelocity() const {
  // see humanoidbase's physics function
  return sprintVelocity * GetVelocityMultiplier();
}

float PlayerBase::GetVelocityMultiplier() const {
  // see humanoid_utils' physics function
  return 0.9f + playerData->get_physical_velocity() * 0.1f;
}

float PlayerBase::GetLastTouchBias(int decay_ms, unsigned long time_ms) {
  DO_VALIDATION;
  unsigned long adaptedTime_ms = time_ms;
  if (time_ms == 0) adaptedTime_ms = match->GetActualTime_ms();
  if (decay_ms > 0) return 1.0f - clamp((adaptedTime_ms - GetLastTouchTime_ms()) / (float)decay_ms, 0.0f, 1.0f);
  return 0.0f;
}

void PlayerBase::ResetSituation(const Vector3 &focusPos) {
  DO_VALIDATION;
  positionHistoryPerSecond.clear();
  lastTouchTime_ms = 0;
  lastTouchType = e_TouchType_None;
  if (IsActive()) humanoid->ResetSituation(focusPos);
  if (GetController()) GetController()->Reset();
}

void PlayerBase::ProcessStateBase(EnvState *state) {
  DO_VALIDATION;
  state->process(isActive);
  humanoid->ProcessState(state);
  if (IsActive()) {
    controller->ProcessState(state);
  }
  state->process(externalController);
  state->process(lastTouchTime_ms);
  state->process(lastTouchType);
  state->process(fatigueFactorInv);
  state->process(positionHistoryPerSecond);
}

void PlayerBase::FillPlayerStateComponent(PlayerStateComponent& out) const {
  DO_VALIDATION;
  // 基本信息
  out.stable_id = stable_id;
  out.team_id = -1;  // 需要从外部设置
  out.is_active = isActive;
  
  // 物理状态
  out.position = GetPosition();
  out.geom_position = GetGeomPosition();
  out.direction_vec = GetDirectionVec();
  out.body_direction_vec = GetBodyDirectionVec();
  out.rel_body_angle = GetRelBodyAngle();
  
  // 动作状态
  out.enum_velocity = GetEnumVelocity();
  out.float_velocity = GetFloatVelocity();
  out.movement = GetMovement();
  
  // 控球状态（需要从 Player 子类获取）
  out.has_possession = false;
  out.has_best_possession = false;
  out.has_unique_possession = false;
  out.possession_duration_ms = 0;
  
  // 时间戳
  out.last_touch_time_ms = lastTouchTime_ms;
  out.last_touch_type = static_cast<int>(lastTouchType);
  
  // 疲劳与状态
  out.fatigue_factor_inv = fatigueFactorInv;
  out.cards = 0;  // 需要从 Player 子类获取
}
