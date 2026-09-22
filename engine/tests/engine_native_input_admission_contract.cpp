// Execute both the frozen original algorithm and the proposed provider path.
#define FrameSimulation PreviousFrameSimulation
// 2026-09-13: formal gate compiles the canonical implementation.
// #include "before/frame_simulation.hpp"
#include "fixtures/frame_simulation_before_input_20260913.inc"
#undef FrameSimulation
#undef GFOOTBALL_FRAME_SYNC_FRAME_SIMULATION_HPP
// 2026-09-13: formal gate compiles the canonical implementation.
// #include "frame_simulation.hpp"
#include "frame_sync/frame_simulation.hpp"
// 2026-09-13: formal gate compiles the canonical implementation.
// #include "local_input_history.hpp"
#include "frame_sync/local_input_history.hpp"
// 2026-09-13: formal gate compiles the canonical implementation.
// #include "../native-input-buffer-20260913-b/native_input_buffer.hpp"
#include "frame_sync/native_input_buffer.hpp"

#include <array>
#include <bit>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace {
std::uint64_t assertions = 0;
void Require(bool value, const char* message) {
  ++assertions;
  if (!value) throw std::runtime_error(message);
}
template<class Function> void Reject(Function function, const char* message) {
  bool rejected = false;
  try { function(); } catch (const std::exception&) { rejected = true; }
  Require(rejected, message);
}
using frame_sync::SlotInput;
using frame_sync::frame_id_t;
const std::array<uint16_t, 1> own_slot{0};
const SlotInput neutral = SlotInput::Default();

class Engine {
 public:
  Engine() = default;
  ~Engine() = default;
  Engine(const Engine&) = delete;
  Engine& operator=(const Engine&) = delete;
  Engine(Engine&&) = delete;
  Engine& operator=(Engine&&) = delete;
  std::array<int64_t, 3> state{};
  std::vector<std::array<SlotInput, 2>> steps;
  bool enlarge_after_correction = false;
  frame_sync::EngineCallbacks Callbacks() {
    frame_sync::EngineCallbacks callbacks;
    callbacks.save_state = [this] {
      frame_sync::StateBlob bytes(sizeof(state));
      if (enlarge_after_correction && state[1] == -1 && state[2] == 1) bytes.reserve(128);
      std::memcpy(bytes.data(), state.data(), sizeof(state));
      return bytes;
    };
    callbacks.restore_state = [this](const frame_sync::StateBlob& bytes) {
      Require(bytes.size() == sizeof(state), "Incorrect model snapshot layout");
      std::memcpy(state.data(), bytes.data(), sizeof(state));
    };
    callbacks.step_frame = [this](std::span<const SlotInput> inputs) {
      Require(inputs.size() == 2, "Lost complete frame slot count");
      for (int slot = 0; slot < 2; ++slot) {
        state[slot] += static_cast<int>(inputs[slot].dir_x) + 100 * inputs[slot].buttons;
      }
      ++state[2];
      steps.push_back({inputs[0], inputs[1]});
    };
    callbacks.compute_hash = [this] {
      return uint64_t(state[0]) ^ (uint64_t(state[1]) * 1000003) ^ (uint64_t(state[2]) * 982451653);
    };
    return callbacks;
  }
};

std::vector<SlotInput> Authority(frame_id_t frame) {
  return {{frame % 2 ? -1.f : 1.f, 0.f, uint16_t(frame % 3 ? 0 : 1u << 9)},
          {frame % 3 ? 1.f : -1.f, 0.f, uint16_t(frame % 7 ? 0 : 1u << 2)}};
}

