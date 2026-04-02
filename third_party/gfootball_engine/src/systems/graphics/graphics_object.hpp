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

#ifndef _HPP_SYSTEMS_GRAPHICS_OBJECT
#define _HPP_SYSTEMS_GRAPHICS_OBJECT

#include "../../defines.hpp"

#include "../../systems/isystemobject.hpp"

namespace blunted {

  class GraphicsScene;

  class GraphicsObject : public ISystemObject {

    public:
      GraphicsObject(GraphicsScene *graphicsScene);
      // 2026-04-02 现代 C++：多态系统对象根类显式禁值语义（基类 ISystemObject 已 delete）
      GraphicsObject(const GraphicsObject &) = delete;
      GraphicsObject &operator=(const GraphicsObject &) = delete;
      GraphicsObject(GraphicsObject &&) = delete;
      GraphicsObject &operator=(GraphicsObject &&) = delete;

      virtual ~GraphicsObject() = default;

      virtual boost::intrusive_ptr<Interpreter> GetInterpreter(e_ObjectType objectType) = 0;

      GraphicsScene *GetGraphicsScene();

    protected:
      GraphicsScene *graphics_scene_;

  };

}

#endif
