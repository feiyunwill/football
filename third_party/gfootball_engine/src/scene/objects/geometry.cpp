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

#include "geometry.hpp"

#include "../../base/log.hpp"
#include "../../main.hpp"
#include "../../systems/isystemobject.hpp"

#include "../../main.hpp"

namespace blunted {

Geometry::Geometry(std::string name, e_ObjectType objectType)
    : Object(name, objectType) {
  DO_VALIDATION;
}

Geometry::Geometry(const Geometry &src, const std::string &postfix)
    : Object(src) {
  DO_VALIDATION;
  if (src.geometry_data_ != boost::intrusive_ptr<Resource<GeometryData> >()) {
    DO_VALIDATION;
    std::string srcName = src.geometry_data_->GetIdentString();
    bool alreadyThere = false;


    geometry_data_ = (GetContext().geometry_manager.FetchCopy(
        srcName, srcName + postfix, alreadyThere));
    // geometryData = (GetContext().geometry_manager.Fetch(srcName, false,
    // alreadyThere, true));
  }
  InvalidateBoundingVolume();
}

Geometry::~Geometry() { DO_VALIDATION; }

void Geometry::Exit() {
  DO_VALIDATION;  // ATOMIC

  int observersSize = observers_.size();
  for (int i = 0; i < observersSize; i++) {
    DO_VALIDATION;
    IGeometryInterpreter *geometryInterpreter =
        static_cast<IGeometryInterpreter *>(observers_[i].get());
    geometryInterpreter->OnUnload();
  }

  Object::Exit();

  if (geometry_data_) geometry_data_.reset();

  InvalidateBoundingVolume();
}

void Geometry::SetGeometryData(
    boost::intrusive_ptr<Resource<GeometryData> > geometryData) {
  DO_VALIDATION;


  geometry_data_ = geometryData;

  int observersSize = observers_.size();
  for (int i = 0; i < observersSize; i++) {
    DO_VALIDATION;
    IGeometryInterpreter *geometryInterpreter =
        static_cast<IGeometryInterpreter *>(observers_[i].get());
    geometryInterpreter->OnLoad(this);
  }

  InvalidateBoundingVolume();
}

void Geometry::OnUpdateGeometryData(bool updateMaterials) {
  DO_VALIDATION;
  GetTracker()->setDisabled(true);
  if (GetGameConfig().render) {
    int observersSize = observers_.size();
    for (int i = 0; i < observersSize; i++) {
      DO_VALIDATION;
      IGeometryInterpreter *geometryInterpreter =
          static_cast<IGeometryInterpreter *>(observers_[i].get());
      geometryInterpreter->OnUpdateGeometry(this, updateMaterials);
    }
    InvalidateBoundingVolume();
  }
  GetTracker()->setDisabled(false);
}

boost::intrusive_ptr<Resource<GeometryData> > Geometry::GetGeometryData() {
  DO_VALIDATION;
  return geometry_data_;
}

void Geometry::Poke(e_SystemType targetSystemType) {
  DO_VALIDATION;

  int observersSize = observers_.size();
  for (int i = 0; i < observersSize; i++) {
    DO_VALIDATION;

    IGeometryInterpreter *geometryInterpreter =
        static_cast<IGeometryInterpreter *>(observers_[i].get());
    if (geometryInterpreter->GetSystemType() == targetSystemType)
      geometryInterpreter->OnPoke();
  }

  // did a system object feedback a new pos/rot?

  if (update_spatial_data_after_poke_.have_to_) {
    DO_VALIDATION;
    RecursiveUpdateSpatialData(e_SpatialDataType_Both,
                               update_spatial_data_after_poke_.exclude_system_);
    update_spatial_data_after_poke_.have_to_ = false;
    update_spatial_data_after_poke_.exclude_system_ = e_SystemType_None;
  }
}

void Geometry::RecursiveUpdateSpatialData(e_SpatialDataType spatialDataType,
                                          e_SystemType excludeSystem) {
  DO_VALIDATION;
  InvalidateSpatialData();
  InvalidateBoundingVolume();

  GetTracker()->setDisabled(true);
  if (GetGameConfig().render) {
    int observersSize = observers_.size();
    for (int i = 0; i < observersSize; i++) {
      DO_VALIDATION;
      if (observers_[i]->GetSystemType() != excludeSystem) {
        DO_VALIDATION;
        IGeometryInterpreter *geometryInterpreter =
            static_cast<IGeometryInterpreter *>(observers_[i].get());
        if (spatialDataType == e_SpatialDataType_Position) {
          DO_VALIDATION;
          geometryInterpreter->OnMove(GetDerivedPosition());
        } else if (spatialDataType == e_SpatialDataType_Rotation) {
          DO_VALIDATION;
          // need to update both: position relies on rotation
          geometryInterpreter->OnMove(GetDerivedPosition());
          geometryInterpreter->OnRotate(GetDerivedRotation());
        } else if (spatialDataType == e_SpatialDataType_Both) {
          DO_VALIDATION;
          geometryInterpreter->OnMove(GetDerivedPosition());
          geometryInterpreter->OnRotate(GetDerivedRotation());
        }
      }
    }
  }
  GetTracker()->setDisabled(false);
}

  AABB Geometry::GetAABB() const {
    if (aabb.dirty == true) {
      DO_VALIDATION;
      assert(geometry_data_->GetResource());
      aabb.aabb = geometry_data_->GetResource()->GetAABB() * GetDerivedRotation() + GetDerivedPosition();
      aabb.dirty = false;
    }

    AABB tmp = aabb.aabb;
    return tmp;
  }

}
