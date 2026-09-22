// 2026-09-09: exercise memory-limited reconciliation through the actual GameEnv bridge.
#include "frame_sync/default_scenario.hpp"
#include "frame_sync/engine_bridge.hpp"
#include "frame_sync/frame_simulation.hpp"
#include "frame_sync/replay_system.hpp"
#include <array>
#include <iostream>
#include <stdexcept>

namespace {
using namespace frame_sync;
unsigned assertions = 0;
size_t max_snapshot_bytes = 0, max_history_bytes = 0;
unsigned confirmed_frames = 0, corrections = 0;
void Require(bool value, const char* message) {
  ++assertions;
  if (!value) throw std::runtime_error(message);
}
void Start(GameEnv& env, uint32_t seed, uint16_t per_team) {
  env.game_config.render = false;
  env.game_config.physics_steps_per_frame = 10;
  auto scenario = MakeDefaultScenario(per_team, per_team, seed);
  env.start_game(*scenario);
  env.state = game_running;
}
std::vector<SlotInput> Inputs(size_t slots, unsigned frame) {
  std::vector<SlotInput> inputs(slots, SlotInput::Default());
  for (size_t i = 0; i < slots; ++i) {
    inputs[i].dir_x = ((frame + i) % 3 == 0) ? -1.0f : 1.0f;
    inputs[i].buttons = (frame % 5 == 0) ? (1 << e_ButtonFunction_Sprint) : 0;
  }
  return inputs;
}
void Scenario(uint32_t seed, uint16_t per_team) {
  GameEnv predicted, reference;
  Start(predicted, seed, per_team);
  Start(reference, seed, per_team);
  auto engine = MakeGameEnvCallbacks(&predicted);
  auto authority = MakeGameEnvCallbacks(&reference);
  const size_t slots = per_team * 2;
  for (unsigned frame = 0; frame < 20; ++frame) {
    auto inputs = Inputs(slots, frame);
    engine.step_frame(inputs);
    authority.step_frame(inputs);
  }
  const auto initial = engine.save_state();
  max_snapshot_bytes = std::max(max_snapshot_bytes, RetainedBytes(initial));
  Require(engine.compute_hash() == authority.compute_hash(), "Initial engines differ");
  const std::array<uint16_t, 1> local{0};
  SlotInput guess = SlotInput::Default();
  guess.dir_x = 1;

  ReplayRecorder replay;
  replay.StartRecording(seed, "native-memory-contract", static_cast<uint32_t>(slots));
  {
    FrameSimulation simulation(engine, slots);
//     for (unsigned batch = 0; batch < 8; ++batch) {
// 2026-09-09: use actual public API and respect the packet-silence threshold.
    constexpr unsigned batch_frames = MAX_FRAMES_WITHOUT_PACKET - 1;
    for (unsigned batch = 0; batch < 16; ++batch) {
//       for (unsigned frame = 0; frame < 8; ++frame) {
// 2026-09-09: use actual public API and respect the packet-silence threshold.
      for (unsigned frame = 0; frame < batch_frames; ++frame) {
        auto tick = simulation.Tick(guess, local, 8);
        Require(tick.predicted && !tick.prediction_limited, "Default budget blocks real prediction");
        Require(simulation.history_size() <= 8, "Prediction frame cap exceeded");
        Require(simulation.history_bytes() <= SnapshotBudget{}.history_bytes, "Prediction byte cap exceeded");
        max_history_bytes = std::max(max_history_bytes, simulation.history_bytes());
      }
//       std::array<uint64_t, 8> expected{};
// 2026-09-09: use actual public API and respect the packet-silence threshold.
      std::array<uint64_t, batch_frames> expected{};
//       for (unsigned frame = 0; frame < 8; ++frame) {
// 2026-09-09: use actual public API and respect the packet-silence threshold.
      for (unsigned frame = 0; frame < batch_frames; ++frame) {
//         const auto fid = batch * 8 + frame;
// 2026-09-09: use actual public API and respect the packet-silence threshold.
        const auto fid = batch * batch_frames + frame;
        auto inputs = Inputs(slots, fid);
        Require(simulation.QueueAuthority(fid, inputs), "Valid authority refused");
        authority.step_frame(inputs);
        expected[frame] = authority.compute_hash();
      }
      unsigned delivered = 0;
      while (simulation.pending_size()) {
        auto tick = simulation.Tick(guess, local, 0);
        Require(!tick.confirmed.empty(), "Authority stopped making progress");
        Require(!tick.prediction_limited, "Default rollback budget exhausted");
        corrections += tick.rolled_back;
        for (const auto& confirmation : tick.confirmed) {
//           Require(confirmation.frame == batch * 8 + delivered, "Confirmation order changed");
// 2026-09-09: use actual public API and respect the packet-silence threshold.
          Require(confirmation.frame == batch * batch_frames + delivered, "Confirmation order changed");
          Require(confirmation.hash == expected[delivered], "Corrected native frame hash differs");
          Require(replay.RecordFrame(confirmation.frame, confirmation.hash, confirmation.inputs),
                  "Real match recording unexpectedly refused");
          ++delivered;
          ++confirmed_frames;
        }
      }
//       Require(delivered == 8, "Missing native confirmations");
// 2026-09-09: use actual public API and respect the packet-silence threshold.
      Require(delivered == batch_frames, "Missing native confirmations");
      Require(simulation.history_bytes() == 0 && simulation.history_size() == 0, "Confirmed history retained");
      Require(simulation.pending_bytes() == 0, "Confirmed inputs retained");
      Require(predicted.get_state_digest() == reference.get_state_digest(), "Full native digest differs");
      Require(GetGame() == nullptr, "Native callback leaked context");
    }
  }
  const auto final_digest = reference.get_state_digest();
  ReplayPlayer player;
  Require(player.LoadReplay(replay.Serialize()), "Native replay failed to load");
  engine.restore_state(initial);
//   while (const auto* frame = player.GetNextFrame()) {
// 2026-09-09: use actual public API and respect the packet-silence threshold.
  player.Play();
  while (player.IsPlaying()) {
    const auto frame = player.GetCurrentFrame();
    Require(frame.has_value(), "Playback lost current frame");
    engine.step_frame(frame->inputs);
//     Require(engine.compute_hash() == frame->state_hash, "Replayed native frame differs");
// 2026-09-09: use actual public API and respect the packet-silence threshold.
    Require(engine.compute_hash() == frame->state_hash, "Replayed native frame differs");
    player.Advance();
  }
  Require(predicted.get_state_digest() == final_digest, "Replayed full digest differs");

  // A budget smaller than a real snapshot pauses prediction before stepping,
  // while authority continues without needing a retained prediction snapshot.
  engine.restore_state(initial);
  authority.restore_state(initial);
  {
    FrameSimulation simulation(engine, slots, SnapshotBudget(1, 1));
    auto before = predicted.get_state_digest();
    auto tick = simulation.Tick(guess, local, 8);
    Require(tick.prediction_limited && !tick.predicted, "Tiny budget did not stop prediction");
    Require(before == predicted.get_state_digest(), "Rejected prediction advanced native engine");
    auto inputs = Inputs(slots, 0);
    Require(simulation.QueueAuthority(0, inputs), "Tiny snapshot budget blocked authority");
    tick = simulation.Tick(guess, local, 0);
    authority.step_frame(inputs);
    Require(tick.confirmed.size() == 1, "Tiny budget lost authoritative frame");
    Require(predicted.get_state_digest() == reference.get_state_digest(), "Tiny budget changed authority");
  }

  // Force aggregate exhaustion with actual snapshots, then drain and resume.
  engine.restore_state(initial);
  authority.restore_state(initial);
  {
    SnapshotBudget budget(256 * 1024, 256 * 1024);
    FrameSimulation simulation(engine, slots, budget);
    unsigned accepted = 0;
    for (unsigned attempt = 0; attempt < 8; ++attempt) {
      auto before = predicted.get_state_digest();
      auto tick = simulation.Tick(guess, local, 8);
      Require(simulation.history_bytes() <= budget.history_bytes, "Aggregate native cap exceeded");
      if (tick.prediction_limited) {
        Require(before == predicted.get_state_digest(), "Aggregate rejection advanced engine");
        break;
      }
      Require(tick.predicted, "Prediction stopped for an unexpected reason");
      ++accepted;
    }
    Require(accepted > 0 && accepted < 8, "Fixture did not reach aggregate byte limit");
    for (unsigned frame = 0; frame < accepted; ++frame) {
      auto inputs = Inputs(slots, frame);
      Require(simulation.QueueAuthority(frame, inputs), "Drain authority refused");
      authority.step_frame(inputs);
    }
    while (simulation.pending_size()) simulation.Tick(guess, local, 0);
    Require(simulation.history_bytes() == 0, "Drained native history retains bytes");
    Require(predicted.get_state_digest() == reference.get_state_digest(), "Drain changed native result");
    Require(simulation.Tick(guess, local, 8).predicted, "Prediction did not recover after drain");
  }

  // Preserve real snapshot contents but inject oversized capacity after a
  // correction. This is callback-capacity fault injection, not natural growth.
  engine.restore_state(initial);
  authority.restore_state(initial);
  {
    bool inflated = false;
    EngineCallbacks callbacks = engine;
    callbacks.step_frame = [&](std::span<const SlotInput> inputs) {
      engine.step_frame(inputs);
      inflated = inputs.back().dir_x < 0;
    };
    callbacks.save_state = [&] {
      auto bytes = engine.save_state();
      if (inflated) bytes.reserve(SnapshotBudget{}.snapshot_bytes + 1);
      return bytes;
    };
    FrameSimulation simulation(callbacks, slots);
    for (unsigned frame = 0; frame < 3; ++frame)
      Require(simulation.Tick(guess, local, 8).predicted, "Growth fixture failed to predict");
    auto corrected = Inputs(slots, 0);
    corrected.back().dir_x = -1;
    Require(simulation.QueueAuthority(0, corrected), "Correction refused");
    auto tick = simulation.Tick(guess, local, 0);
    authority.step_frame(corrected);
    Require(tick.rolled_back && tick.prediction_limited, "Growth did not trigger correction recovery");
    Require(tick.confirmed.size() == 1, "Growth recovery did not confirm root");
    Require(simulation.next_frame() == 1 && simulation.history_bytes() == 0, "Growth retained invalid speculation");
    Require(predicted.get_state_digest() == reference.get_state_digest(), "Growth recovery native digest differs");
    inflated = false;
    Require(simulation.Tick(guess, local, 8).predicted, "Growth recovery could not resume prediction");
  }
}
}  // namespace

// int main() {
// 2026-09-09: use actual public API and respect the packet-silence threshold.
int main(int, char**) {
  try {
    Scenario(42, 2);
    Scenario(43, 11);
    std::cout << "{\"passed\":true,\"assertions\":" << assertions
              << ",\"skipped\":0,\"confirmed_frames\":" << confirmed_frames
              << ",\"corrections\":" << corrections
              << ",\"max_initial_snapshot_bytes\":" << max_snapshot_bytes
              << ",\"max_history_bytes\":" << max_history_bytes << "}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "engine_memory_contract: " << error.what() << '\n';
    return 1;
  }
}
