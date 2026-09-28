// Read-only exposure texture sampling during the actual tone-mapping draw.
#include <EGL/egl.h>
#include <SDL_opengl.h>
#include <dlfcn.h>
#include <cmath>
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
unsigned long long sequence = 0;
void Snapshot() {
  const auto get = Proc<void (*)(GLenum, GLint *)>("glGetIntegerv");
  const auto location = Proc<GLint (*)(GLuint, const GLchar *)>(
      "glGetUniformLocation");
  const auto uniform = Proc<void (*)(GLuint, GLint, GLint *)>("glGetUniformiv");
  const auto active = Proc<void (*)(GLenum)>("glActiveTexture");
  const auto level = Proc<void (*)(GLenum, GLint, GLenum, GLint *)>(
      "glGetTexLevelParameteriv");
  const auto image = Proc<void (*)(GLenum, GLint, GLenum, GLenum, void *)>(
      "glGetTexImage");
  GLint program = 0;
  get(GL_CURRENT_PROGRAM, &program);
  if (!program) return;
  const GLint loc = location(GLuint(program), "useAutoExposure");
  if (loc < 0) return;
  GLint enabled = 0;
  uniform(GLuint(program), loc, &enabled);
  if (!enabled) return;
  GLint priorUnit = 0, fbo = 0, viewport[4]{};
  get(GL_ACTIVE_TEXTURE, &priorUnit);
  get(GL_DRAW_FRAMEBUFFER_BINDING, &fbo);
  get(GL_VIEWPORT, viewport);
  active(GL_TEXTURE3);
  GLint texture = 0, width = 0, height = 0;
  get(GL_TEXTURE_BINDING_2D, &texture);
  if (texture <= 0) std::abort();
  level(GL_TEXTURE_2D, 0, GL_TEXTURE_WIDTH, &width);
  level(GL_TEXTURE_2D, 0, GL_TEXTURE_HEIGHT, &height);
  if (width != 1 || height != 1) std::abort();
  GLfloat values[4]{};
  image(GL_TEXTURE_2D, 0, GL_RGBA, GL_FLOAT, values);
  active(GLenum(priorUnit));
  for (float value : values)
    if (!std::isfinite(value)) std::abort();
  const char *path = std::getenv("FOOTBALL_POSTPROCESS_EXPOSURE_TRACE");
  if (!path) std::abort();
  FILE *out = std::fopen(path, "a");
  if (!out) std::abort();
  std::fprintf(out,
      "{\"sequence\":%llu,\"fbo\":%d,\"texture\":%d,"
      "\"viewport\":[%d,%d,%d,%d],\"exposure\":%.9g,"
      "\"target\":%.9g,\"average_luminance\":%.9g}\n",
      ++sequence, fbo, texture, viewport[0], viewport[1],
      viewport[2], viewport[3], double(values[0]),
      double(values[1]), double(values[2]));
  if (std::fclose(out)) std::abort();
}
}
extern "C" void ProbeFullscreen(void *)
    asm("_ZN7blunted16OpenGLRenderer3D15RenderOverlay2DEv");
extern "C" void ProbeFullscreen(void *renderer) {
  static const auto next = Next<void (*)(void *)>(
      "_ZN7blunted16OpenGLRenderer3D15RenderOverlay2DEv");
  Snapshot();
  next(renderer);
}