void ConstantInputCompatibility() {
  Engine old_engine, new_engine;
  frame_sync::PreviousFrameSimulation old(old_engine.Callbacks(), 2);
  frame_sync::FrameSimulation current(new_engine.Callbacks(), 2);
  for (int iteration = 0; iteration < 1000; ++iteration) {
    const auto frame = old.confirmed_count();
    for (const auto incoming : {frame + 1, frame, frame}) {
      const auto authority = Authority(incoming);
      Require(old.QueueAuthority(incoming, authority) == current.QueueAuthority(incoming, authority),
              "Authority admission changed");
    }
    const SlotInput input{iteration % 2 ? -1.f : 1.f, 0.f, uint16_t(iteration % 11 ? 0 : 1u << 3)};
    const int cap = iteration % 8 ? 3 : 0;
    const auto expected = old.Tick(input, own_slot, cap);
    const auto actual = current.Tick(input, own_slot, cap);
    Require(old_engine.state == new_engine.state, "Fixed-input API changed model state");
    Require(expected.predicted == actual.predicted && expected.rolled_back == actual.rolled_back &&
            expected.prediction_limited == actual.prediction_limited, "Fixed-input tick result changed");
    Require(old.next_frame() == current.next_frame() && old.confirmed_count() == current.confirmed_count() &&
            old.history_size() == current.history_size() && old.history_bytes() == current.history_bytes() &&
            old.pending_size() == current.pending_size() && old.pending_bytes() == current.pending_bytes(),
            "Fixed-input retained history changed");
    Require(expected.confirmed.size() == actual.confirmed.size(), "Confirmation count changed");
    for (std::size_t i = 0; i < expected.confirmed.size(); ++i) {
      const auto& left = expected.confirmed[i]; const auto& right = actual.confirmed[i];
      Require(left.frame == right.frame && left.hash == right.hash && left.inputs == right.inputs &&
              left.was_predicted == right.was_predicted && left.prediction_correct == right.prediction_correct,
              "Confirmation content changed");
    }
  }
  Require(old.confirmed_count() == 2000, "Compatibility trace did not cover all authority frames");
}

void CacheBoundaries() {
  frame_sync::LocalInputHistory history(0, 2);
  int produced = 0;
  auto produce = [&](frame_id_t frame) { ++produced; return SlotInput{-0.f, 0.f, uint16_t(1u << frame)}; };
  const auto first = history.ForFrame(0, produce);
  const auto again = history.ForFrame(0, produce);
  Require(first.second && !again.second && produced == 1, "Repeated frame consumed another input");
  Require(std::bit_cast<uint32_t>(again.first.dir_x) == 0x80000000u,
          "Cached input lost signed-zero wire bits");
  Require(history.ForFrame(1, produce).second && history.size() == 2, "History did not fill");
  Reject([&] { history.ForFrame(2, produce); }, "History overwrote unconfirmed input");
  Require(produced == 2 && history.size() == 2, "Capacity rejection consumed an input");
  history.Confirm(1);
  Require(!history.ForFrame(1, produce).second && produced == 2, "Confirmation erased a future input");
  Require(history.ForFrame(2, produce).second && produced == 3, "Confirmed slot was not reusable");
  Reject([&] { history.ForFrame(0, produce); }, "Confirmed frame accepted fresh input");
  Reject([&] { history.Confirm(0); }, "Confirmed boundary moved backwards");
  history.Confirm(100);
  Require(history.size() == 0 && history.confirmed_count() == 100, "Authority jump retained stale inputs");
  auto invalid = [](frame_id_t) { return SlotInput{std::numeric_limits<float>::infinity(), 0, 0}; };
  Reject([&] { history.ForFrame(100, invalid); }, "Invalid local direction entered history");
  Reject([&] { history.ForFrame(100, [](frame_id_t) -> SlotInput { throw std::runtime_error("source failure"); }); },
         "Input source exception was swallowed");
  Require(history.size() == 0, "Failed source retained an entry");
  Reject([&] { history.ForFrame(100, [&](frame_id_t) { history.Confirm(101); return neutral; }); },
         "Producer mutated its confirmed boundary");
  Reject([&] { history.ForFrame(100, [&](frame_id_t) { return history.ForFrame(100, [](frame_id_t) { return neutral; }).first; }); },
         "Producer reentered history");
  Require(history.confirmed_count() == 100 && history.size() == 0, "Reentrancy changed retained state");
  Require(history.ForFrame(100, [](frame_id_t) { return neutral; }).second, "Failed producer left history locked");
  frame_sync::LocalInputHistory end(UINT32_MAX - 1, 2);
  Require(end.ForFrame(UINT32_MAX - 1, [](frame_id_t) { return neutral; }).second, "Last representable frame rejected");
  end.Confirm(UINT32_MAX);
  Reject([&] { end.ForFrame(UINT32_MAX, [](frame_id_t) { return neutral; }); }, "Frame lifetime wrapped");
  Reject([] { frame_sync::LocalInputHistory invalid(0, 0); }, "Zero history capacity accepted");
  Reject([] { frame_sync::LocalInputHistory invalid(0, frame_sync::kMaxBufferedAuthorityFrames + 1); },
         "Unbounded history capacity accepted");
}

