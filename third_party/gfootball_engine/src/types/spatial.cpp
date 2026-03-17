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

#include "spatial.hpp"

#include "../scene/scene3d/node.hpp"

namespace blunted {

Spatial::Spatial(const std::string &name)
    : name_(name), parent_(nullptr), local_mode_(e_LocalMode_Relative) {
  DO_VALIDATION;
  scale_.Set(1, 1, 1);
  Vector axis(0, 0, -1);
  rotation_.SetAngleAxis(0, axis);
  position_.Set(0, 0, 0);
  aabb_.aabb.Reset();
  aabb_.dirty = false;
  InvalidateSpatialData();
}

Spatial::~Spatial() {
  DO_VALIDATION;
  parent_ = nullptr;
}

Spatial::Spatial(const Spatial &src) {
  DO_VALIDATION;
  name_ = src.GetName();
  position_ = src.position_;
  rotation_ = src.rotation_;
  scale_ = src.scale_;
  local_mode_ = src.local_mode_;
  aabb_.aabb = src.GetAABB();
  aabb_.dirty = false;
  parent_ = nullptr;
  InvalidateSpatialData();
}

void Spatial::SetLocalMode(e_LocalMode localMode) {
  DO_VALIDATION;
  local_mode_ = localMode;
  InvalidateBoundingVolume();
}

e_LocalMode Spatial::GetLocalMode() {
  DO_VALIDATION;
  return local_mode_;
}

void Spatial::SetName(const std::string &name) {
  DO_VALIDATION;
  name_ = name;
}

  const std::string Spatial::GetName() const {
    return name_.c_str();
  }

  void Spatial::SetParent(Node *parent) {
    DO_VALIDATION;
    parent_ = parent;
    InvalidateBoundingVolume();
  }

  void Spatial::SetPosition(const Vector3 &newPosition,
                            bool updateSpatialData) {
    DO_VALIDATION;
    position_ = newPosition;
    if (updateSpatialData) RecursiveUpdateSpatialData(e_SpatialDataType_Position);
  }

  Vector3 Spatial::GetPosition() const {
    return position_;
  }

  void Spatial::SetRotation(const Quaternion &newRotation,
                            bool updateSpatialData) {
    rotation_ = newRotation;
    if (updateSpatialData) RecursiveUpdateSpatialData(e_SpatialDataType_Both);
  }

  Quaternion Spatial::GetRotation() const {
    return rotation_;
  }

  void Spatial::SetScale(const Vector3 &newScale) {
    DO_VALIDATION;
    scale_ = newScale;
    RecursiveUpdateSpatialData(e_SpatialDataType_Rotation);
  }

  Vector3 Spatial::GetScale() const {
    return scale_;
  }

  Vector3 Spatial::GetDerivedPosition() const {
    if (dirty_derived_position_) {
      DO_VALIDATION;
      if (local_mode_ == e_LocalMode_Relative) {
        DO_VALIDATION;
        if (parent_) {
          DO_VALIDATION;
          const Quaternion parentDerivedRotation = parent_->GetDerivedRotation();
          const Vector3 parentDerivedScale = parent_->GetDerivedScale();
          const Vector3 parentDerivedPosition = parent_->GetDerivedPosition();

          cache_derived_position_.Set(parentDerivedRotation * (parentDerivedScale * GetPosition()));
          cache_derived_position_ += parentDerivedPosition;
        } else {
          cache_derived_position_ = GetPosition();
        }
      } else {
        cache_derived_position_ = GetPosition();
      }
      dirty_derived_position_ = false;
    }
    return cache_derived_position_;
  }

  Quaternion Spatial::GetDerivedRotation() const {
    if (dirty_derived_rotation_) {
      DO_VALIDATION;
      if (local_mode_ == e_LocalMode_Relative) {
        DO_VALIDATION;
        if (parent_) {
          DO_VALIDATION;
          cache_derived_rotation_ = (parent_->GetDerivedRotation() * GetRotation()).GetNormalized();
        } else {
          cache_derived_rotation_ = GetRotation();
        }
      } else {
        cache_derived_rotation_ = GetRotation();
      }
      dirty_derived_rotation_ = false;
    }
    return cache_derived_rotation_;
  }

  Vector3 Spatial::GetDerivedScale() const {
    if (dirty_derived_scale_) {
      DO_VALIDATION;
      if (local_mode_ == e_LocalMode_Relative) {
        DO_VALIDATION;
        if (parent_) {
          DO_VALIDATION;
          cache_derived_scale_ = parent_->GetDerivedScale() * GetScale();
        } else {
          cache_derived_scale_ = GetScale();
        }
      } else {
        cache_derived_scale_ = GetScale();
      }
      dirty_derived_scale_ = false;
    }
    return cache_derived_scale_;
  }

  void Spatial::InvalidateBoundingVolume() {
    bool changed = false;
    if (aabb_.dirty == false) {
      aabb_.dirty = true;
      aabb_.aabb.Reset();
      changed = true;
    }
    if (changed) if (parent_) parent_->InvalidateBoundingVolume();
  }

  void Spatial::InvalidateSpatialData() {
    DO_VALIDATION;
    dirty_derived_position_ = true;
    dirty_derived_rotation_ = true;
    dirty_derived_scale_ = true;
  }

  AABB Spatial::GetAABB() const {
    AABB tmp;
    tmp = aabb_.aabb;
    return tmp;
  }

}
