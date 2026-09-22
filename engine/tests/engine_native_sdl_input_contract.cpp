// 2026-09-13: isolated X11/XTEST and SDL virtual-controller preflight.
// Exercises the current native sampler; not GameEnv or player response latency.
#include "frame_sync/python_window_input.hpp"
#include <X11/Xlib.h>
#include <X11/extensions/XTest.h>
#include <SDL.h>
#include <SDL_syswm.h>
#include <algorithm>
#include <chrono>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string_view>

namespace {
int assertions = 0;
void Require(bool value, const char* message) {
  ++assertions;
  if (!value) throw std::runtime_error(message);
}
class SdlSession {
 public:
  SdlSession() { Require(SDL_Init(SDL_INIT_VIDEO) == 0, SDL_GetError()); }
  ~SdlSession() { SDL_Quit(); }
  SdlSession(const SdlSession&) = delete;
  SdlSession& operator=(const SdlSession&) = delete;
  SdlSession(SdlSession&&) = delete;
  SdlSession& operator=(SdlSession&&) = delete;
};
class VirtualPad {
 public:
  VirtualPad() {
    index_ = SDL_JoystickAttachVirtual(SDL_JOYSTICK_TYPE_GAMECONTROLLER, 2, 15, 0);
    Require(index_ >= 0, SDL_GetError());
    joystick_ = SDL_JoystickOpen(index_);
    if (!joystick_) {
      SDL_JoystickDetachVirtual(index_);
      index_ = -1;
      throw std::runtime_error(SDL_GetError());
    }
  }
  ~VirtualPad() { Detach(); }
  VirtualPad(const VirtualPad&) = delete;
  VirtualPad& operator=(const VirtualPad&) = delete;
  VirtualPad(VirtualPad&&) = delete;
  VirtualPad& operator=(VirtualPad&&) = delete;
  SDL_Joystick* get() const { return joystick_; }
  void Detach() noexcept {
    if (joystick_) SDL_JoystickClose(joystick_);
    joystick_ = nullptr;
    if (index_ >= 0) SDL_JoystickDetachVirtual(index_);
    index_ = -1;
  }
 private:
  int index_ = -1;
  SDL_Joystick* joystick_ = nullptr;
};
template<class Predicate> void PumpUntil(const char* label, Predicate predicate) {
  std::cerr << "Waiting for " << label << std::endl;
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
  do {
    SDL_PumpEvents();
    if (predicate()) return;
    SDL_Delay(1);
  } while (std::chrono::steady_clock::now() < deadline);
  std::cerr << "SDL focus pointer=" << SDL_GetKeyboardFocus() << std::endl;
  throw std::runtime_error(std::string("Real SDL state did not arrive: ") + label);
}
// 2026-09-13: a bare Xvfb has no window manager to enact activation requests.
// Keep SDL's request and also set/query actual server focus for this test.
void FocusWindow(Display* display, SDL_Window* window) {
  Require(SDL_SetWindowInputFocus(window) == 0, SDL_GetError());
  SDL_SysWMinfo info{};
  SDL_VERSION(&info.version);
  Require(SDL_GetWindowWMInfo(window, &info) == SDL_TRUE, SDL_GetError());
  Require(info.subsystem == SDL_SYSWM_X11, "Expected the private X11 window");
  ::Window before{}, after{};
  int revert{};
  XGetInputFocus(display, &before, &revert);
  XSetInputFocus(display, info.info.x11.window, RevertToParent, CurrentTime);
  XSync(display, False);
  XGetInputFocus(display, &after, &revert);
  std::cerr << "Focus SDL window=" << SDL_GetWindowID(window)
            << " target XID=" << info.info.x11.window
            << " before=" << before << " after=" << after << std::endl;
  Require(after == info.info.x11.window, "X11 focus transfer was not applied");
}
bool Key(SDL_Scancode scan) {
  int count = 0;
  const Uint8* keys = SDL_GetKeyboardState(&count);
  return keys && static_cast<int>(scan) < count && keys[scan];
}
void Inject(Display* display, const char* name, bool down) {
  const auto symbol = XStringToKeysym(name);
  const auto code = XKeysymToKeycode(display, symbol);
  Require(symbol != NoSymbol && code != 0, "X11 key mapping unavailable");
  Require(XTestFakeKeyEvent(display, code, down, 0) != 0, "XTEST key injection failed");
  XSync(display, False);
}
bool Contains(const std::vector<std::string>& values, std::string_view expected) {
  return std::find(values.begin(), values.end(), expected) != values.end();
}
}  // namespace

