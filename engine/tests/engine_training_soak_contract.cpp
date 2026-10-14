// 2026-10-14: long replay, repeated reset/restore and bounded resident resources.
#include "training/native_training.hpp"
#include "frame_sync/default_scenario.hpp"
#include <fstream>
#include <filesystem>
#include <cstdio>
#include <unistd.h>
namespace ft = football::training;
void require(bool valid) { if (!valid) throw std::runtime_error("Training soak contract failed"); }
long rss() {
  std::ifstream status("/proc/self/statm"); long pages, resident;
  require(bool(status >> pages >> resident));
  return resident * sysconf(_SC_PAGESIZE);
}
size_t descriptors() {
  size_t count = 0;
  for (const auto& entry : std::filesystem::directory_iterator("/proc/self/fd")) { (void)entry; ++count; }
  return count;
}
int main(int, char**) {
  try {
    size_t transitions = 0, resets = 0, restores = 0, hashes = 0;
    long minimum = 0, maximum = 0;
    size_t baseline_fds = 0;
    for (int test = 0; test < 6; ++test) {
      const int players = test % 3 == 0 ? 11 : test % 3 == 1 ? 1 : 2;
      const bool right = test >= 3;
      auto scene = frame_sync::MakeDefaultScenario(right ? 0 : players, right ? players : 0, 42 + test);
      // Three different formation shapes, not just seed changes.
      if (players != 11) {
        scene->left_team.resize(test % 3 == 1 ? 3 : 5);
        scene->right_team.resize(test % 3 == 1 ? 2 : 4);
      }
      scene->game_duration = 1400;
      ft::NativeTrainingEnv control(160, 90, true, test % 2, true, true);
      ft::NativeTrainingEnv replay(160, 90, true, test % 2, true, true);
      const int cadence = test % 2 ? 10 : 2;
      control.reset(*scene, cadence); replay.reset(*scene, cadence); resets += 2;
      for (int block = 0; block < 4; ++block) {
        auto saved = control.get_state();
        for (int wrong = 0; wrong < 3; ++wrong)
          if (replay.step(std::vector<int>(players, 5)).terminated) break;
        replay.set_state(saved); ++restores;
        for (int frame = 0; frame < 256; ++frame) {
          std::vector<int> actions(players);
          for (int player = 0; player < players; ++player) actions[player] = (frame + block * 3 + player) % 20;
          auto a = control.step(actions); auto b = replay.step(actions);
          require(a.observations == b.observations && a.rewards == b.rewards &&
                  a.score_reward == b.score_reward && a.terminated == b.terminated);
          ++transitions;
          if (frame % 16 == 0 || a.terminated) {
            require(control.get_state_digest() == replay.get_state_digest()); ++hashes;
          }
          if (a.terminated) { control.reset(*scene, cadence); replay.reset(*scene, cadence); resets += 2; }
        }
      }
      control.close(); replay.close();
      require(control.is_closed() && replay.is_closed());
      const auto current = rss();
      if (test == 0) { minimum = maximum = current; baseline_fds = descriptors(); }
      else { minimum = std::min(minimum, current); maximum = std::max(maximum, current); }
      require(descriptors() == baseline_fds);
    }
    // Warm allocator retention is bounded separately from sanitizer leak detection.
    require(maximum - minimum <= 64L * 1024 * 1024);
    std::printf("Training soak passed: transitions=%zu restores=%zu resets=%zu hashes=%zu rss_min=%ld rss_max=%ld fds=%zu\n",
                transitions, restores, resets, hashes, minimum, maximum, baseline_fds);
    return 0;
  } catch (const std::exception& error) { std::fprintf(stderr, "%s\n", error.what()); return 1; }
}
