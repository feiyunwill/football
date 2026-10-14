// Inference-only native entry point. PPO updates/checkpoints are a separate task.
#include "training/native_policy.hpp"
#include "frame_sync/default_scenario.hpp"
#include <charconv>
#include <cstdio>
#include <stdexcept>
#include <string_view>

uint64_t number(const char* input, uint64_t maximum) {
  uint64_t value = 0;
  std::string_view text(input);
  auto result = std::from_chars(text.data(), text.data() + text.size(), value);
  if (result.ec != std::errc{} || result.ptr != text.data() + text.size() || value > maximum)
    throw std::invalid_argument("Invalid numeric argument");
  return value;
}
int main(int argc, char** argv) {
  try {
    if (argc > 4) throw std::invalid_argument("Usage: native_policy_rollout [seed] [players=1..11] [steps=1..256]");
    const uint64_t seed = argc > 1 ? number(argv[1], UINT64_MAX) : 42;
    const size_t players = argc > 2 ? number(argv[2], 11) : 1;
    const size_t steps = argc > 3 ? number(argv[3], 256) : 128;
    if (players == 0 || steps == 0) throw std::invalid_argument("Players/steps must be positive");
    football::training::PolicySpec spec; spec.players = players;
    football::training::CategoricalPolicy policy(spec, seed);
    football::training::PolicyRng rng(seed ^ UINT64_C(0xd1b54a32d192ed03));
    football::training::NativePolicyEnvironment env(spec);
    auto scenario = frame_sync::MakeDefaultScenario(players, 0, static_cast<unsigned int>(seed % 2000000001));
    env.reset(*scenario, 10);
    double reward = 0;
    size_t frames = 0;
    bool terminal = false, truncated = false;
    while (frames < steps) {
      auto transition = env.step(policy, rng, false, frames + 1 == steps);
      reward += transition.reward;
      ++frames;
      terminal = transition.following.terminated;
      truncated = transition.truncated;
      if (terminal || truncated) break;
    }
    std::printf("{\"mode\":\"categorical_inference_only\",\"seed\":%llu,\"players\":%zu,\"transitions\":%zu,\"reward\":%.17g,\"terminated\":%s,\"truncated\":%s}\n",
                static_cast<unsigned long long>(seed), players, frames, reward,
                terminal ? "true" : "false", truncated ? "true" : "false");
    env.close();
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "%s\n", error.what()); return 1;
  }
}
