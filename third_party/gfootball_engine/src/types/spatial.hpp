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

#ifndef _HPP_SPATIAL
#define _HPP_SPATIAL

#include <compare>

#include "../defines.hpp"

#include "../types/refcounted.hpp"

#include "../base/math/vector3.hpp"
#include "../base/math/quaternion.hpp"

#include "../base/geometry/aabb.hpp"

#include "../systems/isystem.hpp"

namespace blunted {

  class Node;

  enum e_LocalMode {
    e_LocalMode_Relative,
    e_LocalMode_Absolute
  };
  constexpr std::strong_ordering operator<=>(e_LocalMode a, e_LocalMode b) {
    return static_cast<int>(a) <=> static_cast<int>(b);
  }

  enum e_SpatialDataType {
    e_SpatialDataType_Position,
    e_SpatialDataType_Rotation,
    e_SpatialDataType_Both
  };
  constexpr std::strong_ordering operator<=>(e_SpatialDataType a, e_SpatialDataType b) {
    return static_cast<int>(a) <=> static_cast<int>(b);
  }

  enum e_Streaming_DataType {
    e_Streaming_DataType_File,
    e_Streaming_DataType_String
  };
  constexpr std::strong_ordering operator<=>(e_Streaming_DataType a, e_Streaming_DataType b) {
    return static_cast<int>(a) <=> static_cast<int>(b);
  }

  /// spatial object
  /** an object in a scene. responsibilities:
        - stream loading/saving
        - guarantee atomicity
  */

  class Spatial : public RefCounted {

    public:
      Spatial(const std::string &name);
      virtual ~Spatial();

      Spatial(const Spatial &src);

      virtual void Exit() = 0;

      void SetLocalMode(e_LocalMode localMode);
      e_LocalMode GetLocalMode();

      void SetName(const std::string &name);
      virtual const std::string GetName() const;

      void SetParent(Node *parent);

      virtual void SetPosition(const Vector3 &newPosition, bool updateSpatialData = true);
      virtual Vector3 GetPosition() const;

      virtual void SetRotation(const Quaternion &newRotation, bool updateSpatialData = true);
      virtual Quaternion GetRotation() const;

      virtual void SetScale(const Vector3 &newScale);
      virtual Vector3 GetScale() const;

      virtual Vector3 GetDerivedPosition() const;
      virtual Quaternion GetDerivedRotation() const;
      virtual Vector3 GetDerivedScale() const;

      virtual void RecursiveUpdateSpatialData(e_SpatialDataType spatialDataType, e_SystemType excludeSystem = e_SystemType_None) = 0;

      virtual void InvalidateBoundingVolume();
      virtual void InvalidateSpatialData();

      virtual AABB GetAABB() const;

    protected:
      // 2025-03-17 Google 规范：Class data members 末尾下划线（cpp-google-style）
      std::string name_;
      Node *parent_ = nullptr;
      Vector3 position_;
      Quaternion rotation_;
      Vector3 scale_;
      mutable bool dirty_derived_position_ = false;
      mutable bool dirty_derived_rotation_ = false;
      mutable bool dirty_derived_scale_ = false;
      mutable Vector3 cache_derived_position_;
      mutable Quaternion cache_derived_rotation_;
      mutable Vector3 cache_derived_scale_;
      e_LocalMode local_mode_;
      mutable AABBCache aabb_;

  };

}

#endif
