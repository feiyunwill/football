// 2026-09-09: exercise ownership against the real engine and real resources.
#include "frame_sync/default_scenario.hpp"
#include "game_env.hpp"

#include <atomic>
#include <array>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <unistd.h>
#include <SDL_ttf.h>
#include <GL/gl.h>

namespace {
std::atomic<int> assertions{0};
void Require(bool condition, const char* message) {
  ++assertions;
  if (!condition) throw std::runtime_error(message);
}

void Start(GameEnv& environment, uint32_t seed = 42) {
  environment.game_config.render = false;
  auto scenario = frame_sync::MakeDefaultScenario(1, 1, seed);
  environment.start_game(*scenario);
  environment.state = game_running;
  Require(GetGame() == nullptr, "Startup leaked its TLS context");
}

void Step(GameEnv& environment, int frame) {
  environment.action(frame % 2 ? game_left : game_right, true, 0);
  environment.step();
}

size_t ResidentBytes() {
  std::ifstream stream("/proc/self/statm");
  size_t virtual_pages = 0, resident_pages = 0;
  stream >> virtual_pages >> resident_pages;
  Require(static_cast<bool>(stream), "Cannot read actual process memory");
  return resident_pages * static_cast<size_t>(sysconf(_SC_PAGESIZE));
}

void StartupFailure(int argc, char** argv) {
  Require(argc == 4, "Expected compile and link failure asset paths");
  const int initial_fonts = TTF_WasInit();
  GameEnv environment;
  for (int variant = 2; variant < argc; ++variant) {
    environment.game_config.render = true;
    environment.game_config.render_resolution_x = 320;
    environment.game_config.render_resolution_y = 180;
    environment.game_config.data_dir = argv[variant];
    bool rejected = false;
    try { environment.start_game(); }
    catch (const std::runtime_error& error) {
      const std::string expected = variant == 2 ? "compile fragment" : "link shader";
      rejected = std::string(error.what()).find(expected) != std::string::npos;
    }
    Require(rejected, "Invalid shader was not rejected with the expected diagnostic");
    Require(!environment.context, "Failed startup retained a partial context");
    Require(GetGame() == nullptr, "Failed startup retained a TLS selection");
    Require(TTF_WasInit() == initial_fonts, "Failed startup retained font initialization");
    environment.close();
  }
  environment.game_config.data_dir.clear();
  Start(environment);
  Step(environment, 0);
  environment.close();
  Require(TTF_WasInit() == initial_fonts, "Retry after failed startup leaked fonts");
  std::cout << "{\"passed\":true,\"assertions\":" << assertions
            << ",\"skipped\":0}" << std::endl;
}

void GraphicsLifetime() {
  const int initial_fonts = TTF_WasInit();
  std::string renderer;
  {
    GameEnv first, second;
    for (auto* environment : {&first, &second}) {
      environment->game_config.render = true;
      environment->game_config.render_resolution_x = 320;
      environment->game_config.render_resolution_y = 180;
      auto scenario = frame_sync::MakeDefaultScenario(1, 1, 42);
      environment->start_game(*scenario);
      environment->state = game_running;
      environment->step();
      auto pixels = environment->get_frame();
      Require(pixels.size() == 320 * 180 * 3, "Rendered frame has the wrong dimensions");
      size_t differing_pixels = 0;
      for (size_t pixel = 3; pixel < pixels.size(); pixel += 3)
        differing_pixels += pixels.compare(pixel, 3, pixels, 0, 3) != 0;
      Require(differing_pixels > 100, "Rendered frame is blank or uniform");
    }
    {
      ContextHolder selected(&second);
      renderer = reinterpret_cast<const char*>(glGetString(GL_RENDERER));
      Require(glGetError() == GL_NO_ERROR, "GL errors after context initialization");
    }
    first.close();
    const auto before = second.get_frame();
    second.step();
    Require(second.get_frame() != before, "Closing one GL context prevented the other from rendering");
    // 2026-09-10: validation failure preserves physical state and display history.
    second.save_render_state();
    const auto reset_digest = second.get_state_digest();
    const auto reset_step = second.get_info().step;
    const int tracker_depth = second.context->tracker_disabled;
    for (int variant = 0; variant < 2; ++variant) {
      auto invalid = frame_sync::MakeDefaultScenario(1, 1, 42);
      const int cadence = second.game_config.physics_steps_per_frame;
      if (variant == 0) invalid->left_agents = 12;
      else second.game_config.physics_steps_per_frame = 0;
      bool rejected = false;
      try { second.reset(*invalid, false); }
      catch (const std::invalid_argument&) { rejected = true; }
      second.game_config.physics_steps_per_frame = cadence;
      Require(rejected, "Invalid graphical reset was accepted");
      Require(second.get_info().step == reset_step, "Rejected reset changed the frame");
      Require(second.get_state_digest() == reset_digest, "Rejected reset changed physical state");
      Require(second.context->tracker_disabled == tracker_depth, "Rejected reset changed tracker nesting");
      second.render_interpolated(1.0f, false);
      Require(second.get_frame().size() == 320 * 180 * 3,
              "Rejected reset discarded the captured rendering pose");
    }
    {
      ContextHolder selected(&second);
      Require(glGetError() == GL_NO_ERROR, "GL errors after closing the other environment");
    }
  }
  Require(TTF_WasInit() == initial_fonts, "Graphical environment leaked font initialization");
  Require(GetGame() == nullptr, "Graphical environment leaked TLS state");
  std::cout << "{\"passed\":true,\"assertions\":" << assertions
            << ",\"skipped\":0,\"renderer\":\"" << renderer << "\"}" << std::endl;
}
}  // namespace

