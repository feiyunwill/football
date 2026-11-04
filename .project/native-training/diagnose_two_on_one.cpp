// Validation-only interventions; these rollouts are not learning acceptance.
#include "training/ppo_evaluation.hpp"
#include "frame_sync/default_scenario.hpp"
#include <cstdio>
#include <string>
using namespace football::training;
int main(int argc,char** argv) {
  try {
    if(argc!=3) return 2;
    PpoLearnerConfig config;config.seed=7;config.policy.hidden=64;
    config.parameters.epochs=4;config.parameters.minibatch=64;
    config.checkpoint_rewards=std::string(argv[2])=="1";
    config.scenario=frame_sync::MakeDefaultScenario(1,0,42);ConfigureTwoOnOne(*config.scenario);
    config.scenario->deterministic=true;config.scenario_variation=PpoScenarioVariation::TwoOnOne;
    PpoLearner learner(config);learner.load(argv[1]);const auto state=learner.get_state();
    PolicyRng starts(88173^UINT64_C(0x243f6a8885a308d3));
    auto seed=uint32_t(starts.index(2000000001));
    for(int mode=0;mode<4;++mode) {
      auto scene=*config.scenario;scene.game_engine_random_seed=seed;
      ApplyPpoStart(scene,PpoScenarioVariation::TwoOnOne,seed,StartPartition::Validation);
      if(mode==3) scene.ball_position=blunted::Vector3(scene.ball_position.coords[0]+.12f,
                                                    scene.ball_position.coords[1]<=0 ? .18f : -.18f,0);
      NativeTrainingEnv env(160,90,true,true,config.checkpoint_rewards,false);
      auto observed=env.reset(scene,10);CooperationMetrics metrics;metrics.observe(env.possession());
      PolicyRng actions(88173^UINT64_C(0x13198a2e03707344));int goals=0;size_t steps=0;
      for(;steps<256;++steps) {
        auto before=env.possession();const bool phase=mode>=2 || metrics.completed_passes>0;
        auto input=CooperationObservation(observed,phase,env.sticky_actions());auto output=learner.policy().forward(input);
        CategoricalDistribution distribution(output.logits,1,19);
        auto decision=learner.policy().decide(input,actions,false);
        int action=decision.actions[0];
        if(mode==1 && !metrics.completed_passes && before.team==0 && before.player==1) action=11;
        metrics.action(before,action);auto transition=env.step(std::vector<int>{action,19});
        auto after=env.possession();metrics.observe(after);goals+=transition.score_reward;
        if(steps<24 || before.team!=after.team || before.player!=after.player || transition.score_reward)
          std::printf("{\"mode\":%d,\"step\":%zu,\"phase\":%d,\"action\":%d,\"owner_before\":[%d,%d],\"owner_after\":[%d,%d],\"passes\":%zu,\"p_pass\":%.17g,\"p_shot\":%.17g,\"value\":%.17g,\"ball\":[%.9g,%.9g],\"controlled\":[%.9g,%.9g]}\n",
              mode,steps,int(phase),action,before.team,before.player,after.team,after.player,metrics.completed_passes,
              distribution.probabilities()[9]+distribution.probabilities()[10]+distribution.probabilities()[11],
              distribution.probabilities()[12],output.value,observed.buffer()[88],observed.buffer()[89],observed.buffer()[2],observed.buffer()[3]);
        observed=std::move(transition.observations);if(transition.terminated) {++steps;break;}
      }
      std::printf("{\"summary\":true,\"mode\":%d,\"seed\":%u,\"steps\":%zu,\"goals\":%d,\"passes\":%zu}\n",mode,seed,steps,goals,metrics.completed_passes);
    }
    if(learner.get_state()!=state) throw std::runtime_error("Diagnostic changed learner");
    return 0;
  } catch(const std::exception& error) {std::fprintf(stderr,"%s\n",error.what());return 1;}
}
