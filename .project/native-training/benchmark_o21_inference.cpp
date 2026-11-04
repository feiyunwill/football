#include "training/native_inference.hpp"
#include "deterministic_inference.hpp"
#include <chrono>
#include <iostream>

int main(int argc,char** argv) {
  using namespace football::training;
  try {
    if(argc!=2)throw std::invalid_argument("policy file");
    // Header from the historical O20 tools, distinct from the production type.
    DeterministicInference old("balanced");BalancedInference current;PolicyRng input(20261019021);
    for(int step=0;step<10000;++step) {
      std::array<double,19> p;double sum=0;for(double& x:p){x=input.uniform();sum+=x;}for(double& x:p)x/=sum;
      if(old.choose(p)!=current.choose(p)||old.get_state()!=current.get_state())throw std::runtime_error("O20 controller byte parity failed");
      if(step%100==0){const auto state=current.get_state();BalancedInference restored;restored.set_state(state);current=restored;}
    }
    const auto before=current.get_state();
    for(const std::string bad:std::array<std::string,4>{"DIC9 balanced 0 -1 0","DIC1 sample 0 -1 0",before+" extra",std::string(5000,'x')}){
      try{current.set_state(bad);throw std::logic_error("Accepted malformed state");}catch(const std::invalid_argument&){}
      if(before!=current.get_state())throw std::runtime_error("Invalid restore changed state");
    }
    std::array<double,19> invalid{};
    try{current.choose(invalid);throw std::logic_error("Accepted invalid probability");}catch(const std::invalid_argument&){}
    if(before!=current.get_state())throw std::runtime_error("Invalid input changed state");
    inference::PortablePolicy model(argv[1]);ObservationBuffer view(1,115);view.buffer()[21]=-1;
    std::cout<<std::setprecision(17)<<"{\"contract_passed\":true,\"o20_equal_decisions\":10000,\"controller_bytes\":"<<sizeof(BalancedInference)
      <<",\"serialized_controller_bytes\":"<<before.size()<<",\"measurements\":[";
    uint64_t checksum=0;bool comma=false;
    for(int repeat=0;repeat<5;++repeat)for(const std::string mode:{"argmax","sample","balanced"}){
      PolicyRng rng(42);BalancedInference balanced;constexpr size_t count=20000;
      const auto start=std::chrono::steady_clock::now();
      for(size_t i=0;i<count;++i){
        if(i%256==0)balanced=BalancedInference{};
        view.buffer()[88]=float(i%19)*.0001f;
        if(mode=="balanced"){
          auto output=model.policy.forward(view);CategoricalDistribution dist(output.logits,1,19);checksum+=balanced.choose(dist.probabilities());
        }else checksum+=model.policy.decide(view,rng,mode=="argmax").actions.front();
      }
      const double ns=std::chrono::duration<double,std::nano>(std::chrono::steady_clock::now()-start).count()/count;
      std::cout<<(comma?",":"")<<"{\"mode\":\""<<mode<<"\",\"repeat\":"<<repeat<<",\"decisions\":"<<count<<",\"nanoseconds_per_decision\":"<<ns<<"}";comma=true;
    }
    std::cout<<"],\"checksum\":"<<checksum<<"}\n";
  }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
