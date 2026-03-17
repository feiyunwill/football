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

#include "graphics_system.hpp"

#include "graphics_scene.hpp"

#include "../../base/log.hpp"
#include "../../base/utils.hpp"

#include "rendering/r3d_messages.hpp"

namespace blunted {

GraphicsSystem::GraphicsSystem() { DO_VALIDATION; }

GraphicsSystem::~GraphicsSystem() { DO_VALIDATION; }

void GraphicsSystem::Initialize(bool render, int width, int height) {
  DO_VALIDATION;

  if (render) {
    renderer_3d_ = new OpenGLRenderer3D();
  } else {
    renderer_3d_ = new MockRenderer3D();
  }
  width_ = width;
  height_ = height;
  bpp_ = 32;
  if (!static_cast<Renderer3D *>(renderer_3d_)
           ->CreateContext(width_, height_, bpp_, false)) {
    DO_VALIDATION;
    Log(e_FatalError, "GraphicsSystem", "Initialize",
        "Could not create context");
  }

  task_ = new GraphicsTask(this);
}

void GraphicsSystem::SetContext() {
  if (renderer_3d_) {
    renderer_3d_->SetContext();
  }
}

void GraphicsSystem::DisableContext() {
  if (renderer_3d_) {
    renderer_3d_->DisableContext();
  }
}

const screenshoot &GraphicsSystem::GetScreen() {
  return renderer_3d_->GetScreen();
}

void GraphicsSystem::Exit() {
  DO_VALIDATION;
  delete task_;
  task_ = nullptr;

  delete renderer_3d_;
  renderer_3d_ = nullptr;
}

  e_SystemType GraphicsSystem::GetSystemType() const {
    return system_type_;
  }

  GraphicsScene *GraphicsSystem::Create2DScene(
      boost::shared_ptr<IScene> scene) {
    DO_VALIDATION;
    GraphicsScene *graphicsScene = new GraphicsScene(this);
    scene->Attach(graphicsScene->GetInterpreter(e_SceneType_Scene2D));
    return graphicsScene;
  }

  GraphicsScene *GraphicsSystem::Create3DScene(
      boost::shared_ptr<IScene> scene) {
    DO_VALIDATION;
    GraphicsScene *graphicsScene = new GraphicsScene(this);
    scene->Attach(graphicsScene->GetInterpreter(e_SceneType_Scene3D));
    return graphicsScene;
  }

  GraphicsTask *GraphicsSystem::GetTask() {
    DO_VALIDATION;
    return task_;
  }

  Renderer3D *GraphicsSystem::GetRenderer3D() {
    DO_VALIDATION;
    return renderer_3d_;
  }

  MessageQueue<Overlay2DQueueEntry> &GraphicsSystem::GetOverlay2DQueue() {
    DO_VALIDATION;
    return overlay_2d_queue_;
  }
}
