// 2026-09-13: real GameEnv capture, odd RGB packing and presentation-only state.
#include "frame_sync/input_codec.hpp"
#include "frame_sync/native_match_scenario.hpp"
#include "game_env.hpp"
#include "systems/graphics/graphics_system.hpp"
#include "systems/graphics/rendering/interface_renderer3d.hpp"

#include <EGL/egl.h>
#include <SDL_opengl.h>
#include <array>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
constexpr int kWidth = 321;
constexpr int kHeight = 181;
constexpr size_t kBytes = kWidth * kHeight * 3;
unsigned assertions = 0;
unsigned images = 0;
unsigned uncaptured = 0;
unsigned rejected = 0;
unsigned in_play = 0;

void require(bool value, const char* message) {
  ++assertions;
  if (!value) throw std::runtime_error(message);
}

template <class Function>
void rejects(Function function) {
  bool caught = false;
  try { function(); } catch (const std::logic_error&) { caught = true; }
  require(caught, "Unavailable capture returned stale or empty pixels");
  ++rejected;
}

void write(const std::filesystem::path& path, const std::string& data) {
  require(!std::filesystem::exists(path), "Evidence already exists");
  std::ofstream stream(path, std::ios::binary);
  stream.write(data.data(), static_cast<std::streamsize>(data.size()));
  stream.close();
  require(stream.good(), "Could not write evidence");
}

std::string raw_pixels(GameEnv& env) {
  ContextHolder selected(&env);
  // 2026-09-13: legacy SDL OpenGL headers omit this core function typedef.
  // const auto read = reinterpret_cast<PFNGLREADPIXELSPROC>(
  using ReadPixels = void (*)(GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, void*);
  const auto read = reinterpret_cast<ReadPixels>(
      eglGetProcAddress("glReadPixels"));
  const auto bind = reinterpret_cast<PFNGLBINDFRAMEBUFFERPROC>(
      eglGetProcAddress("glBindFramebuffer"));
  require(read && bind, "Actual GL readback functions missing");
  GLint previous_buffer = 0, previous_pack = 0;
  glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &previous_buffer);
  glGetIntegerv(GL_PACK_ALIGNMENT, &previous_pack);
  bind(GL_READ_FRAMEBUFFER, 0);
  glPixelStorei(GL_PACK_ALIGNMENT, 1);
  std::string pixels(kBytes, '\0');
  read(0, 0, kWidth, kHeight, GL_RGB, GL_UNSIGNED_BYTE, pixels.data());
  glPixelStorei(GL_PACK_ALIGNMENT, previous_pack);
  bind(GL_READ_FRAMEBUFFER, previous_buffer);
  require(glGetError() == GL_NO_ERROR, "Independent GL image read failed");
  return pixels;
}

void render(GameEnv& env) {
  const auto before = env.get_state_digest();
  {
    ContextHolder selected(&env);
    glPixelStorei(GL_PACK_ALIGNMENT, 8);
    env.render();
    glFinish();
    GLint alignment = 0;
    glGetIntegerv(GL_PACK_ALIGNMENT, &alignment);
    require(alignment == 8, "Render changed caller RGB packing");
    require(glGetError() == GL_NO_ERROR, "Actual engine render produced GL error");
  }
  require(env.get_state_digest() == before, "Capture policy changed simulation");
}

