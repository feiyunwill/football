// Copyright 2019 Google LLC & Bastiaan Konings
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//

// 2025-03-17 ECS 迁移：BallSystem 委托 Ball::Process 并写回 ECS

#include "ecs_systems.hpp"
#include "match.hpp"
#include "ecs_components.hpp"
#include "player/player.hpp"
#include "../ecs/transform.hpp"

void BallSystemProcess(Match* match) {
  DO_VALIDATION;
  Ball* ball = match->GetBall();
  ball->Process();

  // 同步到 ECS，供 ProcessState / 后续系统使用
  blunted::Entity e = match->GetEcsBallEntity();
  if (e == blunted::kNullEntity) return;
  blunted::World& w = match->GetEcsWorld();
  BallComponent comp;
  ball->FillBallComponent(comp);
  w.AddComponent(e, comp);
  Transform tr;
  tr.position = comp.positionBuffer;
  tr.rotation = comp.orientationBuffer;
  tr.scale = Vector3(1.0f, 1.0f, 1.0f);
  w.AddComponent(e, tr);
}

void RefereeSystemProcess(Match* match) {
  DO_VALIDATION;
  match->GetReferee()->Process();
}

void RunPlayerSystems(Match* match) {
  DO_VALIDATION;
  blunted::World& w = match->GetEcsWorld();
  for (blunted::Entity e : match->GetEcsPlayerEntities()) {
    PlayerMeta* meta = w.GetComponent<PlayerMeta>(e);
    if (!meta || !meta->is_active) continue;
    ControllerRef* cref = w.GetComponent<ControllerRef>(e);
    PlayerRef* pref = w.GetComponent<PlayerRef>(e);
    if (cref && cref->controller) cref->controller->Process();
    if (pref && pref->player && pref->player->CastHumanoid())
      pref->player->CastHumanoid()->Process();
  }
}
