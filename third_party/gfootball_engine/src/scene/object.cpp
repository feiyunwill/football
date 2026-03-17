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

#include "object.hpp"

#include "../systems/isystemobject.hpp"

namespace blunted {

Object::Object(std::string name, e_ObjectType objectType)
    : Spatial(name), object_type_(objectType) {
  DO_VALIDATION;
  update_spatial_data_after_poke_.have_to_ = false;
  update_spatial_data_after_poke_.exclude_system_ = e_SystemType_None;
  poke_priority_ = 0;
  enabled_ = true;
}

Object::~Object() {
  DO_VALIDATION;
  if (observers_.size() != 0) {
    DO_VALIDATION;
    Log(e_FatalError, "Object", "~Object",
        "Observer(s) still present at destruction time (spatial named: " +
            GetName() + ")");
  }
}

Object::Object(const Object &src) : Subject<Interpreter>(), Spatial(src) {
  DO_VALIDATION;
  object_type_ = src.object_type_;
  properties_ = src.properties_;
  request_properties_.AddProperties(src.request_properties_);
  update_spatial_data_after_poke_.have_to_ = false;
  update_spatial_data_after_poke_.exclude_system_ = e_SystemType_None;
  poke_priority_ = src.GetPokePriority();
  enabled_ = src.enabled_;
  assert(observers_.size() == 0);
}

Object::Object(Object &&src) noexcept
    : Subject<Interpreter>(), Spatial(src) {
  object_type_ = src.object_type_;
  properties_ = std::move(src.properties_);
  request_properties_ = std::move(src.request_properties_);
  update_spatial_data_after_poke_ = src.update_spatial_data_after_poke_;
  poke_priority_ = src.poke_priority_;
  enabled_ = src.enabled_;
}

void Object::Exit() {
  DO_VALIDATION;
  // printf("detaching all observers from object named %s\n",
  // GetName().c_str());
  DetachAll();
}

inline e_ObjectType Object::GetObjectType() {
  DO_VALIDATION;
  return object_type_;
}

  const Properties &Object::GetProperties() const {
    return properties_;
  }

  bool Object::PropertyExists(const char *property) const {
    return properties_.Exists(property);
  }

  const std::string &Object::GetProperty(const char *property) const {
    return properties_.Get(property);
  }

  void Object::SetProperties(const Properties &props) {
    DO_VALIDATION;
    properties_.AddProperties(props);
  }

  void Object::SetProperties(Properties &&props) {
    DO_VALIDATION;
    properties_.AddProperties(std::move(props));
  }

  void Object::SetProperty(const char *name, const char *value) {
    DO_VALIDATION;
    properties_.Set(name, value);
  }

  bool Object::RequestPropertyExists(const char *property) const {
    return request_properties_.Exists(property);
  }

  std::string Object::GetRequestProperty(const char *property) const {
    return request_properties_.Get(property);
  }

  void Object::AddRequestProperty(const char *property) {
    DO_VALIDATION;
    request_properties_.Set(property, "");
  }

  void Object::SetRequestProperty(const char *property, const char *value) {
    DO_VALIDATION;
    request_properties_.Set(property, value);
  }

  void Object::Synchronize() {
    DO_VALIDATION;
    boost::shared_ptr<Interpreter> result;
    int observersSize = observers_.size();
    for (int i = 0; i < observersSize; i++) {
      DO_VALIDATION;
      boost::intrusive_ptr<Interpreter> interpreter = boost::static_pointer_cast<Interpreter>(observers_[i]);
      interpreter->OnSynchronize();
    }
  }

  void Object::Poke(e_SystemType targetSystemType) { DO_VALIDATION; }

  inline void Object::RecursiveUpdateSpatialData(
      e_SpatialDataType spatialDataType, e_SystemType excludeSystem) {
    DO_VALIDATION;
  }

  boost::intrusive_ptr<Interpreter> Object::GetInterpreter(
      e_SystemType targetSystemType) {
    DO_VALIDATION;
    boost::intrusive_ptr<Interpreter> result;
    int observersSize = observers_.size();
    for (int i = 0; i < observersSize; i++) {
      DO_VALIDATION;
      boost::intrusive_ptr<Interpreter> interpreter = boost::static_pointer_cast<Interpreter>(observers_[i]);
      if (interpreter->GetSystemType() == targetSystemType) result = interpreter;
    }
    return result;
  }
}