int main(int argc, char** argv) {
  try {
    if (argc > 1 && std::string(argv[1]) == "--render") {
      GraphicsLifetime();
      return 0;
    }
    if (argc > 1 && std::string(argv[1]) == "--startup-failure") {
      StartupFailure(argc, argv);
      return 0;
    }
    const int initial_fonts = TTF_WasInit();
    {
      GameEnv empty;
      empty.close();
      bool rejected = false;
      try { empty.step(); } catch (const std::logic_error&) { rejected = true; }
      Require(rejected, "Unstarted environment accepted a simulation step");
    }
    std::srand(123);
    const int expected_host_random = std::rand();
    std::srand(123);
    std::string reference;
    {
      GameEnv baseline;
      Start(baseline);
      for (int frame = 0; frame < 40; ++frame) Step(baseline, frame);
      reference = baseline.get_state_digest();
    }
    Require(std::rand() == expected_host_random, "Engine startup modified the host C RNG");
    Require(GetGame() == nullptr, "Destruction left a dangling TLS pointer");
    Require(TTF_WasInit() == initial_fonts, "Font subsystem initialization leaked");
    {
      GameEnv first, second;
      Start(first);
      Start(second, 43);
      bool duplicate_start_rejected = false;
      try { first.start_game(); } catch (const std::logic_error&) { duplicate_start_rejected = true; }
      Require(duplicate_start_rejected, "Starting a live environment twice was accepted");
      for (int frame = 0; frame < 40; ++frame) {
        Step(first, frame);
        Step(second, 40 - frame);
        Require(GetGame() == nullptr, "Interleaved API calls leaked TLS selection");
        Require(first.get_info().step == first.context->step, "Observation came from another environment");
      }
      Require(first.get_state_digest() == reference, "A second environment changed deterministic simulation");
      {
        ContextHolder outer(&first);
        Require(GetGame() == &first, "Outer context was not selected");
        second.get_info();
        Require(GetGame() == &first, "Nested API call did not restore the caller context");
        { ContextHolder inner(&first); first.get_info(); }
        Require(GetGame() == &first, "Same-environment nesting lost the caller context");
      }
      std::weak_ptr<GameTask> task = first.context->gameTask;
      std::weak_ptr<Scene3D> scene = first.context->scene3D;
      first.close();
      first.close();
      Require(!first.context && task.expired() && scene.expired(), "Environment still owns a task or scene after close");
      Require(TTF_WasInit() == initial_fonts + 1, "Closing one environment shut down another environment's fonts");
      Step(second, 41);
      Require(second.get_info().step == second.context->step, "Surviving environment is unusable");
      bool rejected = false;
      try { first.get_info(); } catch (const std::logic_error&) { rejected = true; }
      Require(rejected, "Closed environment accepted observation access");
      Start(first);
      Require(first.get_info().step == first.context->step, "Reopened environment has stale context");
      // Passing an environment to another thread is legal when operations are
      // serialized; TLS selection and dispatch state must follow that thread.
      std::exception_ptr failure;
      std::thread worker([&] {
        try { Step(first, 0); } catch (...) { failure = std::current_exception(); }
      });
      worker.join();
      if (failure) std::rethrow_exception(failure);
      Require(GetGame() == nullptr, "Worker-thread step changed the caller TLS selection");
    }
    Require(TTF_WasInit() == initial_fonts, "Multi-environment teardown leaked fonts");
    {
      GameEnv default_environment;
      default_environment.game_config.render = false;
      default_environment.start_game();
      Require(default_environment.get_info().left_team.size() == 11, "Default Python startup has no valid team");
    }
    {
      std::array<std::exception_ptr, 2> errors;
      std::array<std::string, 2> digests;
      std::array<std::thread, 2> workers;
      for (size_t index = 0; index < workers.size(); ++index) {
        workers[index] = std::thread([&, index] {
          try {
            GameEnv environment;
            Start(environment);
            for (int frame = 0; frame < 40; ++frame) Step(environment, frame);
            digests[index] = environment.get_state_digest();
          } catch (...) { errors[index] = std::current_exception(); }
        });
      }
      for (auto& worker : workers) worker.join();
      for (size_t index = 0; index < workers.size(); ++index) {
        if (errors[index]) std::rethrow_exception(errors[index]);
        Require(digests[index] == reference, "Concurrent environments changed simulation results");
      }
      Require(TTF_WasInit() == initial_fonts, "Concurrent teardown leaked font references");
    }
    size_t warm_memory = 0;
    size_t final_memory = 0;
    for (int cycle = 0; cycle < 12; ++cycle) {
      {
        GameEnv environment;
        environment.game_config.render = false;
        auto scenario = frame_sync::MakeDefaultScenario(1, 1, 42);
        scenario->ball_position = Vector3(.1f, .2f, 0);
        environment.start_game(*scenario);
        environment.state = game_running;
        Require(scenario->ball_position == Vector3(.1f, .2f, 0), "Startup mutated caller scenario coordinates");
        environment.reset(*scenario, false);
        Require(scenario->ball_position == Vector3(.1f, .2f, 0), "Reset scaled caller scenario coordinates twice");
        for (int frame = 0; frame < 10; ++frame) Step(environment, frame);
      }
      Require(GetGame() == nullptr, "Loop teardown left dangling TLS state");
      Require(TTF_WasInit() == initial_fonts, "Repeated restart leaked font references");
      final_memory = ResidentBytes();
      if (cycle == 3) warm_memory = final_memory;
    }
    // RSS includes allocator caching; reject sustained growth equivalent to
    // retaining another full match, then use sanitizers for exact allocations.
    Require(final_memory <= warm_memory + 16 * 1024 * 1024, "Repeated restart retained match-sized allocations");
    std::cout << "{\"passed\":true,\"assertions\":" << assertions
              << ",\"skipped\":0,\"warm_rss_bytes\":" << warm_memory
              << ",\"final_rss_bytes\":" << final_memory << "}" << std::endl;
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Engine lifetime contract: " << error.what() << std::endl;
    return 1;
  }
}
