// Copyright 2019 Google LLC & Bastiaan Konings
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//

#ifndef _HPP_ECS_TRANSFORM
#define _HPP_ECS_TRANSFORM

#include "../base/math/vector3.hpp"
#include "../base/math/quaternion.hpp"

namespace blunted {

/// 与 Spatial 对齐的变换组件，便于同步到 Node（2025-03-17 ECS 迁移）
struct Transform {
  Vector3 position;
  Quaternion rotation;
  Vector3 scale;

  Transform() = default;
  Transform(const Vector3& p, const Quaternion& r, const Vector3& s)
      : position(p), rotation(r), scale(s) {}
};

}  // namespace blunted

#endif