void ProviderAfterCatchup() {
  Engine engine;
  frame_sync::FrameSimulation simulation(engine.Callbacks(), 2);
  for (frame_id_t frame = 0; frame < 3; ++frame)
    Require(simulation.QueueAuthority(frame, Authority(frame)), "Cannot queue catchup frame");
  int calls = 0;
  const auto result = simulation.TickWithInputProvider([&](frame_id_t frame) {
    ++calls;
    Require(frame == 3 && engine.state[2] == 3 && simulation.confirmed_count() == 3,
            "Input provider ran before authority catchup finished");
    return SlotInput{0.f, 1.f, 1u << 3};
  }, own_slot);
  Require(calls == 1 && result.confirmed.size() == 3 && result.predicted && simulation.next_frame() == 4,
          "Post-catchup input did not advance the correct frame");
  Require(engine.steps.back()[0] == SlotInput{0.f, 1.f, 1u << 3}, "Wrong input reached prediction");
  const std::array<uint16_t, 1> invalid_slot{2};
  simulation.TickWithInputProvider([&](frame_id_t) { ++calls; return neutral; }, invalid_slot);
  Require(calls == 1, "Invalid ownership consumed local input");
  Reject([&] { simulation.TickWithInputProvider([&](frame_id_t) -> SlotInput {
    simulation.Tick(neutral, own_slot); return neutral;
  }, own_slot); }, "Input provider reentered simulation");
  const auto next = simulation.next_frame();
  Reject([&] { simulation.TickWithInputProvider([](frame_id_t) -> SlotInput {
    throw std::runtime_error("transport failure");
  }, own_slot); }, "Input provider failure was swallowed");
  Require(simulation.next_frame() == next, "Failed provider advanced prediction");
  simulation.TickWithInputProvider([&](frame_id_t) { ++calls; return neutral; }, own_slot, 0);
  Require(calls == 2, "Provider exception left the simulation locked");
}

frame_sync::PythonWindowInput::Sample Press(const char* key) {
  frame_sync::PythonWindowInput::Sample sample;
  sample.focused = true;
  if (key) sample.pressed_keys = {key};
  return sample;
}

