// 2026-09-10: bounded input from the existing SDL window; no second SDL owner.
#pragma once
#include <SDL.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace frame_sync {
class PythonWindowInput {
 public:
  struct Sample {
    std::vector<std::string> keys, pressed_keys;
    std::array<float, 2> axes{};
    uint16_t buttons = 0, pressed_buttons = 0;
    bool focused = false, connected = false, quit = false;
  };
  PythonWindowInput() = default;
  PythonWindowInput(const PythonWindowInput&) = delete;
  PythonWindowInput& operator=(const PythonWindowInput&) = delete;
  ~PythonWindowInput() { close(); }

  void close() noexcept {
    if (controller_) SDL_GameControllerClose(controller_);
    controller_ = nullptr;
    if (initialized_) SDL_QuitSubSystem(SDL_INIT_GAMECONTROLLER);
    initialized_ = false;
    overflow_ = false;
  }

  Sample poll(SDL_Window* window) {
    if (!window) throw std::runtime_error("Graphical input requires an SDL window");
    if (!initialized_) {
      if (SDL_InitSubSystem(SDL_INIT_GAMECONTROLLER) != 0)
        throw std::runtime_error("Cannot initialize SDL game controller input");
      initialized_ = true;
    }
    if (controller_ && !SDL_GameControllerGetAttached(controller_)) {
      SDL_GameControllerClose(controller_);
      controller_ = nullptr;
    }
    if (!controller_) {
      const int count = std::min(SDL_NumJoysticks(), 16);
      for (int i = 0; i < count && !controller_; ++i)
        if (SDL_IsGameController(i)) controller_ = SDL_GameControllerOpen(i);
    }
    Sample result;
    std::array<bool, bindings_.size()> pressed{};
    const Uint32 window_id = SDL_GetWindowID(window);
    SDL_JoystickID controller_id = controller_
        ? SDL_JoystickInstanceID(SDL_GameControllerGetJoystick(controller_)) : -1;
    SDL_Event event{};
    int consumed = 0;
    for (; consumed < 64 && SDL_PollEvent(&event); ++consumed) {
      if (event.type == SDL_QUIT || (event.type == SDL_WINDOWEVENT &&
          event.window.windowID == window_id && event.window.event == SDL_WINDOWEVENT_CLOSE))
        result.quit = true;
      if (event.type == SDL_WINDOWEVENT && event.window.windowID == window_id &&
          event.window.event == SDL_WINDOWEVENT_FOCUS_LOST) {
        pressed.fill(false);
        result.pressed_buttons = 0;
      }
      if (event.type == SDL_KEYDOWN && event.key.windowID == window_id && !event.key.repeat)
        for (size_t i = 0; i < bindings_.size(); ++i)
          if (event.key.keysym.scancode == bindings_[i].scan) pressed[i] = true;
      if (event.type == SDL_CONTROLLERBUTTONDOWN && event.cbutton.which == controller_id &&
          event.cbutton.button < 15)
        result.pressed_buttons |= uint16_t(1u << event.cbutton.button);
      // SDL transfers ownership of these payloads even when this UI ignores them.
      if (event.type == SDL_DROPFILE || event.type == SDL_DROPTEXT) SDL_free(event.drop.file);
#if SDL_VERSION_ATLEAST(2, 0, 22)
      if (event.type == SDL_TEXTEDITING_EXT) SDL_free(event.editExt.text);
#endif
    }
    // Bound work without replaying old action edges after an event flood.
    const bool discard_edges = overflow_ || consumed == 64;
    overflow_ = consumed == 64;
    result.focused = SDL_GetKeyboardFocus() == window && !overflow_;
    int key_count = 0;
    const Uint8* keys = SDL_GetKeyboardState(&key_count);
    if (result.focused) {
      for (size_t i = 0; i < bindings_.size(); ++i) {
        if (keys && bindings_[i].scan < key_count && keys[bindings_[i].scan])
          result.keys.emplace_back(bindings_[i].name);
        if (!discard_edges && pressed[i]) result.pressed_keys.emplace_back(bindings_[i].name);
      }
    }
    result.connected = controller_ && SDL_GameControllerGetAttached(controller_);
    if (result.focused && result.connected) {
      for (int i = 0; i < 15; ++i)
        if (SDL_GameControllerGetButton(controller_, SDL_GameControllerButton(i)))
          result.buttons |= uint16_t(1u << i);
      auto axis = [this](SDL_GameControllerAxis index) {
        const int value = SDL_GameControllerGetAxis(controller_, index);
        return value / (value < 0 ? 32768.f : 32767.f);
      };
      result.axes = {axis(SDL_CONTROLLER_AXIS_LEFTX), -axis(SDL_CONTROLLER_AXIS_LEFTY)};
    }
    if (!result.focused || !result.connected || discard_edges) result.pressed_buttons = 0;
    return result;
  }

 private:
  struct Binding { SDL_Scancode scan; const char* name; };
  // 2026-09-10: add K pause without remapping save/quit or gameplay buttons.
  // inline static constexpr std::array<Binding, 23> bindings_{{
  inline static constexpr std::array<Binding, 24> bindings_{{
      {SDL_SCANCODE_W, "w"}, {SDL_SCANCODE_A, "a"}, {SDL_SCANCODE_S, "s"}, {SDL_SCANCODE_D, "d"},
      {SDL_SCANCODE_UP, "up"}, {SDL_SCANCODE_LEFT, "left"}, {SDL_SCANCODE_DOWN, "down"}, {SDL_SCANCODE_RIGHT, "right"},
      {SDL_SCANCODE_Z, "z"}, {SDL_SCANCODE_X, "x"}, {SDL_SCANCODE_C, "c"}, {SDL_SCANCODE_V, "v"},
      {SDL_SCANCODE_R, "r"}, {SDL_SCANCODE_B, "b"}, {SDL_SCANCODE_SPACE, "space"}, {SDL_SCANCODE_N, "n"},
      {SDL_SCANCODE_TAB, "tab"}, {SDL_SCANCODE_LSHIFT, "lshift"}, {SDL_SCANCODE_RSHIFT, "rshift"},
      // 2026-09-10: preserve the previous end of the bounded binding table.
      // {SDL_SCANCODE_M, "m"}, {SDL_SCANCODE_P, "p"}, {SDL_SCANCODE_Q, "q"}, {SDL_SCANCODE_ESCAPE, "escape"}}};
      {SDL_SCANCODE_M, "m"}, {SDL_SCANCODE_P, "p"}, {SDL_SCANCODE_Q, "q"}, {SDL_SCANCODE_ESCAPE, "escape"},
      {SDL_SCANCODE_K, "k"}}};
  SDL_GameController* controller_ = nullptr;
  bool initialized_ = false, overflow_ = false;
};
}  // namespace frame_sync
