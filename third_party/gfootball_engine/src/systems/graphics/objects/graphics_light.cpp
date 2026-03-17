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

#include "graphics_light.hpp"

#include "../../../main.hpp"
#include "../../../systems/graphics/rendering/r3d_messages.hpp"
#include "../graphics_scene.hpp"
#include "../graphics_system.hpp"
#include "graphics_geometry.hpp"

namespace blunted {

GraphicsLight::GraphicsLight(GraphicsScene *graphicsScene)
    : GraphicsObject(graphicsScene) {
  DO_VALIDATION;
  radius_ = 512;
  color_.Set(1, 1, 1);
  light_type_ = e_LightType_Point;
  shadow_ = false;
}

GraphicsLight::~GraphicsLight() { DO_VALIDATION; }

boost::intrusive_ptr<Interpreter> GraphicsLight::GetInterpreter(
    e_ObjectType objectType) {
  DO_VALIDATION;
  if (objectType == e_ObjectType_Light) {
    DO_VALIDATION;
    boost::intrusive_ptr<GraphicsLight_LightInterpreter> LightInterpreter(
        new GraphicsLight_LightInterpreter(this));
    return LightInterpreter;
  }
  Log(e_FatalError, "GraphicsLight", "GetInterpreter",
      "No appropriate interpreter found for this ObjectType");
  return boost::intrusive_ptr<GraphicsLight_LightInterpreter>();
}

void GraphicsLight::SetPosition(const Vector3 &newPosition) {
  DO_VALIDATION;
  position_ = newPosition;
}

  Vector3 GraphicsLight::GetPosition() const {
    return position_;
  }

  void GraphicsLight::SetColor(const Vector3 &newColor) {
    DO_VALIDATION;
    color_ = newColor;
  }

  Vector3 GraphicsLight::GetColor() const {
    return color_;
  }

  void GraphicsLight::SetRadius(float radius) {
    DO_VALIDATION;
    radius_ = radius;
  }

  float GraphicsLight::GetRadius() const {
    return radius_;
  }

  void GraphicsLight::SetType(e_LightType lightType) {
    DO_VALIDATION;
    light_type_ = lightType;
  }

  e_LightType GraphicsLight::GetType() const {
    return light_type_;
  }

  void GraphicsLight::SetShadow(bool shadow) {
    DO_VALIDATION;
    shadow_ = shadow;
  }

  bool GraphicsLight::GetShadow() const {
    return shadow_;
  }

  GraphicsLight_LightInterpreter::GraphicsLight_LightInterpreter(
      GraphicsLight *caller)
      : caller_(caller) {
    DO_VALIDATION;
  }

  void GraphicsLight_LightInterpreter::OnUnload() {
    DO_VALIDATION;



    Renderer3D *renderer3D = caller_->GetGraphicsScene()->GetGraphicsSystem()->GetRenderer3D();

    std::vector<ShadowMap>::iterator iter = caller_->shadow_maps_.begin();
    while (iter != caller_->shadow_maps_.end()) {
      DO_VALIDATION;
      renderer3D->BindFrameBuffer((*iter).frameBufferID);
      renderer3D->SetFrameBufferTexture2D(e_TargetAttachment_Depth, 0);
      renderer3D->DeleteFrameBuffer((*iter).frameBufferID);
      (*iter).visibleGeometry.clear();
      (*iter).texture.reset();
      iter = caller_->shadow_maps_.erase(iter);
    }

    delete caller_;
    caller_ = nullptr;
  }

  void GraphicsLight_LightInterpreter::SetValues(const Vector3 &color,
                                                 float radius) {
    DO_VALIDATION;
    caller_->SetColor(color);
    caller_->SetRadius(radius);
  }

  void GraphicsLight_LightInterpreter::SetType(e_LightType lightType) {
    DO_VALIDATION;
    caller_->SetType(lightType);
  }

  void GraphicsLight_LightInterpreter::SetShadow(bool shadow) {
    DO_VALIDATION;
    caller_->SetShadow(shadow);
  }

