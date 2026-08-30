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

#ifndef _HPP_GRAPHICS3D_OPENGL
#define _HPP_GRAPHICS3D_OPENGL
#ifdef __linux__
#include <EGL/egl.h>
#endif

#include "interface_renderer3d.hpp"

namespace blunted {

  class OpenGLRenderer3D : public Renderer3D {

    public:
      OpenGLRenderer3D();
      // 2026-04-02 现代 C++：具体渲染器禁切片拷贝/移动
      OpenGLRenderer3D(const OpenGLRenderer3D &) = delete;
      OpenGLRenderer3D &operator=(const OpenGLRenderer3D &) = delete;
      OpenGLRenderer3D(OpenGLRenderer3D &&) = delete;
      OpenGLRenderer3D &operator=(OpenGLRenderer3D &&) = delete;

      void SetContext() override;
      void DisableContext() override;
      const screenshoot& GetScreen() override;
      ~OpenGLRenderer3D() override;

      void SwapBuffers() override;

      void SetMatrix(const std::string &shaderUniformName, const Matrix4 &matrix) override;

      void RenderOverlay2D(const std::vector<Overlay2DQueueEntry> &overlay2DQueue) override;
      void RenderOverlay2D() override;
      void RenderLights(std::deque<LightQueueEntry> &lightQueue, const Matrix4 &projectionMatrix, const Matrix4 &viewMatrix) override;


      // --- new & improved

      // init & exit
      bool CreateContext(int width, int height, int bpp, bool fullscreen) override;
      void Exit() override;

      int CreateView(float x_percent, float y_percent, float width_percent, float height_percent) override;
      View &GetView(int viewID) override;
      void DeleteView(int viewID) override;

      // general
      void SetCullingMode(e_CullingMode cullingMode) override;
      void SetBlendingMode(e_BlendingMode blendingMode) override;
      void SetDepthFunction(e_DepthFunction depthFunction) override;
      void SetDepthTesting(bool OnOff) override;
      void SetDepthMask(bool OnOff) override;
      void SetBlendingFunction(e_BlendingFunction blendingFunction1, e_BlendingFunction blendingFunction2) override;
      void SetTextureMode(e_TextureMode textureMode) override;
      void SetColor(const Vector3 &color, float alpha) override;
      void SetColorMask(bool r, bool g, bool b, bool alpha) override;

      void ClearBuffer(const Vector3 &color, bool clearDepth, bool clearColor) override;

      Matrix4 CreatePerspectiveMatrix(float aspectRatio, float nearCap = -1, float farCap = -1) override;
      Matrix4 CreateOrthoMatrix(float left, float right, float bottom, float top, float nearCap = -1, float farCap = -1) override;

      // vertex buffers
      VertexBufferID CreateVertexBuffer(float *vertices, unsigned int verticesDataSize, const std::vector<unsigned int>& indices, e_VertexBufferUsage usage) override;
      void UpdateVertexBuffer(VertexBufferID vertexBufferID, float *vertices, unsigned int verticesDataSize) override;
      void DeleteVertexBuffer(VertexBufferID vertexBufferID) override;
      void RenderVertexBuffer(const std::deque<VertexBufferQueueEntry> &vertexBufferQueue, e_RenderMode renderMode = e_RenderMode_Full) override;

      // lights
      void SetLight(const Vector3 &position, const Vector3 &color, float radius) override;

      // textures
      int CreateTexture(e_InternalPixelFormat internalPixelFormat, e_PixelFormat pixelFormat, int width, int height, bool alpha = false, bool repeat = true, bool mipmaps = true, bool filter = true, bool multisample = false, bool compareDepth = false) override;
      void ResizeTexture(int textureID, SDL_Surface *source, e_InternalPixelFormat internalPixelFormat, e_PixelFormat pixelFormat, bool alpha = false, bool mipmaps = true) override;
      void UpdateTexture(int textureID, SDL_Surface *source, bool alpha = false, bool mipmaps = true) override;
      void DeleteTexture(int textureID) override;
      void CopyFrameBufferToTexture(int textureID, int width, int height) override;
      void BindTexture(int textureID) override;
      void SetTextureUnit(int textureUnit) override;
      void SetClientTextureUnit(int textureUnit) override;

      // frame buffers
      int CreateFrameBuffer() override;
      void DeleteFrameBuffer(int fbID) override;
      void BindFrameBuffer(int fbID) override;
      void SetFrameBufferRenderBuffer(e_TargetAttachment targetAttachment, int rbID) override;
      void SetFrameBufferTexture2D(e_TargetAttachment targetAttachment, int texID) override;
      bool CheckFrameBufferStatus() override;
      void SetFramebufferGammaCorrection(bool onOff) override;

      // render targets
      void SetRenderTargets(std::vector<e_TargetAttachment> targetAttachments) override;

      // utility
      void SetFOV(float angle) override;
      void PushAttribute(int attr) override;
      void PopAttribute() override;
      void SetViewport(int x, int y, int width, int height) override;
      void GetContextSize(int &width, int &height, int &bpp) override;

      // shaders
      void LoadShader(const std::string &name, const std::string &filename) override;
      void UseShader(const std::string &name) override;
      void SetUniformInt(const std::string &shaderName, const std::string &varName, int value) override;
      // 非 Renderer3D 接口扩展，非 override
      virtual void SetUniformInt3(const std::string &shaderName, const std::string &varName, int value1, int value2, int value3);
      void SetUniformFloat(const std::string &shaderName, const std::string &varName, float value) override;
      void SetUniformFloat2(const std::string &shaderName, const std::string &varName, float value1, float value2) override;
      void SetUniformFloat3(const std::string &shaderName, const std::string &varName, float value1, float value2, float value3) override;
      void SetUniformFloat3Array(const std::string &shaderName, const std::string &varName, int count, float *values) override;
      void SetUniformMatrix4(const std::string &shaderName, const std::string &varName, const Matrix4 &mat) override;

    protected:
      SDL_GLContext context = 0;
      SDL_Window* window = nullptr;
#ifdef __linux__
      EGLDisplay egl_display = nullptr;
      EGLSurface egl_surface;
      EGLContext egl_context;
#endif
      int context_width, context_height, context_bpp;

      float cameraNear = 0.0f;
      float cameraFar = 0.0f;

      int noiseTexID = 0;

      float FOV = 0.0f;

      float overallBrightness = 0.0f;

      float largest_supported_anisotropy = 0.0f;
      void SetMaxAnisotropy();

      std::map<std::string, int> uniformCache;

      std::map<int, int> VBOPingPongMap;
      std::map<int, int> VAOPingPongMap;
      std::map<int, int> VAOReadIndex;

      signed int _cache_activeTextureUnit = 0;
      screenshoot last_screen_;
      // members and functions for rendering overlay with shaders instead of deprecated methods
      VertexBufferID overlayBuffer;  // buffer for drawing textures such as player's names and game score
      VertexBufferID quadBuffer;     // buffer for drawing simple quads
      VertexBufferID CreateSimpleVertexBuffer(float *vertices, unsigned int size);
      void DeleteSimpleVertexBuffer(VertexBufferID vertexBufferID);
      void InitializeOverlayAndQuadBuffers();
      void CreateContextSdl();
#ifdef __linux__
      void CreateContextEgl();
#endif
  };
}

#endif
