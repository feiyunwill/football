#include "training/native_policy.hpp"
#include "frame_sync/default_scenario.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <limits>
#include <stdexcept>
#if !defined(_WIN32)
#include <sys/wait.h>
#include <unistd.h>
#endif

using namespace football::training;
void require(bool value) { if (!value) throw std::runtime_error("Native policy contract failed"); }
int main(int, char**) {
  try {
    size_t cases = 0, transitions = 0;
    for (size_t players : {size_t{1}, size_t{11}})
      for (bool right : {false, true})
        for (bool v2 : {false, true})
          for (bool fixed : {false, true})
            for (bool stacked : {false, true}) {
              PolicySpec spec{players, stacked ? size_t{460} : size_t{115}, 8, fixed, v2};
              CategoricalPolicy policy(spec, 42);
              PolicyRng sampling(17), reference(17);
              NativePolicyEnvironment env(spec, true);
              NativeTrainingEnv direct(160, 90, v2, fixed, true, stacked);
              auto scenario = frame_sync::MakeDefaultScenario(right ? 0 : players, right ? players : 0, 42);
              scenario->game_duration = 8;
              auto initial = env.reset(*scenario, 10);
              require(initial == direct.reset(*scenario, 10));
              require(!env.needs_reset());
              const auto origin = env.kernel_state();
              auto wrong = spec; wrong.fixed_positions = !fixed;
              try { env.step(CategoricalPolicy(wrong, 0), sampling); require(false); }
              catch (const std::invalid_argument&) {}
              require(env.kernel_state() == origin && sampling.state() == reference.state());
              auto invalid = *scenario; invalid.left_agents = 12;
              try { env.reset(invalid, 10); require(false); }
              catch (const std::invalid_argument&) {}
              require(env.kernel_state() == origin);
              bool terminal = false;
              for (int frame = 0; frame < 64; ++frame) {
                const auto before = env.observation();
                const auto expected = policy.decide(before, reference);
                auto actual = env.step(policy, sampling);
                auto following = direct.step(expected.actions);
                require(actual.observation == before && actual.decision.actions == expected.actions);
                require(actual.decision.log_probability == expected.log_probability &&
                        actual.decision.entropy == expected.entropy && actual.decision.value == expected.value);
                require(actual.following.observations == following.observations && actual.following.rewards == following.rewards &&
                        actual.following.terminated == following.terminated && actual.following.score_reward == following.score_reward);
                require(env.kernel_state() == direct.get_state_digest() && sampling.state() == reference.state());
                double sum = 0; for (float reward : following.rewards) sum += reward;
                require(actual.reward == sum / players && !actual.truncated);
                ++transitions;
                terminal = actual.following.terminated;
                if (terminal) break;
              }
              require(terminal && env.needs_reset());
              const auto final_rng = sampling.state();
              try { env.step(policy, sampling); require(false); } catch (const std::logic_error&) {}
              require(final_rng == sampling.state());
              scenario->game_duration = 1000;
              env.reset(*scenario, 10);
              auto truncated = env.step(policy, sampling, false, true);
              require(truncated.truncated && !truncated.following.terminated && env.needs_reset());
              env.close(); env.close();
              ++cases;
            }
    PolicySpec spec;
    CategoricalPolicy policy(spec, 0);
    PolicyRng rng(0);
    NativePolicyEnvironment env(spec);
    auto scenario = frame_sync::MakeDefaultScenario(1, 0, 42);
    env.reset(*scenario);
    const auto origin = env.kernel_state();
    auto enormous = policy.parameters();
    std::fill(enormous.begin(), enormous.end(), std::numeric_limits<double>::max());
    CategoricalPolicy broken(spec, 0);
    broken.set_parameters(enormous);
    const auto rng_origin = rng.state();
    try { env.step(broken, rng); require(false); } catch (const std::invalid_argument&) {}
    require(env.kernel_state() == origin && rng.state() == rng_origin && !env.needs_reset());
    bool rejected = false;
    std::thread other([&] { try { env.step(policy, rng); } catch (const std::logic_error&) { rejected = true; } });
    other.join(); require(rejected && env.kernel_state() == origin);
#if !defined(_WIN32)
    const pid_t child = fork();
    if (child < 0) throw std::runtime_error("fork failed");
    if (child == 0) {
      try { env.step(policy, rng); } catch (const std::logic_error&) { _exit(0); }
      _exit(1);
    }
    int status = 0;
    require(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0);
    require(env.kernel_state() == origin);
#endif
    env.close();
    std::printf("{\"passed\":true,\"cases\":%zu,\"transitions\":%zu}\n", cases, transitions);
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "%s\n", error.what()); return 1;
  }
}