  bool GraphicsLight_LightInterpreter::GetShadow() {
    DO_VALIDATION;
    return caller_->GetShadow();
  }

  void GraphicsLight_LightInterpreter::OnSpatialChange(
      const Vector3 &position, const Quaternion &rotation) {
    DO_VALIDATION;
    caller_->SetPosition(position);
    //caller_->SetRotation(rotation);
  }

  void GraphicsLight_LightInterpreter::EnqueueShadowMap(
      boost::intrusive_ptr<Camera> camera,
      std::deque<boost::intrusive_ptr<Geometry> > visibleGeometry) {
    DO_VALIDATION;
    if (!caller_->GetShadow()) return;

    int index = -1;
    for (int i = 0; i < (signed int)caller_->shadow_maps_.size(); i++) {
      DO_VALIDATION;
      if (caller_->shadow_maps_[i].cameraName == camera->GetName()) {
        DO_VALIDATION;
        index = i;
      }
    }

    if (index == -1) {
      DO_VALIDATION;

      // does not yet exist

      ShadowMap map;
      map.texture = GetContext().texture_manager.Fetch(
          std::string(camera->GetName() + int_to_str(intptr_t(this))), false,
          false);  // false == don't try to use loader
      if (map.texture->GetResource()->GetID() == -1) {
        DO_VALIDATION;
        Renderer3D *renderer3D = caller_->GetGraphicsScene()->GetGraphicsSystem()->GetRenderer3D();
        map.texture->GetResource()->SetRenderer3D(renderer3D);
        map.texture->GetResource()->CreateTexture(e_InternalPixelFormat_DepthComponent16, e_PixelFormat_DepthComponent, 2048, 2048, false, false, false, true, true);

        // create framebuffer for shadowmap
        map.frameBufferID = renderer3D->CreateFrameBuffer();
        renderer3D->BindFrameBuffer(map.frameBufferID);
        // texture buffers
        renderer3D->SetFrameBufferTexture2D(e_TargetAttachment_Depth, map.texture->GetResource()->GetID());
        // all draw buffers must specify attachment points that have images attached. so to be sure, select none
        std::vector<e_TargetAttachment> targets;
        targets.push_back(e_TargetAttachment_None);
        renderer3D->SetRenderTargets(targets);
        targets.clear();

        if (!renderer3D->CheckFrameBufferStatus()) Log(e_FatalError, "Renderer3DMessage_CreateFrameBuffer", "Execute", "Could not create framebuffer");
        renderer3D->BindFrameBuffer(0);
        targets.push_back(e_TargetAttachment_Back);
        renderer3D->SetRenderTargets(targets);
        targets.clear();
      }

      map.cameraName = camera->GetName();

      caller_->shadow_maps_.push_back(map);
      index = caller_->shadow_maps_.size() - 1;
    }

    // add geometry

    std::deque < boost::intrusive_ptr<Geometry> >::iterator visibleGeometryIter = visibleGeometry.begin();
    while (visibleGeometryIter != visibleGeometry.end()) {
      DO_VALIDATION;
      boost::intrusive_ptr<GraphicsGeometry_GeometryInterpreter> interpreter = boost::static_pointer_cast<GraphicsGeometry_GeometryInterpreter>((*visibleGeometryIter)->GetInterpreter(e_SystemType_Graphics));

      // add buffers to visible geometry queue
      interpreter->GetVertexBufferQueue(caller_->shadow_maps_.at(index).visibleGeometry);

      // unlocksubject used to be here

      std::deque<VertexBufferQueueEntry>::iterator visibleGeometryBufferIter = caller_->shadow_maps_.at(index).visibleGeometry.end();
      visibleGeometryBufferIter--;
      (*visibleGeometryBufferIter).aabb = (*visibleGeometryIter)->GetAABB();

      visibleGeometryIter++;
    }

    //std::sort(caller_->shadow_maps_.at(index).visibleGeometry.begin(), caller_->shadow_maps_.at(index).visibleGeometry.end(), GLLI_SortVertexBufferQueueEntries);


    // all this is way too hardcoded and should somehow heed the camera bounding box better

    // projection matrix
    float left = -65; //65
    float right = 65;
    float bottom = -65;
    float top = 65;

    left = -75;
    right = 75;
    bottom = -75;
    top = 75;

    float nearCap = -150;//-80;
    float farCap = 150;//80;

    Matrix4 proj;
    proj.elements[0] = 2 / (right - left);
    proj.elements[5] = 2 / (top - bottom);
    proj.elements[10] = -2 / (farCap - nearCap);
    proj.elements[3] = -((right + left) / (right - left));
    proj.elements[7] = -((top + bottom) / (top - bottom));
    proj.elements[11] = -((farCap + nearCap) / (farCap - nearCap));
    proj.elements[15] = 1;
    Matrix4 identity = Matrix4(MATRIX4_IDENTITY);
    caller_->shadow_maps_.at(index).lightProjectionMatrix = identity * proj;

    // view matrix
    Quaternion ident(QUATERNION_IDENTITY);
    Vector3 pos = (caller_->GetPosition().GetNormalized(Vector3(0, 0, -1))) + camera->GetDerivedPosition().Get2D() + Vector3(0, 70, 0);
    Quaternion rot; rot = caller_->GetPosition().GetNormalized(Vector3(0, 0, -1));
    caller_->shadow_maps_.at(index).lightViewMatrix.ConstructInverse(pos, Vector3(1, 1, 1), rot);
  }

