// 2026-09-09: adversarial snapshots and real rendering/simulation boundaries.
#include "base/snapshot_envelope.hpp"
#include "frame_sync/default_scenario.hpp"
#include "frame_sync/state_hash.hpp"
#include "game_env.hpp"
#include "onthepitch/ecs_systems.hpp"

#include <climits>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

namespace {
int assertions = 0;
void Require(bool condition, const std::string& message) {
  ++assertions;
  if (!condition) throw std::runtime_error(message);
}
template<class Action> void Reject(Action action, const std::string& message) {
  bool rejected = false;
  try { action(); } catch (const std::invalid_argument&) { rejected = true; }
  Require(rejected, message);
}
template<class T> std::string Bytes(T value) {
  return std::string(reinterpret_cast<const char*>(&value), sizeof(value));
}
void Start(GameEnv& environment, uint32_t seed, bool reverse, bool render = false) {
  environment.game_config.render = render;
  environment.game_config.render_resolution_x = 320;
  environment.game_config.render_resolution_y = 180;
  auto scenario = frame_sync::MakeDefaultScenario(1, 1, seed);
  scenario->reverse_team_processing = reverse;
  environment.start_game(*scenario);
  environment.state = game_running;
}
void Step(GameEnv& environment, int frame) {
  environment.action(frame % 2 ? game_left : game_right, true, 0);
  environment.step();
}

void ReaderBounds() {
  GameEnv environment;
  for (int count : {-1, INT_MIN, INT_MAX, 16385}) {
    auto bytes = Bytes(count);
    EnvState reader(&environment, bytes);
    std::vector<int> values{1, 2, 3};
    Reject([&] { reader.process(values); }, "Invalid vector count accepted");
    Require(values == std::vector<int>({1, 2, 3}), "Rejected size mutated the vector");
  }
  for (int index : {-2, INT_MIN, 0, INT_MAX}) {
    EnvState reader(&environment, Bytes(index));
    Player* player = nullptr;
    reader.SetPlayers({});
    Reject([&] { reader.process(player); }, "Out-of-range object reference accepted");
  }
  for (unsigned char invalid : {2, 127, 255}) {
    EnvState reader(&environment, Bytes(invalid));
    bool value = true;
    Reject([&] { reader.process(value); }, "Noncanonical bool accepted");
    Require(value, "Rejected boolean changed destination");
  }
  for (float invalid : {std::numeric_limits<float>::infinity(), std::numeric_limits<float>::quiet_NaN()}) {
    EnvState reader(&environment, Bytes(invalid));
    float value = 1;
    Reject([&] { reader.process(value); }, "Non-finite scalar accepted");
    Require(value == 1, "Rejected float changed destination");
  }
  // 2026-09-09: game_paused is now a valid lifecycle value.
  // for (int invalid : {-1, 4, INT_MAX}) {
  for (int invalid : {-1, int(game_paused) + 1, INT_MAX}) {
    EnvState reader(&environment, Bytes(invalid));
    GameState value = game_running;
    Reject([&] { reader.process(value); }, "Out-of-domain enum accepted");
    Require(value == game_running, "Rejected enum changed destination");
  }
  EnvState reference(&environment, "", "x");
  int value = 1;
  Reject([&] { reference.process(value); }, "Truncated diagnostic reference accepted");
  Require(blunted::snapshot::Checksum("123456789") == 0xcbf43926u, "CRC32 known-answer mismatch");
}

void SnapshotTransaction(uint32_t seed, bool reverse) {
  GameEnv environment;
  Start(environment, seed, reverse);
  for (int frame = 0; frame < 20; ++frame) Step(environment, frame);
  const auto saved = environment.get_state("");
  const auto before = environment.get_state_digest();
  const std::string payload(blunted::snapshot::Decode(saved));
  auto unchanged = [&](const std::string& invalid, const std::string& label) {
    Reject([&] { environment.set_state(invalid); }, label);
    Require(environment.context != nullptr, label + ": recovery closed a valid game");
    Require(environment.get_state_digest() == before, label + ": failed restore changed game state");
    Require(GetGame() == nullptr, label + ": leaked context selection");
  };
  unchanged("", "empty input");
  unchanged(saved.substr(0, 8), "short header");
  unchanged(payload, "legacy/unversioned input");
  for (size_t offset : {size_t(0), size_t(4), size_t(8), size_t(12), size_t(20), saved.size() - 1}) {
    auto corrupted = saved;
    corrupted[offset] ^= 0x40;
    unchanged(corrupted, "envelope corruption at " + std::to_string(offset));
  }
  // Recompute the checksum so tests reach the parser and transaction cleanup.
  for (size_t offset = 1; offset < payload.size(); offset += 997)
    unchanged(blunted::snapshot::Encode(payload.substr(0, offset)), "deep truncation at " + std::to_string(offset));
  for (size_t removed = 1; removed <= 96; ++removed)
    unchanged(blunted::snapshot::Encode(payload.substr(0, payload.size() - removed)), "late truncation " + std::to_string(removed));
  unchanged(blunted::snapshot::Encode(payload + "trailing"), "trailing payload");
  auto invalid_state = payload;
  invalid_state.replace(4, sizeof(int), Bytes(INT_MAX));
  unchanged(blunted::snapshot::Encode(invalid_state), "invalid lifecycle enum");
  auto invalid_rng = payload;
  invalid_rng.replace(12, GameContext::BaseGenerator::state_size * 4,
                      GameContext::BaseGenerator::state_size * 4, '\0');
  unchanged(blunted::snapshot::Encode(invalid_rng), "all-zero random generator");
  size_t match_offset = 0;
  {
    ContextHolder context(&environment);
    EnvState prefix(&environment, "");
    std::string metadata;
    prefix.process(metadata);
    prefix.process(environment.state);
    prefix.process(environment.waiting_for_game_count);
    environment.context->ProcessState(&prefix);
    match_offset = prefix.getpos();
  }
  for (int invalid : {-2, -1, 2, INT_MAX}) {
    auto corrupted = payload;
    corrupted.replace(match_offset, sizeof(int), Bytes(invalid));
    unchanged(blunted::snapshot::Encode(corrupted), "invalid processing team");
  }
  // first/second team + history count + timestamp/deviation + player count +
  // three vectors precede the first player reference in a populated history.
  const size_t first_player_reference = match_offset + 8 + 4 + 12 + 4 + 36;
  for (int invalid : {-2, -1, INT_MAX}) {
    auto corrupted = payload;
    corrupted.replace(first_player_reference, sizeof(int), Bytes(invalid));
    unchanged(blunted::snapshot::Encode(corrupted), "invalid historical player reference");
  }
  for (int frame = 20; frame < 50; ++frame) Step(environment, frame);
  const auto expected = environment.get_state_digest();
  Require(environment.set_state(saved).empty(), "Snapshot metadata roundtrip failed");
  for (int frame = 20; frame < 50; ++frame) Step(environment, frame);
  Require(environment.get_state_digest() == expected, "Failed snapshot reads changed subsequent simulation");
  std::cout << "{\"passed\":true,\"assertions\":" << assertions
            << ",\"skipped\":0,\"snapshot_bytes\":" << saved.size()
            << ",\"collision_workspace\":true"
            << ",\"seed\":" << seed << ",\"reverse\":" << (reverse ? "true" : "false") << "}" << std::endl;
}

void RenderingBoundary(uint32_t seed) {
  GameEnv headless, graphical;
  Start(headless, seed, false);
  Start(graphical, seed, false, true);
  for (int frame = 0; frame < 30; ++frame) {
    Step(headless, frame);
    Step(graphical, frame);
    const auto digest = graphical.get_state_digest();
    Require(headless.get_state_digest() == digest, "Rendering changed simulation results");
    if (frame == 14) {
      Require(graphical.set_state(headless.get_state("render-transfer")) == "render-transfer",
              "Snapshot transfer between headless/graphical environments failed");
      Require(graphical.get_state_digest() == digest, "Graphical snapshot restore changed logic");
    }
    const auto step = graphical.get_info().step;
    graphical.render(false);
    graphical.render(false);
    Require(graphical.get_info().step == step && graphical.get_state_digest() == digest,
            "Repeated render advanced logic or changed state");
    Require(graphical.get_frame().size() == 320 * 180 * 3, "Rendering boundary did not produce a frame");
  }
  std::cout << "{\"passed\":true,\"assertions\":" << assertions << ",\"skipped\":0}" << std::endl;
}

// 2026-09-13: real collision calls after roster shrink/growth and snapshot
// restoration must behave like a fresh environment, regardless of prior buffer
// capacities. Zero/one player cases exercise the collision boundary directly;
// they do not claim that an empty team is a playable match configuration.
void CollisionWorkspace(uint32_t seed, bool reverse) {
  GameEnv reused;
  Start(reused, seed, reverse);
  for (int frame = 0; frame < 20; ++frame) Step(reused, frame);
  const auto saved = reused.get_state("");

  auto arrange = [&](GameEnv& environment, size_t count) {
    ContextHolder context(&environment);
    Match* match = environment.context->gameTask->GetMatch();
    std::vector<Player*> players;
    match->GetTeam(0)->GetActivePlayers(players);
    match->GetTeam(1)->GetActivePlayers(players);
    Require(players.size() == 22, "Restored collision roster is incomplete");
    for (size_t index = 0; index < players.size(); ++index) {
      if (index >= count) {
        // Bypass team-selection policy only for this isolated system fixture.
        players[index]->PlayerBase::Deactivate();
      } else {
        const Vector3 target(float(index % 5) * 0.4f,
                             float(index / 5) * 0.4f, 0.0f);
        players[index]->OffsetPosition(target - players[index]->GetPosition());
      }
    }
    Require(match->GetTeam(0)->GetActivePlayersCount() +
                match->GetTeam(1)->GetActivePlayersCount() == count,
            "Collision fixture has the wrong active roster");
  };
  auto collide = [&](GameEnv& environment) {
    ContextHolder context(&environment);
    HumanoidCollisionSystemProcess(environment.context->gameTask->GetMatch());
  };

  for (const size_t count : {22u, 2u, 11u, 1u, 0u, 22u}) {
    GameEnv fresh;
    Start(fresh, seed, reverse);
    reused.set_state(saved);
    fresh.set_state(saved);
    arrange(reused, count);
    arrange(fresh, count);
    const auto before = reused.get_state_digest();
    Require(before == fresh.get_state_digest(), "Collision fixtures differ");
    for (int tick = 0; tick < 3; ++tick) {
      collide(reused);
      collide(fresh);
      Require(reused.get_state_digest() == fresh.get_state_digest(),
              "Collision result depends on previous workspace contents");
      Require(GetGame() == nullptr, "Collision fixture leaked its context");
    }
    if (count >= 2)
      Require(reused.get_state_digest() != before,
              "Crowded collision fixture did not exercise contact response");
    else
      Require(reused.get_state_digest() == before,
              "Zero/one-player collision boundary changed authoritative state");
  }
  // Restore the original playable state after empty-roster calls and compare
  // subsequent normal simulation to a newly constructed match.
  GameEnv fresh;
  Start(fresh, seed, reverse);
  reused.set_state(saved);
  fresh.set_state(saved);
  for (int frame = 20; frame < 50; ++frame) {
    Step(reused, frame);
    Step(fresh, frame);
    Require(reused.get_state_digest() == fresh.get_state_digest(),
            "Workspace history changed normal simulation after restore");
  }
}
}  // namespace

int main(int argc, char** argv) {
  try {
    const auto seed = argc > 1 ? static_cast<uint32_t>(std::stoul(argv[1])) : 42u;
    if (argc > 2 && std::string(argv[2]) == "--render") RenderingBoundary(seed);
    else if (argc > 2 && std::string(argv[2]) == "--collision") {
      CollisionWorkspace(seed, bool(seed % 2));
      std::cout << "{\"passed\":true,\"assertions\":" << assertions
                << ",\"skipped\":0,\"collision_workspace\":true}" << std::endl;
    }
    else {
      CollisionWorkspace(seed, argc > 2 && std::string(argv[2]) == "--reverse");
      ReaderBounds();
      SnapshotTransaction(seed, argc > 2 && std::string(argv[2]) == "--reverse");
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Simulation contract: " << error.what() << std::endl;
    return 1;
  }
}
