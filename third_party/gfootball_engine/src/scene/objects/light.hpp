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

#ifndef _HPP_OBJECT_LIGHT
#define _HPP_OBJECT_LIGHT

#include "../../defines.hpp"
#include "../../scene/object.hpp"
#include "../../types/interpreter.hpp"
#include "../../base/math/quaternion.hpp"
#include "../../base/math/vector3.hpp"
#include "../../base/geometry/aabb.hpp"

#include <compare>

namespace blunted {

  class Camera;
  class Geometry;

  enum e_LightType {
    e_LightType_Directional,
    e_LightType_Point
  };

  constexpr std::strong_ordering operator<=>(e_LightType a, e_LightType b) {
    return static_cast<int>(a) <=> static_cast<int>(b);
  }

  class Light : public Object {

    public:
      Light(std::string name);
      // 2026-04-02 现代 C++：override
      // virtual ~Light();
      ~Light() override;

      // virtual void Exit();
      void Exit() override;

      virtual void SetColor(const Vector3 &color);
      virtual Vector3 GetColor() const;

      virtual void SetRadius(float radius);
      virtual float GetRadius() const;

      virtual void SetType(e_LightType lightType);
      virtual e_LightType GetType() const;

      virtual void SetShadow(bool shadow);
      virtual bool GetShadow() const;

      virtual void UpdateValues();

      virtual void EnqueueShadowMap(boost::intrusive_ptr<Camera> camera, std::deque < boost::intrusive_ptr<Geometry> > visibleGeometry);
      // virtual void Poke(e_SystemType targetSystemType);
      void Poke(e_SystemType targetSystemType) override;

      // virtual void RecursiveUpdateSpatialData(e_SpatialDataType spatialDataType, e_SystemType excludeSystem = e_SystemType_None);
      void RecursiveUpdateSpatialData(e_SpatialDataType spatialDataType,
                                      e_SystemType excludeSystem =
                                          e_SystemType_None) override;

      // virtual AABB GetAABB() const;
      AABB GetAABB() const override;

    protected:
      Vector3 color_;
      float radius_ = 0.0f;
      e_LightType light_type_;
      bool shadow_ = false;

  };

  class ILightInterpreter : public Interpreter {

    public:
      virtual void OnUnload() = 0;
      virtual void SetValues(const Vector3 &color, float radius) = 0;
      virtual void SetType(e_LightType lightType) = 0;
      virtual void SetShadow(bool shadow) = 0;
      virtual bool GetShadow() = 0;
      virtual void OnSpatialChange(const Vector3 &position, const Quaternion &rotation) = 0;
      virtual void EnqueueShadowMap(boost::intrusive_ptr<Camera> camera, std::deque < boost::intrusive_ptr<Geometry> > visibleGeometry) = 0;
      virtual void OnPoke() = 0;

    protected:

  };

}

#endif
