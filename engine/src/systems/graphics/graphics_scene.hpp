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

#ifndef _HPP_SYSTEMS_GRAPHICS_SCENE
#define _HPP_SYSTEMS_GRAPHICS_SCENE

#include "../../defines.hpp"

#include "../../scene/scene3d/scene3d.hpp"
#include "../../scene/scene2d/scene2d.hpp"

namespace blunted {

  class GraphicsSystem;

  class GraphicsScene {

    public:
      GraphicsScene(GraphicsSystem *graphicsSystem);
      virtual ~GraphicsScene() = default;

      virtual GraphicsSystem *GetGraphicsSystem();

      virtual ISystemObject *CreateSystemObject(Object* object);

      virtual boost::intrusive_ptr<ISceneInterpreter> GetInterpreter(e_SceneType sceneType);

    protected:
      GraphicsSystem *graphics_system_;
  };


  class GraphicsScene_Scene3DInterpreter : public IScene3DInterpreter {

    public:
      GraphicsScene_Scene3DInterpreter(GraphicsScene *caller);

      // 2026-04-02 现代 C++：override
      e_SystemType GetSystemType() const override { return e_SystemType_Graphics; }
      void OnLoad() override;
      void OnUnload() override;

      ISystemObject *CreateSystemObject(Object* object) override;

      void SetGravity(const Vector3 &gravity) override { DO_VALIDATION;}
      void SetErrorCorrection(float value) override { DO_VALIDATION;}
      void SetConstraintForceMixing(float value) override { DO_VALIDATION;}

    protected:
      GraphicsScene *caller_;

  };

  class GraphicsScene_Scene2DInterpreter : public IScene2DInterpreter {

    public:
      GraphicsScene_Scene2DInterpreter(GraphicsScene *caller);

      // 2026-04-02 现代 C++：override（与 Scene3D 侧一致）
      e_SystemType GetSystemType() const override { return e_SystemType_Graphics; }
      void OnLoad() override;
      void OnUnload() override;

      ISystemObject *CreateSystemObject(Object* object) override;

    protected:
      GraphicsScene *caller_;

  };

}

#endif
