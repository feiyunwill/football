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

#include "scene.hpp"

#include <cstddef>

namespace blunted {

Scene::Scene() { DO_VALIDATION; }

Scene::~Scene() { DO_VALIDATION; }

void Scene::Exit() {
  DO_VALIDATION;
  DetachAll();
}

void Scene::CreateSystemObjects(boost::intrusive_ptr<Object> object) {
  DO_VALIDATION;
  int observersSize = observers_.size();
  for (int i = 0; i < observersSize; i++) {
    DO_VALIDATION;
    ISceneInterpreter *sceneInterpreter =
        static_cast<ISceneInterpreter *>(observers_[i].get());
    sceneInterpreter->CreateSystemObject(object.get());
  }
}

bool Scene::SupportedObjectType(e_ObjectType objectType) const {
  // 2026-04-02 原 vector 线性比较；supported_object_types_ 已改为 bitset，用 test 并防止越界
  // for (size_t i = 0; i < supported_object_types_.size(); i++) {
  //   DO_VALIDATION;
  //   if (objectType == supported_object_types_[i]) return true;
  // }
  // return false;
  const std::size_t idx = static_cast<std::size_t>(objectType);
  DO_VALIDATION;
  if (idx >= supported_object_types_.size()) {
    return false;
  }
  return supported_object_types_.test(idx);
}

}
