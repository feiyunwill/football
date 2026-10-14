#include "training/ppo_math.hpp"
#include <array>
#include <cmath>
#include <cstdio>
#include <stdexcept>
using namespace football::training;
void require(bool value) { if (!value) throw std::runtime_error("PPO math contract failed"); }
template<class F> void rejects(F value) { try { value(); } catch (const std::invalid_argument&) { return; } require(false); }
void array(std::span<const double> values) {
  std::printf("["); for (size_t i=0; i<values.size(); ++i) std::printf("%s%.17g", i ? "," : "", values[i]); std::printf("]");
}
int main() {
  try {
    PolicySpec spec{2,115,2,true,false}; CategoricalPolicy policy(spec,7);
    auto weights = policy.parameters();
    for (size_t i=0; i<weights.size(); ++i) weights[i] = (int(i%7)-3)*.01;
    policy.set_parameters(weights);
    PpoSample sample; sample.observation = ObservationBuffer(2); sample.actions = {3,7}; sample.target = .7;
    for (size_t i=0; i<sample.observation.buffer().size(); ++i) sample.observation.buffer()[i] = (int(i%9)-4)*.03f;
    auto output = policy.forward(sample.observation);
    CategoricalDistribution distribution(output.logits,2,19);
    sample.old_value = output.value;
    PpoParameters parameters;
    std::printf("{\"parameters\":"); array(weights);
    std::printf(",\"input\":[");
    for (size_t i=0; i<sample.observation.buffer().size(); ++i)
      std::printf("%s%.9g", i ? "," : "", double(sample.observation.buffer()[i]));
    std::printf("],\"fixtures\":[");
    const std::array<double,5> ratios{1,1.4,.7,1.4,.7}, advantages{1.25,1.25,-1.25,-1.25,1.25};
    double worst_error=0;
    for (size_t fixture=0; fixture<ratios.size(); ++fixture) {
      sample.old_log_probability = distribution.log_probability(sample.actions)-std::log(ratios[fixture]);
      sample.advantage = advantages[fixture];
      auto gradient = LossGradient(policy,sample,parameters);
      for (size_t i=0; i<weights.size(); ++i) {
        auto plus_weights=weights, minus_weights=weights; plus_weights[i]+=1e-6; minus_weights[i]-=1e-6;
        CategoricalPolicy plus=policy, minus=policy; plus.set_parameters(plus_weights); minus.set_parameters(minus_weights);
        const double numerical=(LossGradient(plus,sample,parameters).loss-LossGradient(minus,sample,parameters).loss)/2e-6;
        worst_error=std::max(worst_error,std::abs(numerical-gradient.gradient[i]));
        require(std::abs(numerical-gradient.gradient[i])<2e-7);
      }
      std::printf("%s{\"old_log_probability\":%.17g,\"advantage\":%.17g,\"target\":%.17g,\"loss\":%.17g,\"ratio\":%.17g,\"entropy\":%.17g,\"gradient\":",
                  fixture ? "," : "",sample.old_log_probability,sample.advantage,sample.target,gradient.loss,gradient.ratio,gradient.entropy);
      array(gradient.gradient); std::printf("}");
    }
    std::printf("],\"finite_difference_max_error\":%.17g",worst_error);
    parameters.normalize_advantage=false;
    std::vector<PpoSample> gae(3);
    for (size_t i=0; i<3; ++i) { gae[i].reward=i+1; gae[i].old_value=i+2; gae[i].next_value=i+3; }
    gae[1].truncated=true; gae[2].terminated=true; gae[2].next_value=999;
    auto advantages_result=PrepareAdvantages(gae,parameters);
    require(std::abs(advantages_result[0].advantage-4.75388)<1e-12);
    require(std::abs(advantages_result[1].advantage-2.96)<1e-12 && advantages_result[2].advantage==-1);
    std::array<double,3> gae_values{advantages_result[0].advantage,advantages_result[1].advantage,advantages_result[2].advantage};
    std::printf(",\"gae\":"); array(gae_values);
    parameters.normalize_advantage=true;
    auto normalized=PrepareAdvantages(gae,parameters);
    std::array<double,3> normalized_values{normalized[0].advantage,normalized[1].advantage,normalized[2].advantage};
    std::printf(",\"normalized_advantages\":"); array(normalized_values);
    AdamState adam(weights.size()); CategoricalPolicy adam_policy=policy;
    std::vector<double> direction(weights.size()); direction[0]=.25; direction[1]=-.5;
    AdamStep(adam_policy,adam,direction,parameters);
    require(adam.step==1 && std::abs(adam.first[0]-.025)<1e-16);
    std::printf(",\"adam_weights\":"); array(adam_policy.parameters());
    std::printf(",\"adam_first\":"); array(adam.first);
    std::printf(",\"adam_second\":"); array(adam.second);
    const auto before_adam=adam_policy.parameters(); const auto before_first=adam.first;
    direction.back()=INFINITY;
    rejects([&] { AdamStep(adam_policy,adam,direction,parameters); });
    require(adam_policy.parameters()==before_adam && adam.first==before_first && adam.step==1);
    direction.back()=0; direction[0]=-.125; direction[1]=.75;
    AdamStep(adam_policy,adam,direction,parameters);
    std::printf(",\"adam_step2_weights\":"); array(adam_policy.parameters());
    std::printf(",\"adam_step2_first\":"); array(adam.first);
    std::printf(",\"adam_step2_second\":"); array(adam.second);
    parameters.epochs=2; parameters.minibatch=4;
    std::vector<PpoSample> rollout(6,sample);
    for (size_t i=0; i<rollout.size(); ++i) {
      rollout[i].old_log_probability=distribution.log_probability(sample.actions);
      rollout[i].reward=int(i%3)-1; rollout[i].next_value=output.value-.1; rollout[i].policy_version=0;
      rollout[i].terminated=false; rollout[i].truncated=i==2;
    }
    CategoricalPolicy training=policy, replay=policy; AdamState optimizer(weights.size()), replay_optimizer(weights.size());
    PolicyRng shuffle(17), replay_shuffle(17);
    auto update=UpdatePpo(training,optimizer,shuffle,rollout,0,parameters);
    UpdatePpo(replay,replay_optimizer,replay_shuffle,rollout,0,parameters);
    require(update.parameter_delta>0 && optimizer.step==4 && training.parameters()==replay.parameters() &&
            optimizer.first==replay_optimizer.first && optimizer.second==replay_optimizer.second && shuffle.state()==replay_shuffle.state());
    const auto before=training.parameters(); const auto first=optimizer.first; const auto random=shuffle.state();
    rollout[0].policy_version=2;
    rejects([&] { UpdatePpo(training,optimizer,shuffle,rollout,1,parameters); });
    require(before==training.parameters() && first==optimizer.first && random==shuffle.state());
    rejects([&] { PrepareAdvantages({},parameters); });
    parameters.gamma=NAN; rejects([&] { parameters.validate(); });
    std::printf(",\"parameter_delta\":%.17g,\"optimizer_steps\":%llu,\"passed\":true}\n",update.parameter_delta,
                static_cast<unsigned long long>(optimizer.step));
    return 0;
  } catch (const std::exception& error) { std::fprintf(stderr,"%s\n",error.what()); return 1; }
}
