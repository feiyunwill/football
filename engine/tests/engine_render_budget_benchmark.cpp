// Full-resolution GameEnv render timing. Keep simulation outside the measured interval.
#include "frame_sync/input_codec.hpp"
#include "frame_sync/native_match_scenario.hpp"
#include "game_env.hpp"
#include "systems/graphics/graphics_system.hpp"

#include <SDL.h>
#include <SDL_opengl.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr int kWidth = 1920, kHeight = 1080;
constexpr unsigned kWarmup = 30, kSamples = 120;

void Require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

bool Enabled(const char* name) {
  const char* value = std::getenv(name);
  return value && std::string(value) == "1";
}

double Percentile(std::vector<double> values, double fraction) {
  std::sort(values.begin(), values.end());
  return values[static_cast<size_t>(std::ceil(fraction * values.size())) - 1];
}

std::string LoadedGalliumPath() {
  std::ifstream maps("/proc/self/maps");
  std::string line;
  while (std::getline(maps, line)) {
    const auto start = line.find('/');
    if (start != std::string::npos &&
        line.find("/libgallium-", start) != std::string::npos)
      return line.substr(start);
  }
  return {};
}
}  // namespace

int main(int argc, char** argv) {
  try {
    Require(argc == 2 || (argc == 3 && std::string(argv[2]) == "--diagnostic"),
            "Expected one deterministic match seed and optional --diagnostic");
    const bool diagnostic = argc == 3;
    const unsigned long parsed = std::stoul(argv[1]);
    Require(parsed <= UINT32_MAX, "Match seed out of range");
    Require(Enabled("GFOOTBALL_USE_PBR") &&
                (diagnostic || (Enabled("GFOOTBALL_PBR_BLOOM") &&
                Enabled("GFOOTBALL_PBR_FXAA") &&
                Enabled("GFOOTBALL_PBR_AUTO_EXPOSURE"))),
            "1080p quality profile is incomplete");
    std::string quality = "pbr";
    if (Enabled("GFOOTBALL_PBR_BLOOM")) quality += "+bloom";
    if (Enabled("GFOOTBALL_PBR_FXAA")) quality += "+fxaa";
    if (Enabled("GFOOTBALL_PBR_AUTO_EXPOSURE")) quality += "+auto_exposure";
    const bool swap_enabled = !diagnostic || !Enabled("GFOOTBALL_RENDER_SKIP_SWAP");
    GameEnv env;
    env.game_config.render = true;
    env.game_config.capture_frames = false;
    env.game_config.render_resolution_x = kWidth;
    env.game_config.render_resolution_y = kHeight;
    env.game_config.physics_steps_per_frame =
        frame_sync::NativeMatchContract::kPhysicsSteps;
    auto scenario = frame_sync::MakeNativeMatchScenario(
        frame_sync::NativeMatchContract(static_cast<uint32_t>(parsed), 1, 0));
    env.start_game(*scenario);
    env.state = game_running;
    std::string renderer, vendor, version, gallium_path;
    int swap_interval = 0;
    {
      ContextHolder selected(&env);
      swap_interval = SDL_GL_GetSwapInterval();
      const auto* gl_renderer = glGetString(GL_RENDERER);
      const auto* gl_vendor = glGetString(GL_VENDOR);
      const auto* gl_version = glGetString(GL_VERSION);
      Require(gl_renderer && gl_vendor && gl_version,
              "No actual OpenGL context or renderer identity");
      renderer = reinterpret_cast<const char*>(gl_renderer);
      vendor = reinterpret_cast<const char*>(gl_vendor);
      version = reinterpret_cast<const char*>(gl_version);
      gallium_path = LoadedGalliumPath();
      for (unsigned i = 0; glGetError() != GL_NO_ERROR; ++i)
        Require(i < 32, "Initialization GL error did not clear");
    }
    const frame_sync::SlotInput neutral{};
    for (unsigned i = 0; i < 180; ++i)
      env.StepWithInput(&neutral, sizeof(neutral));
    unsigned in_play = 0;
    std::vector<double> samples;
    std::vector<double> submit_samples;
    std::vector<double> finish_samples;
    samples.reserve(kSamples);
    submit_samples.reserve(kSamples);
    finish_samples.reserve(kSamples);
    for (unsigned frame = 0; frame < kWarmup + kSamples; ++frame) {
      env.StepWithInput(&neutral, sizeof(neutral));
      in_play += env.get_info().is_in_play;
      const auto before = std::chrono::steady_clock::now();
      std::chrono::steady_clock::time_point after_submit;
      {
        ContextHolder selected(&env);
        env.render(swap_enabled);
        after_submit = std::chrono::steady_clock::now();
        glFinish();  // Include completion, rather than submission alone.
        Require(glGetError() == GL_NO_ERROR, "Real render produced a GL error");
      }
      const auto after = std::chrono::steady_clock::now();
      if (frame >= kWarmup) {
        samples.push_back(std::chrono::duration<double, std::milli>(
                              after - before).count());
        submit_samples.push_back(std::chrono::duration<double, std::milli>(
                                     after_submit - before).count());
        finish_samples.push_back(std::chrono::duration<double, std::milli>(
                                     after - after_submit).count());
      }
    }
    Require(samples.size() == kSamples && in_play > 0,
            "Rendered no live match samples");
    Require(std::all_of(samples.begin(), samples.end(), [](double value) {
              return std::isfinite(value) && value > 0.;
            }), "Invalid full-resolution frame time");
    {
      ContextHolder selected(&env);
      GLint viewport[4]{};
      glGetIntegerv(GL_VIEWPORT, viewport);
      Require(viewport[2] == kWidth && viewport[3] == kHeight,
              "OpenGL viewport differs from 1080p target");
    }
    std::cout << std::fixed << std::setprecision(6)
              << "{\"seed\":" << parsed
              << ",\"vendor\":" << std::quoted(vendor)
              << ",\"renderer\":" << std::quoted(renderer)
              << ",\"gl_version\":" << std::quoted(version)
              << ",\"gallium_path\":" << std::quoted(gallium_path)
              << ",\"width\":" << kWidth
              << ",\"height\":" << kHeight
              << ",\"quality\":" << std::quoted(quality)
              << ",\"swap_enabled\":" << (swap_enabled ? "true" : "false")
              << ",\"swap_interval\":" << swap_interval
              << ",\"warmup_frames\":" << kWarmup
              << ",\"measured_frames\":" << samples.size()
              << ",\"in_play_frames\":" << in_play
              << ",\"p50_ms\":" << Percentile(samples, .50)
              << ",\"p95_ms\":" << Percentile(samples, .95)
              << ",\"p99_ms\":" << Percentile(samples, .99)
              << ",\"submit_p50_ms\":" << Percentile(submit_samples, .50)
              << ",\"submit_p95_ms\":" << Percentile(submit_samples, .95)
              << ",\"finish_p50_ms\":" << Percentile(finish_samples, .50)
              << ",\"finish_p95_ms\":" << Percentile(finish_samples, .95)
              << ",\"samples_ms\":[";
    for (size_t i = 0; i < samples.size(); ++i)
      std::cout << (i ? "," : "") << samples[i];
    std::cout << "],\"submit_samples_ms\":[";
    for (size_t i = 0; i < submit_samples.size(); ++i)
      std::cout << (i ? "," : "") << submit_samples[i];
    std::cout << "],\"finish_samples_ms\":[";
    for (size_t i = 0; i < finish_samples.size(); ++i)
      std::cout << (i ? "," : "") << finish_samples[i];
    std::cout << "]}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Render benchmark failed: " << error.what() << '\n';
    return 1;
  }
}
