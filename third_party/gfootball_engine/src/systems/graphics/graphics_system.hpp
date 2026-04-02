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

#ifndef _HPP_SYSTEMS_GRAPHICS_SYSTEM
#define _HPP_SYSTEMS_GRAPHICS_SYSTEM

#include "../../defines.hpp"

#include "../../types/messagequeue.hpp"
#include "../../systems/isystem.hpp"
#include "../../systems/graphics/rendering/opengl_renderer3d.hpp"

#include "../../scene/iscene.hpp"

#include "graphics_task.hpp"

#include "resources/texture.hpp"
#include "resources/vertexbuffer.hpp"

#include "../../managers/resourcemanager.hpp"

namespace blunted {

  class Renderer3D;
  class GraphicsScene;

  class GraphicsSystem {

    public:
      GraphicsSystem();
      // 2026-04-02 现代 C++：grep 无按值/拷贝使用；禁切片拷贝移动
      GraphicsSystem(const GraphicsSystem &) = delete;
      GraphicsSystem &operator=(const GraphicsSystem &) = delete;
      GraphicsSystem(GraphicsSystem &&) = delete;
      GraphicsSystem &operator=(GraphicsSystem &&) = delete;

      virtual ~GraphicsSystem();

      virtual void Initialize(bool render, int width, int height);
      virtual void Exit();
      void SetContext();
      void DisableContext();
      const screenshoot& GetScreen();

      e_SystemType GetSystemType() const;

      GraphicsScene *Create2DScene(boost::shared_ptr<IScene> scene);
      GraphicsScene *Create3DScene(boost::shared_ptr<IScene> scene);

      GraphicsTask *GetTask();
      virtual Renderer3D *GetRenderer3D();

      MessageQueue<Overlay2DQueueEntry> &GetOverlay2DQueue();

      Vector3 GetContextSize() { DO_VALIDATION; return Vector3(width_, height_, bpp_); }

      virtual std::string GetName() const { return "graphics"; }

    protected:
      // 2025-03-17 Google 规范：Class data members 末尾下划线（cpp-google-style）
      const e_SystemType system_type_ = e_SystemType_Graphics;
      Renderer3D *renderer_3d_ = nullptr;
      GraphicsTask *task_ = nullptr;
      MessageQueue<Overlay2DQueueEntry> overlay_2d_queue_;
      int width_ = 0, height_ = 0, bpp_ = 0;

  };

}

#endif
