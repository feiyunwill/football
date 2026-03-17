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

#include "light.hpp"

#include "camera.hpp"
#include "geometry.hpp"

#include "../../systems/isystemobject.hpp"

namespace blunted {

Light::Light(std::string name) : Object(name, e_ObjectType_Light) {
  DO_VALIDATION;
  radius_ = 512;
  color_.Set(1, 1, 1);
  light_type_ = e_LightType_Point;
  shadow_ = false;
}

Light::~Light() { DO_VALIDATION; }

void Light::Exit() {
  DO_VALIDATION;  // ATOMIC

  int observersSize = observers_.size();
  for (int i = 0; i < observersSize; i++) {
    DO_VALIDATION;
    ILightInterpreter *LightInterpreter =
        static_cast<ILightInterpreter *>(observers_[i].get());
    LightInterpreter->OnUnload();
  }

  Object::Exit();
}

void Light::SetColor(const Vector3 &color) {
  DO_VALIDATION;
  color_ = color;
  UpdateValues();
}

  Vector3 Light::GetColor() const {
    Vector3 retColor = color_;
    return retColor;

  }

  void Light::SetRadius(float radius) {
    DO_VALIDATION;
    radius_ = radius;
    UpdateValues();

    InvalidateBoundingVolume();
  }

  float Light::GetRadius() const {
    float rad = radius_;
    return rad;
  }

  void Light::SetType(e_LightType lightType) {
    DO_VALIDATION;

    light_type_ = lightType;

    int observersSize = observers_.size();
    for (int i = 0; i < observersSize; i++) {
      DO_VALIDATION;
      ILightInterpreter *LightInterpreter = static_cast<ILightInterpreter*>(observers_[i].get());
      LightInterpreter->SetType(lightType);
    }
  }

  e_LightType Light::GetType() const {
    e_LightType theType = light_type_;
    return theType;
  }

  void Light::SetShadow(bool shadow) {
    DO_VALIDATION;

    shadow_ = shadow;

    int observersSize = observers_.size();
    for (int i = 0; i < observersSize; i++) {
      DO_VALIDATION;
      ILightInterpreter *LightInterpreter = static_cast<ILightInterpreter*>(observers_[i].get());
      LightInterpreter->SetShadow(shadow);
    }
  }

  bool Light::GetShadow() const {
    return shadow_;
  }

  void Light::UpdateValues() {
    DO_VALIDATION;

    int observersSize = observers_.size();
    for (int i = 0; i < observersSize; i++) {
      DO_VALIDATION;
      ILightInterpreter *LightInterpreter = static_cast<ILightInterpreter*>(observers_[i].get());
      LightInterpreter->SetValues(color_, radius_);
    }
  }

  void Light::EnqueueShadowMap(
      boost::intrusive_ptr<Camera> camera,
      std::deque<boost::intrusive_ptr<Geometry> > visibleGeometry) {
    DO_VALIDATION;

    int observersSize = observers_.size();
    for (int i = 0; i < observersSize; i++) {
      DO_VALIDATION;
      ILightInterpreter *LightInterpreter = static_cast<ILightInterpreter*>(observers_[i].get());
      LightInterpreter->EnqueueShadowMap(camera, visibleGeometry);
    }
  }

  void Light::Poke(e_SystemType targetSystemType) {
    DO_VALIDATION;

    int observersSize = observers_.size();
    for (int i = 0; i < observersSize; i++) {
      DO_VALIDATION;
      ILightInterpreter *LightInterpreter = static_cast<ILightInterpreter*>(observers_[i].get());
      if (LightInterpreter->GetSystemType() == targetSystemType) LightInterpreter->OnPoke();
    }
  }

  void Light::RecursiveUpdateSpatialData(e_SpatialDataType spatialDataType,
                                         e_SystemType excludeSystem) {
    DO_VALIDATION;
    InvalidateSpatialData();
    InvalidateBoundingVolume();


    int observersSize = observers_.size();
    for (int i = 0; i < observersSize; i++) {
      DO_VALIDATION;
      if (observers_[i]->GetSystemType() != excludeSystem) {
        DO_VALIDATION;
        ILightInterpreter *lightInterpreter = static_cast<ILightInterpreter*>(observers_[i].get());
        lightInterpreter->OnSpatialChange(GetDerivedPosition(), GetDerivedRotation());
      }
    }
  }

  AABB Light::GetAABB() const {
    //aabb.Lock();
    if (aabb.dirty == true) {
      DO_VALIDATION;
      Vector3 pos = GetDerivedPosition();
      aabb.aabb.minxyz = pos - radius_;
      aabb.aabb.maxxyz = pos + radius_;
      aabb.aabb.MakeDirty();
      aabb.dirty = false;
    }
    AABB tmp = aabb.aabb;
    //aabb.Unlock();
    return tmp;
  }

}
