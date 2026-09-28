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
      GLuint(view.postToneTextureID), GLuint(view.postExposureTextureID[0]),
      GLuint(view.postExposureTextureID[1])};
  const GLuint framebuffers[] = {
      GLuint(view.postBloomFrameBufferID[0]),
      GLuint(view.postBloomFrameBufferID[1]),
      GLuint(view.postToneFrameBufferID),
      GLuint(view.postExposureFrameBufferID[0]),
      GLuint(view.postExposureFrameBufferID[1])};
  int beforeTextures[5]{}, beforeFramebuffers[5]{};
  for (int i = 0; i < 5; ++i) {
    beforeTextures[i] = textures[i] ? int(isTexture(textures[i])) : 0;
    beforeFramebuffers[i] =
        framebuffers[i] ? int(isFramebuffer(framebuffers[i])) : 0;
  }
  next(renderer, viewID);
  int afterTextures[5]{}, afterFramebuffers[5]{};
  for (int i = 0; i < 5; ++i) {
    afterTextures[i] = textures[i] ? int(isTexture(textures[i])) : 0;
    afterFramebuffers[i] =
        framebuffers[i] ? int(isFramebuffer(framebuffers[i])) : 0;
  }
  const char *path = std::getenv("FOOTBALL_POSTPROCESS_LIFETIME_TRACE");
  if (!path) std::abort();
  FILE *out = std::fopen(path, "a");
  if (!out) std::abort();
  std::fprintf(out, "{\"view\":%d", viewID);
  auto printIDs = [&](const char *name, const GLuint *values) {
    std::fprintf(out, ",\"%s\":[", name);
    for (int i = 0; i < 5; ++i)
      std::fprintf(out, "%s%u", i ? "," : "", values[i]);
    std::fputc(']', out);
  };
  auto printStates = [&](const char *name, const int *values) {
    std::fprintf(out, ",\"%s\":[", name);
    for (int i = 0; i < 5; ++i)
      std::fprintf(out, "%s%d", i ? "," : "", values[i]);
    std::fputc(']', out);
  };
  printIDs("textures", textures);
  printIDs("framebuffers", framebuffers);
  printStates("before_textures", beforeTextures);
  printStates("after_textures", afterTextures);
  printStates("before_framebuffers", beforeFramebuffers);
  printStates("after_framebuffers", afterFramebuffers);
  std::fputs("}\n", out);
  if (std::fclose(out)) std::abort();
}