int main() {
  try {
    SdlSession session;
    std::unique_ptr<Display, decltype(&XCloseDisplay)> display(XOpenDisplay(nullptr), &XCloseDisplay);
    Require(display != nullptr, "Cannot connect to the private X server");
    int event = 0, error = 0, major = 0, minor = 0;
    Require(XTestQueryExtension(display.get(), &event, &error, &major, &minor), "XTEST unavailable");
    using Window = std::unique_ptr<SDL_Window, decltype(&SDL_DestroyWindow)>;
    Window window(SDL_CreateWindow("Football input preflight", 0, 0, 320, 240, SDL_WINDOW_SHOWN), &SDL_DestroyWindow);
    Require(window != nullptr, SDL_GetError());
    FocusWindow(display.get(), window.get());
    PumpUntil("original window focus", [&] { return SDL_GetKeyboardFocus() == window.get(); });
    frame_sync::PythonWindowInput sampler;
    auto sample = sampler.poll(window.get());
    Require(sample.focused && !sample.quit, "Owned SDL window did not receive focus");
    Require(SDL_NumJoysticks() == 0, "Isolated input test expected no pre-existing controller");
    for (const char* key : {"w", "Shift_L", "v"}) Inject(display.get(), key, true);
    PumpUntil("held keyboard keys", [] { return Key(SDL_SCANCODE_W) && Key(SDL_SCANCODE_LSHIFT) && Key(SDL_SCANCODE_V); });
    sample = sampler.poll(window.get());
    for (std::string_view key : {"w", "lshift", "v"}) {
      Require(Contains(sample.keys, key), "Simultaneous held key missing");
      Require(Contains(sample.pressed_keys, key), "Real key-down edge missing");
    }
    sample = sampler.poll(window.get());
    Require(sample.pressed_keys.empty(), "Held keys repeated their press edges");
    for (const char* key : {"w", "Shift_L", "v"}) Inject(display.get(), key, false);
    PumpUntil("released keyboard keys", [] { return !Key(SDL_SCANCODE_W) && !Key(SDL_SCANCODE_LSHIFT) && !Key(SDL_SCANCODE_V); });
    sample = sampler.poll(window.get());
    Require(sample.keys.empty() && sample.pressed_keys.empty(), "Released SDL keyboard state retained");
    Inject(display.get(), "v", true);
    Inject(display.get(), "v", false);
    SDL_Delay(2);
    sample = sampler.poll(window.get());
    Require(!Contains(sample.keys, "v") && Contains(sample.pressed_keys, "v"),
            "Short XTEST press/release was lost before native sampling");
    Require(sampler.poll(window.get()).pressed_keys.empty(), "Short press was duplicated");
    VirtualPad pad;
    sample = sampler.poll(window.get());
    Require(sample.connected, "SDL virtual game controller was not recognized");
    Require(SDL_JoystickSetVirtualAxis(pad.get(), 0, 16384) == 0, SDL_GetError());
    Require(SDL_JoystickSetVirtualAxis(pad.get(), 1, -32768) == 0, SDL_GetError());
    Require(SDL_JoystickSetVirtualButton(pad.get(), 0, 1) == 0, SDL_GetError());
    SDL_JoystickUpdate();
    sample = sampler.poll(window.get());
    Require(sample.connected && sample.axes[0] > .49f && sample.axes[0] < .51f && sample.axes[1] == 1.f,
            "Virtual stick normalization or Y inversion is wrong");
    Require((sample.buttons & 1) && (sample.pressed_buttons & 1), "Virtual pad held/press event missing");
    sample = sampler.poll(window.get());
    Require((sample.buttons & 1) && sample.pressed_buttons == 0, "Virtual pad edge was repeated");
    Window other(SDL_CreateWindow("Focus transfer", 350, 0, 120, 120, SDL_WINDOW_SHOWN), &SDL_DestroyWindow);
    Require(other != nullptr, SDL_GetError());
    FocusWindow(display.get(), other.get());
    PumpUntil("second window focus", [&] { return SDL_GetKeyboardFocus() == other.get(); });
    sample = sampler.poll(window.get());
    Require(!sample.focused && sample.keys.empty() && sample.pressed_keys.empty() &&
            sample.buttons == 0 && sample.pressed_buttons == 0 && sample.axes == std::array<float, 2>{},
            "Focus loss exposed held gameplay input");
    FocusWindow(display.get(), window.get());
    PumpUntil("original window focus", [&] { return SDL_GetKeyboardFocus() == window.get(); });
    Require(sampler.poll(window.get()).focused, "Original window did not recover focus");
    pad.Detach();
    sample = sampler.poll(window.get());
    Require(!sample.connected && sample.buttons == 0 && sample.pressed_buttons == 0 &&
            sample.axes == std::array<float, 2>{}, "Detached controller retained input");
    sampler.close();
    sampler.close();
    std::cout << "{\"passed\":true,\"assertions\":" << assertions
              << ",\"skipped\":0,\"actual_x11_keyboard\":true,\"actual_sdl_virtual_controller\":true,"
                 "\"actual_focus_transfer\":true,\"native_gameenv_exercised\":false}" << std::endl;
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << std::endl;
    return 1;
  }
}
