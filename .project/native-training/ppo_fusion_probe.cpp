// Isolated deterministic update benchmark; never installed with the engine.
#include "training/ppo_math.hpp"
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <ctime>
using namespace football::training;
template<class T> void emit(const T& value) { std::fwrite(&value,sizeof(value),1,stdout); }
void emit_vector(const std::vector<double>& values) {
  std::fwrite(values.data(),sizeof(double),values.size(),stdout);
}
int main(int argc,char** argv) {
  if(argc!=5) return 2;
  size_t players=std::strtoul(argv[1],nullptr,10), hidden=std::strtoul(argv[2],nullptr,10);
  size_t count=std::strtoul(argv[3],nullptr,10), repeats=std::strtoul(argv[4],nullptr,10);
  PolicySpec spec; spec.players=players; spec.hidden=hidden;
  CategoricalPolicy original(spec,7);
  std::vector<PpoSample> samples(count);
  PolicyRng sampling(91);
  for(size_t i=0;i<count;++i) {
    auto& sample=samples[i]; sample.observation=ObservationBuffer(players);
    for(size_t j=0;j<sample.observation.buffer().size();++j)
      sample.observation.buffer()[j]=(int((i*13+j*7)%101)-50)*.01f;
    auto decision=original.decide(sample.observation,sampling);
    sample.actions=decision.actions;
    auto output=original.forward(sample.observation);
    CategoricalDistribution distribution(output.logits,players,spec.actions());
    sample.old_log_probability=distribution.log_probability(sample.actions);
    sample.old_value=output.value; sample.next_value=output.value*.9;
    sample.reward=(int(i%7)-3)*.1; sample.truncated=(i%17==16 || i+1==count);
    sample.terminated=(i%31==30); if(sample.terminated) sample.truncated=false;
  }
  PpoParameters parameters;
  std::clock_t elapsed=0;
  for(size_t repeat=0;repeat<repeats;++repeat) {
    auto policy=original; AdamState adam(policy.parameters().size()); PolicyRng shuffle(17);
    auto start=std::clock();
    auto result=UpdatePpo(policy,adam,shuffle,samples,0,parameters);
    elapsed+=std::clock()-start;
    if(repeat==0) {
      emit_vector(policy.parameters()); emit_vector(adam.first); emit_vector(adam.second);
      emit(adam.step); auto rng=shuffle.state(); emit(rng);
      emit(result.loss); emit(result.entropy); emit(result.clip_fraction);
      emit(result.gradient_norm); emit(result.parameter_delta); emit(result.optimizer_steps);
      auto prepared=PrepareAdvantages(samples,parameters);
      for(const auto& sample:prepared) {
        auto gradient=LossGradient(policy,sample,parameters);
        emit_vector(gradient.gradient); emit(gradient.loss); emit(gradient.ratio);
      }
    }
  }
  std::fprintf(stderr,"%.9f\n",double(elapsed)/CLOCKS_PER_SEC);
}
