// Observe per-view postprocess ownership during real GameEnv teardown.
#include "systems/graphics/rendering/opengl_renderer3d.hpp"
#include <EGL/egl.h>
#include <SDL_opengl.h>
#include <dlfcn.h>
#include <cstdio>
#include <cstdlib>

namespace {
template <class Function> Function Next(const char *name) {
  auto symbol = dlsym(RTLD_NEXT, name);
  if (!symbol) std::abort();
  return reinterpret_cast<Function>(symbol);
}
template <class Function> Function Proc(const char *name) {
  auto symbol = eglGetProcAddress(name);
  if (!symbol) std::abort();
  return reinterpret_cast<Function>(symbol);
}
}

extern "C" void ProbeDeleteView(void *, int)
    asm("_ZN7blunted16OpenGLRenderer3D10DeleteViewEi");
extern "C" void ProbeDeleteView(void *renderer, int viewID) {
  auto next = Next<void (*)(void *, int)>(
      "_ZN7blunted16OpenGLRenderer3D10DeleteViewEi");
  auto getView = Next<blunted::View &(*)(void *, int)>(
      "_ZN7blunted16OpenGLRenderer3D7GetViewEi");
  auto isTexture = Proc<GLboolean (*)(GLuint)>("glIsTexture");
  auto isFramebuffer = Proc<GLboolean (*)(GLuint)>("glIsFramebuffer");
  const blunted::View view = getView(renderer, viewID);
  const GLuint textures[] = {
      GLuint(view.postBloomTextureID[0]), GLuint(view.postBloomTextureID[1]),
      GLuint(view.postToneTextureID)};
  const GLuint framebuffers[] = {
      GLuint(view.postBloomFrameBufferID[0]),
      GLuint(view.postBloomFrameBufferID[1]),
      GLuint(view.postToneFrameBufferID)};
  int beforeTextures[3]{}, beforeFramebuffers[3]{};
  for (int i = 0; i < 3; ++i) {
    beforeTextures[i] = textures[i] ? int(isTexture(textures[i])) : 0;
    beforeFramebuffers[i] =
        framebuffers[i] ? int(isFramebuffer(framebuffers[i])) : 0;
  }
  next(renderer, viewID);
  int afterTextures[3]{}, afterFramebuffers[3]{};
  for (int i = 0; i < 3; ++i) {
    afterTextures[i] = textures[i] ? int(isTexture(textures[i])) : 0;
    afterFramebuffers[i] =
        framebuffers[i] ? int(isFramebuffer(framebuffers[i])) : 0;
  }
  const char *path = std::getenv("FOOTBALL_POSTPROCESS_LIFETIME_TRACE");
  if (!path) std::abort();
  FILE *out = std::fopen(path, "a");
  if (!out) std::abort();
  std::fprintf(out,
      "{\"view\":%d,\"textures\":[%u,%u,%u],"
      "\"framebuffers\":[%u,%u,%u],"
      "\"before_textures\":[%d,%d,%d],"
      "\"after_textures\":[%d,%d,%d],"
      "\"before_framebuffers\":[%d,%d,%d],"
      "\"after_framebuffers\":[%d,%d,%d]}\n",
      viewID, textures[0], textures[1], textures[2],
      framebuffers[0], framebuffers[1], framebuffers[2],
      beforeTextures[0], beforeTextures[1], beforeTextures[2],
      afterTextures[0], afterTextures[1], afterTextures[2],
      beforeFramebuffers[0], beforeFramebuffers[1], beforeFramebuffers[2],
      afterFramebuffers[0], afterFramebuffers[1], afterFramebuffers[2]);
  if (std::fclose(out)) std::abort();
}
