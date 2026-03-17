// Copyright 2019 Google LLC & Bastiaan Konings
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//

#ifndef _HPP_ECS_ENTITY
#define _HPP_ECS_ENTITY

#include <cstdint>

namespace blunted {

/// ECS 实体：仅 ID，表示可追踪对象（2025-03-17 ECS 迁移，计划阶段 1）
using Entity = std::uint64_t;

constexpr Entity kNullEntity = 0;

}  // namespace blunted

#endif