  ShadowMap GraphicsLight_LightInterpreter::GetShadowMap(
      const std::string &camName) {
    DO_VALIDATION;
    for (unsigned int i = 0; i < caller_->shadow_maps_.size(); i++) {
      DO_VALIDATION;
      if (caller_->shadow_maps_[i].cameraName == camName) {
        DO_VALIDATION;
        return caller_->shadow_maps_[i];
      }
    }

    ShadowMap empty;
    return empty;
  }

  void GraphicsLight_LightInterpreter::OnPoke() {
    DO_VALIDATION;
    if (!caller_->GetShadow()) return;

    for (auto &map : caller_->shadow_maps_) {
      DO_VALIDATION;
      Renderer3D *renderer = caller_->GetGraphicsScene()->GetGraphicsSystem()->GetRenderer3D();
      renderer->UseShader("zphase");
      renderer->BindFrameBuffer(map.frameBufferID);

      int shadowW, shadowH;
      map.texture->GetResource()->GetSize(shadowW, shadowH);
      renderer->SetViewport(0, 0, shadowW, shadowH);

      renderer->ClearBuffer(Vector3(0, 0, 0), true, false);

      renderer->SetMatrix("projectionMatrix", map.lightProjectionMatrix);
      renderer->SetMatrix("viewMatrix", map.lightViewMatrix);

      std::vector<e_TargetAttachment> targets;
      targets.push_back(e_TargetAttachment_None);
      renderer->SetRenderTargets(targets);
      targets.clear();

      renderer->SetCullingMode(e_CullingMode_Front);
      renderer->SetBlendingMode(e_BlendingMode_Off);
      renderer->SetDepthFunction(e_DepthFunction_Less);
      renderer->SetDepthTesting(true);
      renderer->SetDepthMask(true);

      renderer->RenderVertexBuffer(map.visibleGeometry, e_RenderMode_GeometryOnly);

      renderer->BindFrameBuffer(0);
      renderer->UseShader("");

      targets.push_back(e_TargetAttachment_Back);
      renderer->SetRenderTargets(targets);
      targets.clear();

      // restore context viewport
      int width, height, bpp;
      renderer->GetContextSize(width, height, bpp);
      renderer->SetViewport(0, 0, width, height);
      renderer->SetCullingMode(e_CullingMode_Back);
      map.visibleGeometry.clear();
    }
  }
}
