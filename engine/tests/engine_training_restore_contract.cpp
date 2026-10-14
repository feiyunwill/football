// 2026-10-14: real kernel + reward/history transactional replay contract.
#include "training/native_training.hpp"
#include "training/training_snapshot.hpp"
#include "training/snapshot_identity.hpp"
#include "frame_sync/default_scenario.hpp"
#include <array>
#include <cstdio>
#include <functional>
#include <source_location>
#include <filesystem>
#include <fstream>
#include <chrono>
#include <cstdlib>
namespace ft = football::training;
namespace ts = ft::snapshot;
namespace ks = blunted::snapshot;
void require(bool condition, std::source_location where = std::source_location::current()) {
  if (!condition) throw std::runtime_error("Training restore contract failed at line " + std::to_string(where.line()));
}
void reject(const std::function<void()>& operation) {
  try { operation(); } catch (const std::invalid_argument&) { return; }
  throw std::runtime_error("Invalid training restore was accepted");
}
void equal(const ft::TrainingTransition& a, const ft::TrainingTransition& b) {
  require(a.observations == b.observations && a.rewards == b.rewards &&
          a.terminated == b.terminated && a.score_reward == b.score_reward);
}
int main(int, char**) {
  try {
    ft::NativeTrainingEnv fresh(160, 90);
    try { fresh.get_state(); throw std::runtime_error("Unreset environment saved"); }
    catch (const std::logic_error&) {}
    for (bool right : {false, true}) for (bool fixed : {false, true})
      for (bool checkpoint : {false, true}) for (bool stack : {false, true}) {
        auto scenario = frame_sync::MakeDefaultScenario(right ? 0 : 2, right ? 2 : 0, 43);
        scenario->game_duration = 12;
        ft::NativeTrainingEnv env(160, 90, false, fixed, checkpoint, stack);
        ft::NativeTrainingEnv target(160, 90, false, fixed, checkpoint, stack);
        env.reset(*scenario, 10); target.reset(*scenario, 10);
        env.step(std::array<int, 2>{13, 1});
        env.step(std::array<int, 2>{5, 8});
        const auto saved = env.get_state();
        const auto initial_digest = env.get_state_digest();
        target.set_state(saved);
        require(target.get_state_digest() == initial_digest);
        std::vector<ft::TrainingTransition> expected;
        for (int i = 0; i < 32; ++i) {
          auto a = env.step(std::array<int, 2>{i % 19, (i + 4) % 19});
          auto b = target.step(std::array<int, 2>{i % 19, (i + 4) % 19});
          equal(a, b);
          require(env.get_state_digest() == target.get_state_digest());
          expected.push_back(std::move(a));
          if (expected.back().terminated) break;
        }
        require(expected.back().terminated);
        const auto terminal = env.get_state();
        target.set_state(terminal);
        require(!ts::Decode(terminal).ready);
        try { target.step(std::array<int, 2>{0, 0}); throw std::runtime_error("Terminal snapshot resumed"); }
        catch (const std::logic_error&) {}
        target.set_state(saved); // live snapshot can resume a normally finished target
        std::vector<int> actions;
        for (int i = 0; i < 32; ++i) { actions.push_back(i % 19); actions.push_back((i + 4) % 19); }
        auto batch = target.step_many(actions, 32);
        require(batch.terminated.size() == expected.size());
        for (size_t i = 0; i < expected.size(); ++i) {
          require(batch.terminated[i] == expected[i].terminated && batch.score_rewards[i] == expected[i].score_reward);
          for (size_t player = 0; player < 2; ++player) {
            require(std::ranges::equal(batch.observations[i * 2 + player], expected[i].observations[player]));
            require(batch.rewards[i * 2 + player] == expected[i].rewards[player]);
          }
        }
        require(env.get_state_digest() == target.get_state_digest());
      }

    // Independent full-capacity/default-v2 action cases, not only two-player replay.
    for (int players : {1, 11}) {
      auto sc = frame_sync::MakeDefaultScenario(players, 0, 44);
      ft::NativeTrainingEnv a(160, 90, true, true, true, true);
      ft::NativeTrainingEnv b(160, 90, true, true, true, true);
      a.reset(*sc, 3); b.reset(*sc, 3);
      a.step(std::vector<int>(players, 19));
      const auto saved = a.get_state(); b.set_state(saved);
      for (int frame = 0; frame < 8; ++frame) {
        equal(a.step(std::vector<int>(players, frame)), b.step(std::vector<int>(players, frame)));
        require(a.get_state_digest() == b.get_state_digest());
      }
    }
    for (bool goal : {false, true}) {
      auto sc = frame_sync::MakeDefaultScenario(1, 0, 46);
      sc->offsides = false; sc->reverse_team_processing = false;
      sc->game_duration = 400; sc->end_episode_on_score = goal;
      sc->ball_position = blunted::Vector3(goal ? 0.98f : 0.4f, 0, 0);
      sc->left_team = {FormationEntry(-1, 0, e_PlayerRole_GK, true, true),
                      FormationEntry(goal ? 0.96f : 0.38f, 0, e_PlayerRole_CF, true, true)};
      sc->right_team = {FormationEntry(0.5f, 0.3f, e_PlayerRole_GK, true, true)};
      ft::NativeTrainingEnv a(160, 90, false, true, true, true);
      ft::NativeTrainingEnv b(160, 90, false, true, true, true);
      a.reset(*sc, 10); b.reset(*sc, 10);
      if (!goal) {
        bool collected = false;
        for (int frame = 0; frame < 30 && !collected; ++frame)
          collected = a.step(std::array<int, 1>{5}).rewards[0] > 0;
        require(collected);
        auto counts = ts::Decode(a.get_state()).checkpoints;
        require(counts.size() == 1 && counts[0] > 0 && counts[0] < 10);
      }
      const auto saved = a.get_state(); b.set_state(saved);
      int score = 0;
      for (int frame = 0; frame < (goal ? 120 : 12); ++frame) {
        const std::array<int, 1> action{goal && frame % 5 == 0 ? 12 : 5};
        auto x = a.step(action); auto y = b.step(action);
        equal(x, y); score += x.score_reward;
        require(a.get_state_digest() == b.get_state_digest());
        if (x.terminated) break;
      }
      if (goal) {
        require(score == 1);
        require(ts::Decode(a.get_state()).checkpoints[0] == 10);
      }
    }

    auto scenario = frame_sync::MakeDefaultScenario(2, 0, 42);
    scenario->game_duration = 32;
    ft::NativeTrainingEnv env(160, 90, false, true, true, true);
    env.reset(*scenario, 10);
    for (int i = 0; i < 5; ++i) env.step(std::array<int, 2>{13, 5});
    const auto original = env.get_state();
    const auto original_state = ts::Decode(original);
    const auto digest = env.get_state_digest();
    auto unchanged = [&] {
      require(env.get_state_digest() == digest);
      auto state = ts::Decode(env.get_state());
      auto prior = original_state;
      state.kernel.clear(); prior.kernel.clear();
      require(state == prior);
    };
    auto reject_state = [&](ts::State state) {
      reject([&] { env.set_state(ts::Encode(state)); }); unchanged();
    };
    auto bad = original_state; bad.compatibility[0] ^= 1; reject_state(bad);
    // Correct envelopes must not admit impossible restart bookkeeping.
    for (uint32_t waiting : {0xffffffffu, 1u, 0x7fffffffu}) {
      bad = original_state;
      auto waiting_payload = std::string(ks::Decode(bad.kernel));
      // Empty external-state length, GameState, then waiting_for_game_count.
      ks::Write32(waiting_payload, 8, waiting);
      bad.kernel = ks::Encode(waiting_payload);
      reject_state(bad);
    }
    bad = original_state; bad.scenario[0] ^= 1; reject_state(bad);
    bad = original_state; bad.physics_steps = 20; reject_state(bad);
    bad = original_state; bad.builtin_ai_action = true; reject_state(bad);
    bad = original_state; bad.fixed_positions = false; reject_state(bad);
    // These pass admission and restore the kernel before failing postconditions.
    bad = original_state; ++bad.previous_score_diff; reject_state(bad);
    bad = original_state; bad.ready = false; reject_state(bad);
    bad = original_state; bad.history.back() += 1.0f; reject_state(bad);
    bad = original_state;
    bad.kernel = ks::Encode(std::string(ks::Decode(bad.kernel).substr(0, 100)));
    reject_state(bad); // partial RNG/state decode must roll back
    bad = original_state;
    auto payload = std::string(ks::Decode(bad.kernel));
    ks::Write32(payload, 0, 1); payload.insert(4, 1, 'x');
    bad.kernel = ks::Encode(payload); reject_state(bad); // unexpected external/pickle bytes
    reject([&] { env.set_state(std::string_view(original).substr(0, original.size() - 1)); }); unchanged();
    reject([&] { env.set_state(std::string(ts::kMaxBytes + 1, 'x')); }); unchanged();
    ft::NativeTrainingEnv different_dimensions(161, 90, false, true, true, true);
    different_dimensions.reset(*scenario, 10);
    reject([&] { different_dimensions.set_state(original); });
    auto altered = *scenario; altered.game_engine_random_seed = 43;
    ft::NativeTrainingEnv different_scene(160, 90, false, true, true, true);
    different_scene.reset(altered, 10);
    reject([&] { different_scene.set_state(original); });
    // Subsequent transitions prove rejected input did not merely preserve a digest.
    ft::NativeTrainingEnv control(160, 90, false, true, true, true);
    control.reset(*scenario, 10); control.set_state(original);
    for (int i = 0; i < 12; ++i) {
      equal(env.step(std::array<int, 2>{i % 19, 0}), control.step(std::array<int, 2>{i % 19, 0}));
      require(env.get_state_digest() == control.get_state_digest());
    }
    env.close();
    try { env.set_state(original); throw std::runtime_error("Closed environment restored"); }
    catch (const std::logic_error&) {}
    // Resource validation uses a private symlink dataset, never edits repository assets.
    namespace fs = std::filesystem;
    const auto* configured_resources = std::getenv("GFOOTBALL_DATA_DIR");
    require(configured_resources != nullptr);
    const auto resources = fs::absolute(configured_resources);
    const auto temporary = fs::temp_directory_path() / ("football-snapshot-resources-" +
        std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    require(fs::create_directory(temporary));
    struct Cleanup { fs::path path; ~Cleanup() { std::error_code error; fs::remove_all(path, error); } } cleanup{temporary};
    GameEnv probe;
    probe.game_config.data_dir = resources.string();
    const auto compatibility = ft::TrainingCompatibility(probe);
    probe.game_config.data_dir = temporary.string();
    reject([&] { (void)ft::TrainingCompatibility(probe); });
    fs::path first_file;
    for (const auto& entry : fs::recursive_directory_iterator(resources)) {
      const auto relative = entry.path().lexically_relative(resources);
      if (entry.is_directory()) fs::create_directories(temporary / relative);
      else if (entry.is_regular_file()) {
        fs::create_directories((temporary / relative).parent_path());
        fs::create_symlink(entry.path(), temporary / relative);
        if (first_file.empty()) first_file = relative;
      }
    }
    require(ft::TrainingCompatibility(probe) == compatibility);
    { std::ofstream added(temporary / "extra-resource"); added << "added"; }
    reject([&] { (void)ft::TrainingCompatibility(probe); });
    fs::remove(temporary / "extra-resource");
    require(!first_file.empty());
    fs::remove(temporary / first_file); // unlink private symlink before writing replacement
    { std::ofstream changed(temporary / first_file); changed << "different-resource-bytes"; }
    reject([&] { (void)ft::TrainingCompatibility(probe); });
    std::puts("Training restore: 16 replay configurations, 1/11 agents, nonzero checkpoints, goal, terminal/batch, rollback and resource identity passed");
    return 0;
  } catch (const std::exception& error) { std::fprintf(stderr, "%s\n", error.what()); return 1; }
}
