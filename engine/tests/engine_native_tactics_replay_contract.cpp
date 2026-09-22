
#include <fstream>
#include <iostream>

#include "frame_sync/engine_tcp_bridge.hpp"
#include "frame_sync/native_match_replay.hpp"
namespace fs = frame_sync;
unsigned assertions = 0;
void Require(bool v, const char* m) {
  ++assertions;
  if (!v) throw std::runtime_error(m);
}
int main(int argc, char** argv) {
  try {
    // 2026-09-14: compare a real client's independently saved inputs and hashes too.
    // Require(argc == 2, "Expected authority file");
    Require(argc == 2 || argc == 3, "Expected authority and optional actual-client replay files");
    std::ifstream stream(argv[1], std::ios::binary);
    Require(bool(stream), "Cannot open authority");
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(stream)), {});
    Require(bytes.size() >= 12 &&
                std::string(reinterpret_cast<char*>(bytes.data()), 4) == "FTAC",
            "Replay header");
    uint32_t seed;
    memcpy(&seed, bytes.data() + 4, 4);
    unsigned left = bytes[8], right = bytes[9];
    Require(left == 1 && right == 2 && bytes[10] == 1 && bytes[11] == 0,
            "Replay contract");
    fs::NativeReplayPlayer client_replay;
    if (argc == 3) {
      std::ifstream client_stream(argv[2], std::ios::binary);
      Require(bool(client_stream), "Cannot open actual client replay");
      const std::string contents((std::istreambuf_iterator<char>(client_stream)), {});
      Require(client_replay.LoadReplay(contents), "Actual client replay invalid");
      Require(client_replay.contract() == fs::NativeMatchContract(seed, left, right),
              "Actual client replay contract differs");
    }
    GameEnv env;
    env.game_config.render = false;
    env.game_config.physics_steps_per_frame =
        fs::NativeMatchContract::kPhysicsSteps;
    auto scenario =
        fs::MakeNativeMatchScenario(fs::NativeMatchContract(seed, left, right));
    env.start_game(*scenario);
    env.state = game_running;
    auto engine = fs::MakeGameEnvCallbacks(&env);
    auto observe = fs::MakeGameEnvBotObserver(&env, left, right);
    fs::BotTakeoverManager bots(50);
    unsigned frame_count = 0, hashes = 0, notices = 0, bot_frames = 0,
             nonzero = 0, unavailable = 0;
    fs::state_hash_t current_hash = 0;
    for (size_t at = 12; at < bytes.size();) {
      const auto* data = bytes.data() + at;
      const auto remaining = bytes.size() - at;
      size_t used = 0;
      if (data[0] == 10) {
        uint16_t slot;
        fs::frame_id_t frame;
        used = fs::UnpackTakeoverNotify(data, remaining, &slot, &frame);
        Require(used && frame == frame_count && slot < 2,
                "Takeover boundary invalid");
        bots.Takeover(slot, slot < left ? 0 : 1);
        ++notices;
      } else if (data[0] == 3) {
        fs::frame_id_t frame;
        std::vector<fs::SlotInput> inputs;
        used = fs::UnpackAuthoritativeFrame(data, remaining, &frame, &inputs);
        Require(used && frame == frame_count && inputs.size() == 3,
                "Authority sequence changed");
        Require(inputs[2] == fs::SlotInput::Default(),
                "Unreserved slot takeover");
        if (bots.bot_count()) {
          const auto snapshot = observe();
          for (auto slot : bots.GetBotSlots()) {
            const auto expected = bots.GenerateInput(slot, snapshot);
            Require(
                inputs[slot] == expected,
                "Wire bot input differs from real tactical engine decision");
            ++bot_frames;
            nonzero += expected != fs::SlotInput::Default();
            unavailable += (snapshot.unavailable_slots & (1u << slot)) != 0;
          }
        }
        if (argc == 3) {
          const auto recorded = client_replay.GetFrameAt(frame);
          Require(recorded.has_value() && recorded->inputs == inputs,
                  "Actual native client consumed different authoritative inputs");
        }
        engine.step_frame(inputs);
        current_hash = engine.compute_hash();
        if (argc == 3)
          Require(client_replay.GetFrameAt(frame)->state_hash == current_hash,
                  "Actual native client state differs at an authority frame");
        ++frame_count;
      } else if (data[0] == 4) {
        fs::frame_id_t frame;
        fs::state_hash_t hash;
        used = fs::UnpackStateHash(data, remaining, &frame, &hash);
        Require(used && frame + 1 == frame_count, "Hash boundary invalid");
        Require(hash == current_hash,
                "Broadcast input did not reproduce actual authority state");
        ++hashes;
      } else
        throw std::runtime_error("Unknown replay message");
      Require(used > 0 && used <= remaining, "Truncated authority file");
      at += used;
    }
    if (argc == 3)
      Require(client_replay.GetTotalFrames() == frame_count && frame_count >= 260,
              "Actual client did not finish the full takeover replay");
    Require(notices == 1 && bot_frames >= 151 && nonzero >= 10 && hashes >= 15,
            "Insufficient real takeover replay");
    std::cout << "{\"passed\":true,\"assertions\":" << assertions
              << ",\"skipped\":0,\"actual_gameenv\":true,\"frames\":"
              << frame_count << ",\"hashes\":" << hashes
              << ",\"bot_frames\":" << bot_frames << ",\"nonzero\":" << nonzero
              << ",\"unavailable\":" << unavailable << "}\n";
  } catch (const std::exception& e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
