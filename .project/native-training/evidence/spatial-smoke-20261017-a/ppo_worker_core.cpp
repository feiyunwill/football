// Diagnostic bridge to the production categorical policy and PPO update math.
// Built outside the repository; not installed or added to the public engine API.
#include "training/ppo_math.hpp"
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <algorithm>
#include <cmath>
#include <chrono>
#include <tuple>
namespace py = pybind11;
using namespace football::training;
namespace {
void require(bool value, const char* message) {
  if (!value) throw std::invalid_argument(message);
}
PolicySpec spec(size_t players) {
  PolicySpec result; result.players=players; result.hidden=16; result.validate(); return result;
}
class Core {
  CategoricalPolicy policy_;
  AdamState optimizer_;
  PolicyRng shuffle_;
  PpoParameters parameters_;
  uint64_t version_=0;
  using Key=std::pair<uint64_t,size_t>;
  std::vector<std::pair<Key,PpoSample>> records_;
  ObservationBuffer observation(py::array_t<float,py::array::c_style|py::array::forcecast> input) const {
    require(size_t(input.size())==policy_.spec().inputs(),"Wrong observation shape");
    ObservationBuffer result(policy_.spec().players);
    std::copy(input.data(),input.data()+input.size(),result.buffer().begin());
    for(float value:result.buffer()) require(std::isfinite(value),"Nonfinite observation");
    return result;
  }
 public:
  Core(size_t players,uint64_t seed):policy_(spec(players),seed ^ UINT64_C(0xa0761d6478bd642f)),
      optimizer_(policy_.parameters().size()), shuffle_(seed ^ UINT64_C(0x8ebc6af09c88c6e3)) {}
  std::vector<int> decide(py::array_t<float,py::array::c_style|py::array::forcecast> input,
                          uint64_t episode_seed,size_t step) const {
    require(step<4096,"Step budget exceeded");
    PolicyRng rng(episode_seed ^ (step*UINT64_C(0x9e3779b97f4a7c15)));
    return policy_.decide(observation(input),rng).actions;
  }
  void add(py::array_t<float,py::array::c_style|py::array::forcecast> input,
           const std::vector<int>& actions,
           py::array_t<float,py::array::c_style|py::array::forcecast> next,
           double reward,bool terminated,bool truncated,uint64_t episode,size_t step) {
    require(records_.size()<kMaxPpoRollout && step<4096 && std::isfinite(reward) &&
            !(terminated&&truncated),"Invalid bounded transition");
    PpoSample sample; sample.observation=observation(input); sample.actions=actions;
    const auto old=policy_.forward(sample.observation);
    CategoricalDistribution distribution(old.logits,policy_.spec().players,policy_.spec().actions());
    sample.old_log_probability=distribution.log_probability(actions); sample.old_value=old.value;
    sample.next_value=terminated?0:policy_.forward(observation(next)).value;
    sample.reward=reward; sample.terminated=terminated; sample.truncated=truncated; sample.policy_version=version_;
    records_.push_back({{episode,step},std::move(sample)});
  }
  py::dict update() {
    require(!records_.empty(),"Empty rollout");
    std::sort(records_.begin(),records_.end(),[](const auto& a,const auto& b){return a.first<b.first;});
    std::vector<PpoSample> samples;
    for(size_t i=0;i<records_.size();++i) {
      const auto& [key,sample]=records_[i];
      if(i==0 || key.first!=records_[i-1].first.first) {
        require(key.second==0 && (i==0 || samples.back().terminated || samples.back().truncated),
                "Episode boundary missing");
      } else require(key.second==records_[i-1].first.second+1 && !samples.back().terminated &&
                     !samples.back().truncated,"Noncontiguous episode");
      samples.push_back(sample);
    }
    require(samples.back().terminated||samples.back().truncated,"Incomplete final episode");
    const auto start=std::chrono::steady_clock::now();
    auto old_policy=policy_;
    auto prepared=PrepareAdvantages(samples,parameters_);
    const auto update_start=std::chrono::steady_clock::now();
    auto result=UpdatePpo(policy_,optimizer_,shuffle_,samples,version_,parameters_);
    const auto update_end=std::chrono::steady_clock::now();
    double kl=0,value_loss=0;
    for(size_t i=0;i<samples.size();++i) {
      auto old=old_policy.forward(samples[i].observation),current=policy_.forward(samples[i].observation);
      CategoricalDistribution previous(old.logits,policy_.spec().players,policy_.spec().actions());
      CategoricalDistribution following(current.logits,policy_.spec().players,policy_.spec().actions());
      for(size_t j=0;j<previous.probabilities().size();++j)
        kl+=previous.probabilities()[j]*(previous.log_probabilities()[j]-following.log_probabilities()[j]);
      const double residual=current.value-prepared[i].target;
      value_loss+=0.5*residual*residual;
    }
    kl/=samples.size(); value_loss/=samples.size();
    require(std::isfinite(kl)&&std::isfinite(value_loss),"Nonfinite PPO diagnostics");
    const auto end=std::chrono::steady_clock::now();
    ++version_; records_.clear();
    py::dict out; out["loss"]=result.loss; out["entropy"]=result.entropy;
    out["parameter_delta"]=result.parameter_delta; out["transitions"]=samples.size();
    out["clip_fraction"]=result.clip_fraction; out["gradient_norm"]=result.gradient_norm;
    out["kl_old_new"]=kl; out["value_loss_after"]=value_loss;
    const auto native_ns=std::chrono::duration_cast<std::chrono::nanoseconds>(update_end-update_start).count();
    out["native_update_ns"]=native_ns;
    out["diagnostic_ns"]=std::chrono::duration_cast<std::chrono::nanoseconds>(end-start).count()-native_ns;
    out["optimizer_steps"]=result.optimizer_steps; return out;
  }
  py::dict state() const {
    require(records_.empty(),"Checkpoint requires completed episodes/update boundary");
    py::dict out; out["schema"]=1; out["players"]=policy_.spec().players;
    out["weights"]=policy_.parameters(); out["first"]=optimizer_.first; out["second"]=optimizer_.second;
    out["optimizer_step"]=optimizer_.step; out["shuffle"]=shuffle_.state(); out["version"]=version_; return out;
  }
  void restore(py::dict state) {
    require(records_.empty() && state.size()==8 && state["schema"].cast<int>()==1 &&
            state["players"].cast<size_t>()==policy_.spec().players,"Checkpoint identity mismatch");
    auto proposed=policy_; auto optimizer=optimizer_;
    proposed.set_parameters(state["weights"].cast<std::vector<double>>());
    optimizer.first=state["first"].cast<std::vector<double>>(); optimizer.second=state["second"].cast<std::vector<double>>();
    require(optimizer.first.size()==proposed.parameters().size() && optimizer.second.size()==optimizer.first.size(),
            "Optimizer shape mismatch");
    for(double value:optimizer.first) require(std::isfinite(value),"Nonfinite optimizer");
    for(double value:optimizer.second) require(std::isfinite(value)&&value>=0,"Invalid optimizer variance");
    optimizer.step=state["optimizer_step"].cast<uint64_t>();
    const auto version=state["version"].cast<uint64_t>(),shuffle=state["shuffle"].cast<uint64_t>();
    require(version<kMaxPpoCounter && optimizer.step<kMaxPpoCounter,"Counter budget exceeded");
    policy_=std::move(proposed); optimizer_.swap(optimizer); shuffle_.set_state(shuffle); version_=version;
  }
};
}
PYBIND11_MODULE(_ppo_worker_core,module) {
  py::class_<Core>(module,"Core").def(py::init<size_t,uint64_t>()).def("decide",&Core::decide)
    .def("add",&Core::add).def("update",&Core::update).def("state",&Core::state).def("restore",&Core::restore);
}
