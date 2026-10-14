// 2026-10-14: format-only adversarial tests, no engine/runtime dependency.
#include "training/training_snapshot.hpp"
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
namespace ts = football::training::snapshot;
namespace ks = blunted::snapshot;
void require(bool value) { if (!value) throw std::runtime_error("Training snapshot contract failed"); }
void reject(const std::function<void()>& operation) {
  try { operation(); } catch (const std::invalid_argument&) { return; }
  throw std::runtime_error("Malformed training snapshot accepted");
}
void checksum(std::string& bytes) { ks::Write32(bytes, 12, ks::Checksum(std::string_view(bytes).substr(16))); }
int main() {
  try {
    ts::State base;
    base.compatibility = "test-abi";
    base.scenario = std::string("scene\0bytes", 11);
    base.kernel = ks::Encode("format-only engine fixture");
    base.previous_score_diff = -3;
    const auto bytes = ts::Encode(base);
    require(bytes.substr(0, 4) == "FTRN" && ks::Read32(bytes, 4) == 1);
    require(ks::Read32(bytes, 16) == 18 && ks::Read32(bytes, 20) == 1);
    require(ks::Read32(bytes, 32) == 0xfffffffdu);
    require(ts::Decode(bytes) == base && ts::Encode(ts::Decode(bytes)) == bytes);
    for (size_t length = 0; length < bytes.size(); ++length)
      reject([&] { (void)ts::Decode(std::string_view(bytes).substr(0, length)); });
    for (size_t offset = 0; offset < bytes.size(); ++offset) {
      auto corrupted = bytes;
      corrupted[offset] ^= 1;
      reject([&] { (void)ts::Decode(corrupted); });
    }
    auto tamper = [&](size_t offset, uint32_t value) {
      auto changed = bytes;
      ks::Write32(changed, offset, value);
      checksum(changed);
      reject([&] { (void)ts::Decode(changed); });
    };
    tamper(16, 32);  // reserved flags
    tamper(20, 0);   // no controlled team
    tamper(24, 1);   // both teams controlled
    tamper(20, 0xffffffffu);
    tamper(28, 0); tamper(28, 1001);
    tamper(36, 7); tamper(40, 2);
    tamper(44, 0xffffffffu); // compatibility blob length
    // Oversized collection lengths with a correct outer checksum.
    const size_t scenario_length = 48 + base.compatibility.size();
    tamper(scenario_length, 0xffffffffu);
    const size_t checkpoint_length = scenario_length + 4 + base.scenario.size();
    tamper(checkpoint_length, 0xffffffffu);
    tamper(checkpoint_length + 4, 0xffffffffu);
    tamper(checkpoint_length + 8, 0xffffffffu); // nested kernel length
    auto trailing = bytes + "x";
    ks::Write32(trailing, 8, static_cast<uint32_t>(trailing.size() - 16));
    checksum(trailing);
    reject([&] { (void)ts::Decode(trailing); });
    reject([&] { (void)ts::Decode(std::string(ts::kMaxBytes + 1, 'x')); });
    auto nested = base;
    nested.kernel.back() ^= 1;
    reject([&] { (void)ts::Encode(nested); });
    auto nested_wire = bytes;
    nested_wire.back() ^= 1; checksum(nested_wire);
    reject([&] { (void)ts::Decode(nested_wire); });

    // Every immutable-option combination, both controlled sides and all counts.
    for (uint32_t flags = 0; flags < 32; ++flags) for (bool right : {false, true})
      for (uint32_t players = 1; players <= 11; ++players) {
        auto state = base;
        state.builtin_ai_action = flags & 1; state.fixed_positions = flags & 2;
        state.checkpoint_rewards = flags & 4; state.stacked = flags & 8;
        state.ready = flags & 16;
        state.left_agents = right ? 0 : players; state.right_agents = right ? players : 0;
        if (state.checkpoint_rewards) state.checkpoints.assign(players, 10);
        if (state.stacked) {
          state.history.resize(4 * players * 115);
          for (size_t i = 0; i < state.history.size(); ++i) state.history[i] = float(i) / 100;
          state.history[0] = -0.0f;
        }
        const auto wire = ts::Encode(state);
        require(ts::Decode(wire) == state && ts::Encode(ts::Decode(wire)) == wire);
      }
    auto bad = base;
    bad.checkpoint_rewards = true; bad.checkpoints = {11};
    reject([&] { (void)ts::Encode(bad); });
    bad.checkpoints = {0}; bad.stacked = true; bad.history.assign(460, 0);
    auto bad_counter_wire = ts::Encode(bad);
    bad_counter_wire[checkpoint_length + 4] = 11; checksum(bad_counter_wire);
    reject([&] { (void)ts::Decode(bad_counter_wire); });
    const size_t history_values = checkpoint_length + 4 + 1 + 4;
    auto nan_wire = ts::Encode(bad);
    ks::Write32(nan_wire, history_values, 0x7fc00000u); checksum(nan_wire);
    reject([&] { (void)ts::Decode(nan_wire); });
    for (float value : {std::numeric_limits<float>::infinity(), std::numeric_limits<float>::quiet_NaN()}) {
      bad.history[0] = value; reject([&] { (void)ts::Encode(bad); });
    }
    auto maximum = base;
    maximum.compatibility.assign(ts::kMaxIdentityBytes, 'a');
    maximum.scenario.assign(ts::kMaxScenarioBytes, 'b');
    maximum.left_agents = 11; maximum.stacked = maximum.checkpoint_rewards = true;
    maximum.history.assign(4 * 11 * 115, 1); maximum.checkpoints.assign(11, 10);
    maximum.kernel = ks::Encode(std::string(ks::kMaxBytes, 'k'));
    const auto maximum_bytes = ts::Encode(maximum);
    require(maximum_bytes.size() <= ts::kMaxBytes && ts::Decode(maximum_bytes) == maximum);
    maximum.scenario.push_back('b'); reject([&] { (void)ts::Encode(maximum); });
    auto bad_identity = base; bad_identity.compatibility.assign(ts::kMaxIdentityBytes + 1, 'x');
    reject([&] { (void)ts::Encode(bad_identity); });
    bad_identity.compatibility.clear(); reject([&] { (void)ts::Encode(bad_identity); });
    std::cout << "Training snapshot format contract passed (704 option/side/agent cases plus malformed boundaries)\n";
    return 0;
  } catch (const std::exception& failure) { std::cerr << failure.what() << '\n'; return 1; }
}