void exercise(const std::filesystem::path& output) {
  require(std::getenv("DISPLAY") == nullptr,
          "Use an actual EGL offscreen context for the independent back-buffer oracle");
  GameEnv env;
  require(env.game_config.capture_frames, "Default RGB API changed");
  env.game_config.render = true;
  env.game_config.render_resolution_x = kWidth;
  env.game_config.render_resolution_y = kHeight;
  env.game_config.physics_steps_per_frame = 2;
  auto scenario = frame_sync::MakeNativeMatchScenario(
      frame_sync::NativeMatchContract(42, 1, 0));
  env.start_game(*scenario);
  env.state = game_running;
  {
    ContextHolder selected(&env);
    const auto* renderer = glGetString(GL_RENDERER);
    require(renderer != nullptr, "Actual OpenGL renderer missing");
    std::ofstream identity(output / "identity.json");
    identity << "{\"renderer\":"
             << std::quoted(reinterpret_cast<const char*>(renderer))
             << ",\"width\":" << kWidth << ",\"height\":" << kHeight << "}\n";
    identity.close();
    require(identity.good(), "GL identity write failed");
    // Legacy initialization may leave GL errors; each measured render must not.
    for (unsigned i = 0; glGetError() != GL_NO_ERROR; ++i)
      require(i < 32, "Initialization GL error did not clear");
  }
  std::ifstream maps("/proc/self/maps");
  std::ofstream loaded(output / "loaded-maps.txt");
  loaded << maps.rdbuf();
  loaded.close();
  require(loaded.good(), "Loaded-library evidence failed");

  const frame_sync::SlotInput input{};
  for (unsigned frame = 0; frame <= 160; ++frame) {
    env.StepWithInput(&input, sizeof(input));
    in_play += env.get_info().is_in_play;
    if (frame % 40 != 0) continue;
    render(env);
    const auto cached = env.get_frame();
    require(cached.size() == kBytes, "Odd-width RGB size differs");
    require(cached == raw_pixels(env), "Default cache differs from real back buffer");
    require(cached == env.get_frame(), "Repeated get_frame changed pixels");
    size_t varied = 0;
    for (size_t i = 3; i < cached.size(); i += 3)
      varied += cached.compare(i, 3, cached, 0, 3) != 0;
    require(varied > 100, "Actual game image is blank");
    const auto state = env.get_state_digest();
    const auto snapshot = env.get_state("capture-contract");
    write(output / ("frame-" + std::to_string(frame) + ".rgb"), cached);
    write(output / ("frame-" + std::to_string(frame) + ".state"), state);
    ++images;

    env.game_config.capture_frames = false;
    rejects([&] { env.get_frame(); });
    require(env.get_state("capture-contract") == snapshot,
            "Capture policy leaked into serialized game state");
    render(env);
    ++uncaptured;
    rejects([&] { env.get_frame(); });
    require(raw_pixels(env) == cached, "Capture opt-out changed displayed pixels");
    require(env.set_state(snapshot) == "capture-contract", "Snapshot restore failed");
    require(!env.game_config.capture_frames, "Restore overwrote presentation policy");
    require(env.get_state_digest() == state, "Restore changed captured logical state");
    env.game_config.capture_frames = true;
    rejects([&] { env.get_frame(); });
    render(env);
    require(env.get_frame() == cached, "Re-enabled capture returned a stale image");
  }
  require(in_play > 0, "Capture contract never reached actual play");

  // Known framebuffer colours detect previous-frame capture independently of
  // engine scene complexity. Exercise the actual renderer's swap path.
  {
    ContextHolder selected(&env);
    auto* renderer = GetGraphicsSystem()->GetRenderer3D();
    const auto bind = reinterpret_cast<PFNGLBINDFRAMEBUFFERPROC>(
        eglGetProcAddress("glBindFramebuffer"));
    require(renderer && bind, "Actual renderer is unavailable");
    bind(GL_FRAMEBUFFER, 0);
    glDisable(GL_SCISSOR_TEST);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    const auto state = env.get_state_digest();
    for (unsigned channel = 0; channel < 3; ++channel) {
      glClearColor(channel == 0, channel == 1, channel == 2, 1.f);
      glClear(GL_COLOR_BUFFER_BIT);
      renderer->SwapBuffers();
      const auto pixels = env.get_frame();
      require(pixels.size() == kBytes, "Solid RGB frame has incorrect size");
      bool correct = true;
      for (size_t i = 0; i < pixels.size(); ++i)
        correct &= static_cast<unsigned char>(pixels[i]) == (i % 3 == channel ? 255 : 0);
      require(correct, "Captured RGB belongs to a previous frame or padded row");
      require(glGetError() == GL_NO_ERROR, "Solid frame capture produced GL error");
    }
    require(env.get_state_digest() == state, "Presenting colours altered simulation");
  }
}
}  // namespace

int main(int argc, char** argv) {
  try {
    require(argc == 2, "A new evidence directory is required");
    const std::filesystem::path output(argv[1]);
    require(std::filesystem::create_directory(output), "Evidence directory already exists");
    exercise(output);
    // 2026-09-13: API opt-out is enforced even when the renderer is headless.
    {
      GameEnv headless;
      require(headless.game_config.capture_frames, "Headless default capture changed");
      headless.start_game();
      headless.state = game_running;
      require(headless.get_frame().empty(), "Headless default RGB behavior changed");
      const auto state = headless.get_state_digest();
      headless.game_config.capture_frames = false;
      rejects([&] { headless.get_frame(); });
      require(headless.get_state_digest() == state, "Headless capture rejection changed state");
      headless.game_config.capture_frames = true;
      require(headless.get_frame().empty(), "Headless capture opt-in changed renderer");
    }
    std::cout << "{\"passed\":true,\"skipped\":0,\"assertions\":" << assertions
              << ",\"actual_gameenv\":true,\"engine_frames\":161,\"images\":" << images
              << ",\"uncaptured_renders\":" << uncaptured << ",\"rejections\":" << rejected
              << ",\"headless_policy\":true,\"solid_colours\":3,\"odd_width\":321,\"in_play_frames\":" << in_play
              << ",\"product_acceptance\":false}\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