void WaitingPreservesPendingTap() {
  Engine engine;
  frame_sync::FrameSimulation simulation(engine.Callbacks(), 2);
  frame_sync::NativeInputBuffer buffer;
  frame_sync::LocalInputHistory history;
  int produced = 0;
  std::vector<std::pair<frame_id_t, SlotInput>> submitted;
  auto provider = [&](frame_id_t frame) {
    history.Confirm(simulation.confirmed_count());
    auto [input, fresh] = history.ForFrame(frame, [&](frame_id_t) { ++produced; return buffer.Take(); });
    if (fresh) submitted.emplace_back(frame, input);
    return input;
  };
  buffer.Feed(Press("v"));
  simulation.TickWithInputProvider(provider, own_slot, 0);
  buffer.Feed(Press("z"));
  for (int attempt = 0; attempt < 12; ++attempt)
    Require(!simulation.TickWithInputProvider(provider, own_slot, 0).predicted, "Suspended prediction advanced");
  Require(produced == 1 && submitted.size() == 1 && submitted[0].first == 0 &&
          submitted[0].second.buttons == (1u << 3), "Repeated waits resubmitted or changed the first tap");
  Require(simulation.QueueAuthority(0, {submitted[0].second, neutral}), "Cannot confirm waiting input");
  simulation.TickWithInputProvider(provider, own_slot, 0);
  Require(produced == 2 && submitted.size() == 2 && submitted[1].first == 1 &&
          submitted[1].second.buttons == (1u << 2), "Waiting consumed the next tap or assigned it to an old frame");
}

void RecoverCorrectionReusesInput() {
  Engine engine;
  engine.enlarge_after_correction = true;
  frame_sync::FrameSimulation simulation(engine.Callbacks(), 2, frame_sync::SnapshotBudget(64, 512));
  frame_sync::NativeInputBuffer buffer;
  frame_sync::LocalInputHistory history;
  std::vector<std::pair<frame_id_t, SlotInput>> submitted;
  int produced = 0;
  auto provider = [&](frame_id_t frame) {
    history.Confirm(simulation.confirmed_count());
    auto [input, fresh] = history.ForFrame(frame, [&](frame_id_t) { ++produced; return buffer.Take(); });
    if (fresh) submitted.emplace_back(frame, input);
    return input;
  };
  for (const char* key : {"z", "v", "lshift"}) {
    buffer.Feed(Press(key));
    Require(simulation.TickWithInputProvider(provider, own_slot).predicted, "Initial prediction failed");
  }
  Require(produced == 3 && simulation.next_frame() == 3, "Missing original input history");
  buffer.Feed(Press("b"));
  Require(simulation.QueueAuthority(0, {submitted[0].second, SlotInput{-1.f, 0.f, 0}}),
          "Cannot queue divergent authority");
  const auto correction = simulation.TickWithInputProvider(provider, own_slot);
  Require(correction.rolled_back && correction.prediction_limited && !correction.predicted &&
          simulation.next_frame() == 1 && simulation.confirmed_count() == 1 && engine.state[2] == 1,
          "Real snapshot-budget correction did not rewind speculation");
  Require(produced == 3 && submitted.size() == 3 && history.size() == 2,
          "Rewind consumed the pending tap or discarded future input history");
  Require(simulation.QueueAuthority(1, {submitted[1].second, neutral}), "Cannot queue recovery authority");
  const auto recovery = simulation.TickWithInputProvider(provider, own_slot);
  Require(recovery.predicted && simulation.next_frame() == 3 && produced == 3 &&
          engine.steps.back()[0] == submitted[2].second, "Recovery failed to reuse the original frame-two input");
  Require(simulation.TickWithInputProvider(provider, own_slot).predicted, "Fresh frame did not resume");
  Require(produced == 4 && submitted.size() == 4 && submitted.back().first == 3 &&
          submitted.back().second.buttons == (1u << 5), "Pending new tap was lost or applied during replay");
}
}

int main() {
  try {
    ConstantInputCompatibility();
    CacheBoundaries();
    ProviderAfterCatchup();
    WaitingPreservesPendingTap();
    RecoverCorrectionReusesInput();
    std::cout << "{\"passed\":true,\"skipped\":0,\"assertions\":" << assertions
              << ",\"compatibility_authority_frames\":2000,\"actual_frame_simulation\":true,"
                 "\"actual_gameenv\":false,\"history_capacity\":" << frame_sync::kMaxBufferedAuthorityFrames
              << ",\"history_object_bytes\":" << sizeof(frame_sync::LocalInputHistory) << "}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
