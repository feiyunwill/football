// 2026-09-13: staged shared input admission through actual GameEnv instances.
// Synthetic SDL samples; this is not a device-to-photon latency measurement.
// 2026-09-13: formal gate compiles the canonical implementation.
// #include "../native-input-buffer-20260913-b/native_input_buffer.hpp"
#include "frame_sync/native_input_buffer.hpp"
// 2026-09-13: formal gate compiles the canonical implementation.
// #include "../native-input-admission-20260913-a/frame_simulation.hpp"
#include "frame_sync/frame_simulation.hpp"
// 2026-09-13: formal gate compiles the canonical implementation.
// #include "../native-input-admission-20260913-a/local_input_history.hpp"
#include "frame_sync/local_input_history.hpp"
#include "frame_sync/default_scenario.hpp"
#include "frame_sync/engine_bridge.hpp"
#include "frame_sync/input_codec.hpp"
#include <array>
#include <bit>
#include <iostream>
#include <map>
#include <stdexcept>
#include <vector>

namespace {
namespace fs = frame_sync;
std::uint64_t assertions = 0, steps = 0, corrected = 0, confirmations = 0;
void Require(bool condition, const char* message) {
  ++assertions;
  if (!condition) throw std::runtime_error(message);
}
void Start(GameEnv& env, unsigned int seed) {
  env.game_config.render = false;
  auto scenario = fs::MakeDefaultScenario(1, 1, seed);
  env.start_game(*scenario);
  env.state = game_running;
}
void Step(GameEnv& env, const std::array<fs::SlotInput, 2>& inputs) {
  env.StepWithInput(inputs.data(), sizeof(inputs));
  ++steps;
  Require(GetGame() == nullptr, "Step leaked environment selection");
}
fs::PythonWindowInput::Sample Sample(std::vector<std::string> keys = {}) {
  fs::PythonWindowInput::Sample sample;
  sample.focused = true;
  sample.keys = std::move(keys);
  return sample;
}
void CheckControllers(GameEnv& env, const std::array<fs::SlotInput, 2>& inputs) {
  ContextHolder selected(&env);
  for (int slot = 0; slot < 2; ++slot) {
    const int index = fs::SlotIndexToControllerIndex(slot, 1, 1);
    auto* controller = env.context->controllers[index];
    const auto direction = controller->GetOriginalDirection();
    Require(direction.coords[0] == inputs[slot].dir_x &&
            direction.coords[1] == inputs[slot].dir_y, "Actual controller direction differs");
    for (auto button : {e_ButtonFunction_KeeperRush, e_ButtonFunction_Pressure,
                        e_ButtonFunction_Sprint, e_ButtonFunction_Dribble}) {
      Require(controller->GetButton(button) == !!(inputs[slot].buttons & (1u << button)),
              "Actual sticky controller button differs");
    }
  }
}
void DirectAndReplay(unsigned int seed) {
  GameEnv env;
  Start(env, seed);
  const std::array<fs::SlotInput, 2> neutral{};
  for (int frame = 0; frame < 20; ++frame) Step(env, neutral);
  const auto before = env.get_state("input start");
  fs::NativeInputBuffer input;
  std::vector<std::array<fs::SlotInput, 2>> recorded;
  for (int frame = 0; frame < 120; ++frame) {
    auto sample = Sample();
    switch (frame % 12) {
      case 0: case 1: case 2: sample.keys = {"d", "lshift", "m", "space"}; break;
      case 3: sample.pressed_keys = {"v", "z"}; break;
      case 5: sample.connected = true; sample.axes = {.6f, -.8f};
              sample.buttons = (1u << 9) | (1u << 10); break;
      case 6: sample.connected = true; sample.axes = {.02f, -.02f}; break;
      case 8: sample.keys = {"w", "d", "lshift"}; break;
      case 9: sample.focused = false; sample.keys = {"d", "lshift"}; break;
      case 10: sample.keys = {"a", "lshift"}; break;
    }
    input.Feed(sample);
    const std::array<fs::SlotInput, 2> slots{input.Take(), fs::SlotInput::Default()};
    recorded.push_back(slots);
    Step(env, slots);
    CheckControllers(env, slots);
    if (frame % 12 == 4 || frame % 12 == 7 || frame % 12 == 9 || frame % 12 == 11)
      Require(slots[0] == fs::SlotInput::Default(), "Release, focus or disconnect retained input");
  }
  const auto expected = env.get_state_digest();
  Require(env.set_state(before) == "input start", "Replay metadata changed");
  for (const auto& slots : recorded) Step(env, slots);
  Require(env.get_state_digest() == expected, "Buffered input replay changed real match state");

  input.Feed(Sample({"d", "lshift"}));
  Step(env, {input.Take(), fs::SlotInput::Default()});
  input.SetSuspended(true);
  env.pause();
  const auto paused = env.get_state_digest();
  for (int wait = 0; wait < 6; ++wait) {
    input.Feed(Sample({"d", "lshift"}));
    Step(env, {input.Take(), fs::SlotInput::Default()});
    Require(env.get_state_digest() == paused, "Suspended input advanced paused match");
  }
  env.resume();
  input.SetSuspended(false);
  input.Feed(Sample({"d", "lshift"}));
  auto blocked = input.Take();
  Require(blocked == fs::SlotInput::Default() && input.release_required(),
          "Resume admitted a held key before neutral observation");
  Step(env, {blocked, fs::SlotInput::Default()});
  CheckControllers(env, {blocked, fs::SlotInput::Default()});
  input.Feed(Sample());
  Require(!input.release_required(), "Neutral observation did not release resume barrier");
  input.Feed(Sample({"d", "lshift"}));
  auto fresh = input.Take();
  Require(fresh.dir_x == 1 && (fresh.buttons & (1u << e_ButtonFunction_Sprint)),
          "Fresh input remained blocked after resume");
  Step(env, {fresh, fs::SlotInput::Default()});
  CheckControllers(env, {fresh, fs::SlotInput::Default()});
  env.close();
}
void ActualPlayerResponse(unsigned int seed) {
  GameEnv right, left;
  Start(right, seed); Start(left, seed);
  const std::array<fs::SlotInput, 2> neutral{};
  for (int frame = 0; frame < 30; ++frame) { Step(right, neutral); Step(left, neutral); }
  const auto initial = right.get_info();
  Require(initial.left_controllers.size() == MAX_PLAYERS, "Missing actual controller slots");
  const int owned = initial.left_controllers[0].controlled_player;
  Require(owned >= 0 && owned < int(initial.left_team.size()), "No player assigned to input slot");
  fs::NativeInputBuffer to_right, to_left;
  to_right.Feed(Sample({"d", "lshift"})); to_left.Feed(Sample({"a", "lshift"}));
  for (int frame = 0; frame < 30; ++frame) {
    Step(right, {to_right.Take(), fs::SlotInput::Default()});
    Step(left, {to_left.Take(), fs::SlotInput::Default()});
  }
  const auto a = right.get_info(), b = left.get_info();
  Require(a.left_team[owned].player_position != b.left_team[owned].player_position,
          "Opposing buffered directions never changed the actual owned player's position");
  right.close(); left.close();
}
void ActualReconciliation(unsigned int seed) {
  GameEnv authority, predicted;
  Start(authority, seed); Start(predicted, seed);
  auto callbacks = fs::MakeGameEnvCallbacks(&predicted);
  auto authoritative = fs::MakeGameEnvCallbacks(&authority);
  fs::FrameSimulation simulation(callbacks, 2);
  fs::LocalInputHistory history;
  fs::NativeInputBuffer buffer;
  const std::array<uint16_t, 1> own{0};
  std::map<fs::frame_id_t, std::uint64_t> hashes;
  std::map<fs::frame_id_t, fs::SlotInput> sent;
  unsigned int produced = 0;
  auto supply = [&](fs::frame_id_t frame) {
    history.Confirm(simulation.confirmed_count());
    auto [input, fresh] = history.ForFrame(frame, [&](fs::frame_id_t accepted) {
      ++produced;
      auto input = buffer.Take();
      sent.emplace(accepted, input);
      return input;
    });
    Require(input == sent.at(frame), "Retransmission changed the real-engine frame input");
    return input;
  };
  auto check = [&](const fs::FrameSimulation::TickResult& result) {
    for (const auto& confirmed : result.confirmed) {
      Require(confirmed.hash == hashes.at(confirmed.frame), "Real authoritative frame hash differs");
      ++confirmations;
    }
  };
  std::array<std::vector<fs::SlotInput>, 3> catchup;
  for (fs::frame_id_t frame = 0; frame < 3; ++frame) {
    catchup[frame] = {{0.f, 0.f, 0}, {.5f, 0.f, 0}};
    authoritative.step_frame(catchup[frame]);
    hashes[frame] = authoritative.compute_hash();
  }
  for (fs::frame_id_t frame : {2u, 0u, 1u})
    Require(simulation.QueueAuthority(frame, catchup[frame]), "Catchup authority rejected");
  buffer.Feed(Sample({"d", "lshift"}));
  check(simulation.TickWithInputProvider(supply, own, 0));
  Require(produced == 1 && sent.contains(3) && history.confirmed_count() == 3,
          "Real catchup bound input to the pre-authority frame");
  Require(callbacks.compute_hash() == authoritative.compute_hash(), "Catchup changed real match state");
  for (int wait = 0; wait < 10; ++wait) check(simulation.TickWithInputProvider(supply, own, 0));
  Require(produced == 1, "Waiting consumed repeated input in real engine");
  for (fs::frame_id_t frame = 3; frame < 41; ++frame) {
    auto sample = Sample(frame % 2 ? std::vector<std::string>{"d", "lshift"} :
                                   std::vector<std::string>{"a", "m"});
    if (frame % 7 == 0) sample.pressed_keys = {"v"};
    buffer.Feed(sample);
    const auto prediction = simulation.TickWithInputProvider(supply, own, 3);
    // The long wait disables prediction until frame 3's authority arrives.
    Require(prediction.predicted == (frame != 3),
            "Actual authority drought did not stop and resume prediction");
    const std::vector<fs::SlotInput> inputs{sent.at(frame),
        fs::SlotInput{frame % 2 ? -.5f : .5f, 0.f, 0}};
    authoritative.step_frame(inputs);
    hashes[frame] = authoritative.compute_hash();
    Require(simulation.QueueAuthority(frame, inputs), "Real authority rejected");
    const auto result = simulation.TickWithInputProvider(supply, own, 0);
    corrected += result.rolled_back;
    check(result);
    Require(callbacks.compute_hash() == authoritative.compute_hash(),
            "Rollback did not restore exact real match state");
    Require(simulation.next_frame() == frame + 1, "Real reconciliation frame index differs");
  }
  Require(simulation.confirmed_count() == 41 && produced == 39,
          "Real history lost authority or admitted the wrong cohort");
  authority.close(); predicted.close();
}
}  // namespace
// 2026-09-13: main.hpp declares the C-linkage argc/argv entry point.
// int main() {
int main(int, char**) {
  try {
    for (unsigned int seed : {42u, 43u}) {
      DirectAndReplay(seed);
      ActualPlayerResponse(seed);
      ActualReconciliation(seed);
    }
    Require(corrected > 0 && confirmations == 82, "Missing actual correction coverage");
    std::cout << "{\"passed\":true,\"skipped\":0,\"assertions\":" << assertions
              << ",\"actual_gameenv\":true,\"actual_sockets\":false"
              << ",\"synthetic_samples\":true,\"steps\":" << steps
              << ",\"confirmed_frames\":" << confirmations
              << ",\"corrected_frames\":" << corrected << "}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
