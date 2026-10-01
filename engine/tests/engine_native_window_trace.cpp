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
#include "onthepitch/player/controller/humancontroller.hpp"
#include "onthepitch/player/player.hpp"
#include "onthepitch/team.hpp"
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
// Observe whether the UI owner misses polls or SDL blocks it while GL presents.
// Only slow/gapped polls and keyboard events are logged to limit observer cost.
extern "C" int SDL_PollEvent(SDL_Event* event) {
  static const auto next = Next<int(*)(SDL_Event*)>("SDL_PollEvent");
  static thread_local long long previous_end = 0;
  const auto start = Now();
  const int result = next(event);
  const auto end = Now();
  const auto gap = previous_end ? start - previous_end : 0;
  previous_end = end;
  const bool keyboard = result && event &&
      (event->type == SDL_KEYDOWN || event->type == SDL_KEYUP);
  if (gap > 10000000 || end - start > 2000000 || keyboard) {
    const unsigned event_type = result && event ? event->type : 0;
    const int key = keyboard ? event->key.keysym.scancode : -1;
    std::fprintf(Log(),
        "{\"kind\":\"sdl_poll\",\"start\":%lld,\"end\":%lld,"
        "\"gap_ns\":%lld,\"duration_ns\":%lld,\"event_type\":%u,"
        "\"scancode\":%d}\n",
        start, end, gap, end - start, event_type, key);
    std::fflush(Log());
  }
  return result;
}
extern "C" void SDL_GL_SwapWindow(SDL_Window* window) {
  static const auto next = Next<void(*)(SDL_Window*)>("SDL_GL_SwapWindow");
  ++swaps;
  if (swaps == 1) {
    std::fprintf(Log(), "{\"kind\":\"swap_interval\",\"time\":%lld,\"value\":%d}\n",
                 Now(), SDL_GL_GetSwapInterval());
    std::fflush(Log());
  }
  SDL_SysWMinfo info{};
  SDL_VERSION(&info.version);
  const auto xid = SDL_GetWindowWMInfo(window, &info) && info.subsystem == SDL_SYSWM_X11
      ? static_cast<unsigned long>(info.info.x11.window) : 0;
  const auto picture_start = Now();
  Picture(window);
  const auto before_swap = Now();
  std::fprintf(Log(), "{\"kind\":\"swap\",\"time\":%lld,\"index\":%llu,\"xid\":%lu,\"render_owner\":%s}\n", before_swap, swaps, xid, rendering ? "true" : "false");
  std::fflush(Log());
  next(window);
  const auto after_swap = Now();
  std::fprintf(Log(), "{\"kind\":\"swap_timing\",\"index\":%llu,\"start\":%lld,\"end\":%lld,\"picture_ns\":%lld,\"swap_ns\":%lld}\n",
               swaps, before_swap, after_swap, before_swap - picture_start,
               after_swap - before_swap);
  std::fflush(Log());
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
  std::fprintf(Log(), "{\"kind\":\"step_timing\",\"index\":%llu,\"start\":%lld,\"end\":%lld,\"step_ns\":%lld,\"sim_step\":%d,\"in_play\":%s,\"game_mode\":%d,\"vx\":%.9g,\"vy\":%.9g}\n",steps+1,step_start,step_end,step_end-step_start,info.step,info.is_in_play?"true":"false",static_cast<int>(info.game_mode),vx,vy);
  int controllable = 0;
  for (const auto& entry : env->scenario_config.left_team) controllable += entry.controllable;
  std::fprintf(Log(), "{\"kind\":\"step\",\"time\":%lld,\"index\":%llu,\"x\":%.9g,\"y\":%.9g,"
                      "\"buttons\":%u,\"owned\":%d,\"player_x\":%.9g,\"player_y\":%.9g,"
                      "\"ball_x\":%.9g,\"ball_y\":%.9g,\"ball_z\":%.9g,"
                      "\"ball_vx\":%.9g,\"ball_vy\":%.9g,\"ball_vz\":%.9g,"
                      "\"ball_owned_team\":%d,\"ball_owned_player\":%d,"
                      "\"controllable\":%d,\"state\":%d,\"slots\":%zu}\n",
               Now(), ++steps, input.dir_x, input.dir_y, input.buttons, owned, x, y,
               info.ball_position[0], info.ball_position[1],
               info.ball_position[2], info.ball_direction[0],
               info.ball_direction[1], info.ball_direction[2],
               info.ball_owned_team, info.ball_owned_player,
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

extern "C" void ObserveHumanCommand(HumanController*, PlayerCommandQueue&)
    asm("_ZN15HumanController14RequestCommandERSt6vectorI13PlayerCommandSaIS1_EE");
extern "C" void ObserveHumanCommand(HumanController* controller,
                                    PlayerCommandQueue& commands) {
  static const auto next = Next<void(*)(HumanController*, PlayerCommandQueue&)>(
      "_ZN15HumanController14RequestCommandERSt6vectorI13PlayerCommandSaIS1_EE");
  if (!std::getenv("FOOTBALL_FEEL_COMMAND_TRACE")) {
    next(controller, commands);
    return;
  }
  const Vector3 hid = controller->GetHIDevice()->GetDirection();
  const auto before = commands.size();
  next(controller, commands);
  auto* player = controller->CastPlayer();
  int team_index = 0;
  bool found_player = false;
  for (auto* teammate : player->GetTeam()->GetAllPlayers()) {
    if (teammate == player) {
      found_player = true;
      break;
    }
    if (teammate->CastHumanoid()) ++team_index;
  }
  if (!found_player) team_index = -1;
  const PlayerCommand* movement = nullptr;
  for (size_t i = before; i < commands.size(); ++i)
    if (commands[i].desiredFunctionType == e_FunctionType_Movement)
      movement = &commands[i];
  const auto position = player->GetPosition();
  const auto actual = player->GetMovement();
  const auto controller_direction = controller->GetDirection();
  const auto* active_anim = player->CastHumanoid()->GetCurrentAnim();
  std::fprintf(Log(),
      "{\"kind\":\"human_command\",\"time\":%lld,\"player\":\"%p\",\"team_id\":%d,\"team_index\":%d,\"player_x\":%.9g,\"player_y\":%.9g,"
      "\"hid_x\":%.9g,\"hid_y\":%.9g,\"actual_vx\":%.9g,\"actual_vy\":%.9g,"
      "\"movement\":%s,\"desired_x\":%.9g,\"desired_y\":%.9g,\"desired_speed\":%.9g,"
      "\"anim_type\":%d,\"anim_frame\":%d,\"anim_touch\":%d,"
      "\"steer_x\":%.9g,\"steer_y\":%.9g,\"steer_vx\":%.9g,\"steer_vy\":%.9g,"
      "\"origin_x\":%.9g,\"origin_y\":%.9g,\"origin_speed\":%.9g,"
      "\"controller_x\":%.9g,\"controller_y\":%.9g,\"controller_speed\":%.9g,"
      "\"has_possession\":%s,\"ball_retainer\":%s}\n",
      Now(), static_cast<const void*>(player), player->GetTeam()->GetID(),
      team_index, position.coords[0], position.coords[1],
      hid.coords[0], hid.coords[1],
      actual.coords[0], actual.coords[1], movement ? "true" : "false",
      movement ? movement->desiredDirection.coords[0] : 0,
      movement ? movement->desiredDirection.coords[1] : 0,
      movement ? movement->desiredVelocityFloat : 0,
      static_cast<int>(active_anim->functionType), active_anim->frameNum,
      active_anim->touchFrame, active_anim->movementSmuggleOffset.coords[0],
      active_anim->movementSmuggleOffset.coords[1],
      active_anim->movementSmuggle.coords[0],
      active_anim->movementSmuggle.coords[1],
      active_anim->originatingCommand.desiredDirection.coords[0],
      active_anim->originatingCommand.desiredDirection.coords[1],
      active_anim->originatingCommand.desiredVelocityFloat,
      controller_direction.coords[0], controller_direction.coords[1],
      controller->GetFloatVelocity(),
      player->HasPossession() ? "true" : "false",
      controller->GetMatch()->GetBallRetainer() == player ? "true" : "false");
}

extern "C" bool ObserveAnimSelection(Humanoid*, const PlayerCommand&,
                                      e_InterruptAnim, bool)
    asm("_ZN8Humanoid10SelectAnimERK13PlayerCommand15e_InterruptAnimb");
extern "C" bool ObserveAnimSelection(Humanoid* humanoid,
                                      const PlayerCommand& command,
                                      e_InterruptAnim interrupt, bool prefer_pass) {
  static const auto next = Next<bool(*)(Humanoid*, const PlayerCommand&,
                                        e_InterruptAnim, bool)>(
      "_ZN8Humanoid10SelectAnimERK13PlayerCommand15e_InterruptAnimb");
  if (!std::getenv("FOOTBALL_FEEL_COMMAND_TRACE"))
    return next(humanoid, command, interrupt, prefer_pass);
  const int before = humanoid->GetCurrentFrame();
  const int type_before = static_cast<int>(
      humanoid->CastPlayer()->GetCurrentFunctionType());
  const bool touch_pending_before = humanoid->TouchPending();
  const int touch_frame_before = humanoid->GetTouchFrame();
  const auto position = humanoid->CastPlayer()->GetPosition();
  const bool selected = next(humanoid, command, interrupt, prefer_pass);
  std::fprintf(Log(),
      "{\"kind\":\"anim_select\",\"time\":%lld,\"player\":\"%p\",\"player_x\":%.9g,\"player_y\":%.9g,"
      "\"interrupt\":%d,\"current_type\":%d,\"has_possession\":%s,"
      "\"touch_pending\":%s,\"touch_frame\":%d,"
      "\"command_type\":%d,\"desired_x\":%.9g,"
      "\"desired_speed\":%.9g,\"accepted\":%s,\"frame_before\":%d,\"frame_after\":%d,"
      "\"type_before\":%d,\"touch_pending_before\":%s,\"touch_frame_before\":%d}\n",
      Now(), static_cast<const void*>(humanoid->CastPlayer()), position.coords[0],
      position.coords[1], static_cast<int>(interrupt),
      static_cast<int>(humanoid->CastPlayer()->GetCurrentFunctionType()),
      humanoid->CastPlayer()->HasPossession() ? "true" : "false",
      humanoid->TouchPending() ? "true" : "false", humanoid->GetTouchFrame(),
      static_cast<int>(command.desiredFunctionType), command.desiredDirection.coords[0],
      command.desiredVelocityFloat, selected ? "true" : "false", before,
      humanoid->GetCurrentFrame(), type_before,
      touch_pending_before ? "true" : "false", touch_frame_before);
  return selected;
}

// Observe committed contact separately from animation selection. The game
// records the last-touch player after it updates ball physics.
extern "C" void ObserveLastTouch(Team*, Player*, e_TouchType)
    asm("_ZN4Team18SetLastTouchPlayerEP6Player11e_TouchType");
extern "C" void ObserveLastTouch(Team* team, Player* player, e_TouchType type) {
  static const auto next = Next<void(*)(Team*, Player*, e_TouchType)>(
      "_ZN4Team18SetLastTouchPlayerEP6Player11e_TouchType");
  next(team, player, type);
  if (!std::getenv("FOOTBALL_FEEL_COMMAND_TRACE")) return;
  std::fprintf(Log(),
      "{\"kind\":\"ball_touch\",\"time\":%lld,\"player\":\"%p\","
      "\"team_id\":%d,\"touch_type\":%d}\n",
      Now(), static_cast<const void*>(player), team->GetID(),
      static_cast<int>(type));
}
