// Copyright 2019 Google LLC & Bastiaan Konings
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//

// 2025-03-17 ECS 迁移：组件 ProcessState 实现，与 set_state 兼容

#include "ecs_components.hpp"

void BallComponent::ProcessState(EnvState* state) {
  DO_VALIDATION;
  state->process(momentum);
  state->process(rotation_ms);
  for (unsigned int x = 0; x < sizeof(predictions) / sizeof(predictions[0]); x++) {
    state->process(predictions[x]);
  }
  state->process(valid_predictions);
  state->process(orientPrediction);
  int size = static_cast<int>(ballPosHistory.size());
  state->process(size);
  ballPosHistory.resize(size);
  for (auto& i : ballPosHistory) {
    DO_VALIDATION;
    state->process(i);
  }
  state->process(positionBuffer);
  state->process(orientationBuffer);
  state->process(ballTouchesNet);
}

void PlayerMeta::ProcessState(EnvState* state) {
  DO_VALIDATION;
  state->process(stable_id);
  state->process(team_id);
  state->process(is_active);
  // player_data 指针不序列化，由 Match/Team 在 set_state 后按 stable_id 重新绑定
}
