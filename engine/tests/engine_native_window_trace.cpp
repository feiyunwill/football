// 2026-09-13: independent in-play timing observer; product input and state unchanged.
// 2026-09-13: observe actual product calls, SDL presents and framebuffer images.
// No input, logical state, pose or frame scheduling is injected by this library.
// 2026-09-13: use SDL's installed OpenGL declarations; no external GLEW dependency.
// #include <GL/glew.h>
#include <SDL_opengl.h>
#include "game_env.hpp"
#include "main.hpp"
#include "frame_sync/protocol.hpp"
#include "frame_sync/input_codec.hpp"
#include <SDL.h>
#include <SDL_syswm.h>
#include <dlfcn.h>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <string>
#include <vector>

namespace {
unsigned long long swaps = 0, renders = 0, steps = 0;
// 2026-09-13: identify the loading-screen swap separately from actual match rendering.
bool rendering = false;
long long Now() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
}
FILE* Log() {
  static FILE* file = [] {
    const char* directory = std::getenv("FOOTBALL_NATIVE_TRACE");
    if (!directory) std::abort();
    auto path = std::filesystem::path(directory) / "events.jsonl";
    auto* stream = std::fopen(path.c_str(), "wx");
    if (!stream) std::abort();
    return stream;
  }();
  return file;
}
template<class Function> Function Next(const char* name) {
  auto value = dlsym(RTLD_NEXT, name);
  if (!value) std::abort();
  return reinterpret_cast<Function>(value);
}
void Picture(SDL_Window* window) {
  if (swaps > 6 && swaps != 12 && swaps != 24 && swaps != 40) return;
  int width, height;
  SDL_GL_GetDrawableSize(window, &width, &height);
  if (width <= 0 || height <= 0 || width > 4096 || height > 4096) std::abort();
  const auto get_integer = reinterpret_cast<void(*)(GLenum,GLint*)>(SDL_GL_GetProcAddress("glGetIntegerv"));
  const auto pixel_store = reinterpret_cast<void(*)(GLenum,GLint)>(SDL_GL_GetProcAddress("glPixelStorei"));
  const auto read_buffer_fn = reinterpret_cast<void(*)(GLenum)>(SDL_GL_GetProcAddress("glReadBuffer"));
  const auto read_pixels = reinterpret_cast<void(*)(GLint,GLint,GLsizei,GLsizei,GLenum,GLenum,void*)>(
      SDL_GL_GetProcAddress("glReadPixels"));
  if (!get_integer || !pixel_store || !read_buffer_fn || !read_pixels) std::abort();
  GLint alignment, read_buffer;
  get_integer(GL_PACK_ALIGNMENT, &alignment);
  get_integer(GL_READ_BUFFER, &read_buffer);
  pixel_store(GL_PACK_ALIGNMENT, 1);
  read_buffer_fn(GL_BACK);
  std::vector<unsigned char> pixels(static_cast<size_t>(width) * height * 3);
  read_pixels(0, 0, width, height, GL_RGB, GL_UNSIGNED_BYTE, pixels.data());
  read_buffer_fn(read_buffer);
  pixel_store(GL_PACK_ALIGNMENT, alignment);
  const auto path = std::filesystem::path(std::getenv("FOOTBALL_NATIVE_TRACE")) /
                    ("frame-" + std::to_string(swaps) + ".ppm");
  auto* file = std::fopen(path.c_str(), "wx");
  if (!file) std::abort();
  std::fprintf(file, "P6\n%d %d\n255\n", width, height);
  for (int y = height - 1; y >= 0; --y)
    if (std::fwrite(pixels.data() + static_cast<size_t>(y) * width * 3, width * 3, 1, file) != 1) std::abort();
  if (std::fclose(file) != 0) std::abort();
}
}
extern "C" void SDL_GL_SwapWindow(SDL_Window* window) {
  static const auto next = Next<void(*)(SDL_Window*)>("SDL_GL_SwapWindow");
  ++swaps;
  SDL_SysWMinfo info{};
  SDL_VERSION(&info.version);
  const auto xid = SDL_GetWindowWMInfo(window, &info) && info.subsystem == SDL_SYSWM_X11
      ? static_cast<unsigned long>(info.info.x11.window) : 0;
  Picture(window);
  std::fprintf(Log(), "{\"kind\":\"swap\",\"time\":%lld,\"index\":%llu,\"xid\":%lu,\"render_owner\":%s}\n", Now(), swaps, xid, rendering ? "true" : "false");
  std::fflush(Log());
  next(window);
}
extern "C" void ObserveRender(GameEnv*, float, bool) asm("_ZN7GameEnv19render_interpolatedEfb");
extern "C" void ObserveRender(GameEnv* env, float alpha, bool swap) {
  static const auto next = Next<void(*)(GameEnv*,float,bool)>("_ZN7GameEnv19render_interpolatedEfb");
  const auto observe_start = Now();
  const auto before = env->get_state_digest();
  const auto count = swaps;
  // 2026-09-13: observe render ownership without changing the call or framebuffer.
  // next(env, alpha, swap);
  if (rendering) std::abort();
  rendering = true;
  const auto render_start = Now();
  next(env, alpha, swap);
  const auto render_end = Now();
  rendering = false;
  const bool stable = before == env->get_state_digest();
  std::fprintf(Log(), "{\"kind\":\"render_timing\",\"start\":%lld,\"end\":%lld,\"render_ns\":%lld,\"observer_ns\":%lld}\n", render_start,render_end,render_end-render_start,Now()-observe_start-(render_end-render_start));
  std::fprintf(Log(), "{\"kind\":\"render\",\"time\":%lld,\"index\":%llu,\"alpha\":%.9g,"
                      "\"swap_requested\":%s,\"present_delta\":%llu,\"state_stable\":%s}\n",
               Now(), ++renders, alpha, swap ? "true" : "false", swaps-count, stable ? "true" : "false");
  std::fflush(Log());
}
extern "C" void ObserveStep(GameEnv*, const void*, size_t) asm("_ZN7GameEnv13StepWithInputEPKvm");
extern "C" void ObserveStep(GameEnv* env, const void* bytes, size_t size) {
  static const auto next = Next<void(*)(GameEnv*,const void*,size_t)>("_ZN7GameEnv13StepWithInputEPKvm");
  if (!bytes || size == 0 || size > 22 * sizeof(frame_sync::SlotInput) ||
      size % sizeof(frame_sync::SlotInput)) std::abort();
  frame_sync::SlotInput input;
  std::memcpy(&input, bytes, sizeof(input));
  const auto step_start = Now();
  next(env, bytes, size);
  const auto step_end = Now();
  const auto info = env->get_info();
  const int owned = info.left_controllers.empty() ? -1 : info.left_controllers[0].controlled_player;
  double x = 0, y = 0;
  if (owned >= 0 && owned < int(info.left_team.size())) {
    x = info.left_team[owned].player_position[0]; y = info.left_team[owned].player_position[1];
  }
  const double vx = owned >= 0 && owned < int(info.left_team.size()) ? info.left_team[owned].player_direction[0] : 0;
  const double vy = owned >= 0 && owned < int(info.left_team.size()) ? info.left_team[owned].player_direction[1] : 0;
  std::fprintf(Log(), "{\"kind\":\"step_timing\",\"index\":%llu,\"start\":%lld,\"end\":%lld,\"step_ns\":%lld,\"sim_step\":%d,\"in_play\":%s,\"vx\":%.9g,\"vy\":%.9g}\n",steps+1,step_start,step_end,step_end-step_start,info.step,info.is_in_play?"true":"false",vx,vy);
  int controllable = 0;
  for (const auto& entry : env->scenario_config.left_team) controllable += entry.controllable;
  std::fprintf(Log(), "{\"kind\":\"step\",\"time\":%lld,\"index\":%llu,\"x\":%.9g,\"y\":%.9g,"
                      "\"buttons\":%u,\"owned\":%d,\"player_x\":%.9g,\"player_y\":%.9g,"
                      "\"controllable\":%d,\"state\":%d,\"slots\":%zu}\n",
               Now(), ++steps, input.dir_x, input.dir_y, input.buttons, owned, x, y,
               controllable, static_cast<int>(env->state), size / sizeof(input));
  std::fflush(Log());
}

extern "C" void ObservePause(GameEnv*) asm("_ZN7GameEnv5pauseEv");
extern "C" void ObservePause(GameEnv* env) {
  static const auto next = Next<void(*)(GameEnv*)>("_ZN7GameEnv5pauseEv");
  next(env);
  std::fprintf(Log(), "{\"kind\":\"pause\",\"time\":%lld}\n", Now()); std::fflush(Log());
}
extern "C" void ObserveResume(GameEnv*) asm("_ZN7GameEnv6resumeEv");
extern "C" void ObserveResume(GameEnv* env) {
  static const auto next = Next<void(*)(GameEnv*)>("_ZN7GameEnv6resumeEv");
  next(env);
  std::fprintf(Log(), "{\"kind\":\"resume\",\"time\":%lld}\n", Now()); std::fflush(Log());
}
