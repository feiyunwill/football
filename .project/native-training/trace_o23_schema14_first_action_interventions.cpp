// Bounded causal first-action intervention helper for rejected Schema14 policies.
#include "training/native_inference.hpp"
#include <fstream>
#include <iostream>
#include <set>
#include <stdexcept>

int main(int argc, char** argv) {
  using namespace football::training;
  namespace inference = football::training::inference;
  try {
    if (argc != 4) throw std::invalid_argument("policy cases selected-index-file");
    inference::PortablePolicy model(argv[1]);
    const auto cases = inference::Cases(inference::Read(argv[2], 128 * 1024));
    std::ifstream selected_file(argv[3]);
    std::set<size_t> selected;
    for (size_t index; selected_file >> index;) {
      if (index >= cases.size()) throw std::invalid_argument("Selected index outside cases");
      if (!selected.insert(index).second) throw std::invalid_argument("Duplicate selected index");
    }
    if (selected.empty()) throw std::invalid_argument("No selected cases");
    NativeTrainingEnv env(160, 90, true, true, false, false);
    for (const auto& c : cases) {
      if (!selected.contains(c.index)) continue;
      for (int forced_action = -1; forced_action < 19; ++forced_action) {
        auto scene = frame_sync::MakeDefaultScenario(1, 0, 42);
        ConfigureTwoOnOne(*scene);
        scene->deterministic = true;
        scene->game_engine_random_seed = c.seed;
        scene->left_team[1] = FormationEntry(c.ax, c.ay, e_PlayerRole_CF, false, true);
        scene->left_team[2] = FormationEntry(c.tx, c.ty, e_PlayerRole_CF, false, true);
        scene->right_team[1] = FormationEntry(c.dx, c.dy, e_PlayerRole_CB, false, false);
        scene->ball_position = blunted::Vector3(c.ax + .02f, c.ay, 0);
        auto observation = env.reset(*scene, 10);
        inference::Episode episode;
        episode.actions.set_state(c.action_seed);
        episode.metrics.observe(env.possession());
        int sampled_first_action = -1;
        while (episode.steps < 256) {
          const auto view = CooperationObservation(observation, episode.metrics.completed_passes > 0,
                                                   env.sticky_actions());
          const auto output = model.policy.forward(view);
          CategoricalDistribution distribution(output.logits, 1, 19);
          const int sampled_action = episode.controller.choose(distribution.probabilities());
          if (episode.steps == 0) sampled_first_action = sampled_action;
          const int applied_action = episode.steps == 0 && forced_action >= 0 ? forced_action : sampled_action;
          episode.metrics.action(env.possession(), applied_action);
          auto transition = env.step(std::array<int, 2>{applied_action, 19});
          episode.metrics.observe(env.possession());
          episode.reward += transition.rewards.front();
          episode.score += transition.score_reward;
          ++episode.steps;
          episode.terminated = transition.terminated;
          observation = std::move(transition.observations);
          if (episode.terminated) break;
        }
        std::cout << "{\"index\":" << c.index << ",\"group\":" << c.group
                  << ",\"forced_first_action\":" << forced_action
                  << ",\"sampled_first_action\":" << sampled_first_action
                  << ",\"applied_first_action\":" << (forced_action < 0 ? sampled_first_action : forced_action)
                  << ",\"steps\":" << episode.steps << ",\"score\":" << episode.score
                  << ",\"pass_requests\":" << episode.metrics.pass_requests
                  << ",\"completed_passes\":" << episode.metrics.completed_passes << "}\n";
      }
    }
    env.close();
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
