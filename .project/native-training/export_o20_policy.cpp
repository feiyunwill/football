// Run only against the accepted compatible O20 core; exports inference weights,
// never rewrites FPPO identity or imports optimizer/native state into a new build.
#include "training/ppo_learner.hpp"
#include "frame_sync/default_scenario.hpp"
#include "frame_sync/state_hash.hpp"
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
using namespace football::training;
std::string digest(std::string_view bytes) {
  frame_sync::SHA256 h;h.update(reinterpret_cast<const uint8_t*>(bytes.data()),bytes.size());
  uint8_t out[32];h.finalize(out);std::string result;const char* hex="0123456789abcdef";
  for(auto x:out){result+=hex[x>>4];result+=hex[x&15];}return result;
}
int main(int argc,char** argv) {
  try {
    if(argc!=4)throw std::invalid_argument("seed FPPO output");
    PpoLearnerConfig config;config.seed=std::stoull(argv[1]);config.policy.hidden=64;
    config.parameters.epochs=4;config.parameters.minibatch=64;
    config.scenario=frame_sync::MakeDefaultScenario(1,0,42);ConfigureTwoOnOne(*config.scenario);
    config.scenario->deterministic=true;config.scenario_variation=PpoScenarioVariation::TwoOnOne;
    PpoLearner learner(config);learner.load(argv[2]);
    std::ifstream input(argv[2],std::ios::binary);std::string checkpoint((std::istreambuf_iterator<char>(input)),{});
    if(!input || checkpoint!=learner.get_state())throw std::runtime_error("Full checkpoint roundtrip mismatch");
    std::ostringstream payload;payload<<std::setprecision(17)<<"two_on_one_sticky_v1 "<<kCategoricalPolicyVersion<<' '<<kPolicyRngVersion<<' '
      <<config.seed<<' '<<config.policy.hidden<<' '<<learner.policy().parameters().size()<<' '<<digest(checkpoint)<<'\n';
    for(double p:learner.policy().parameters())payload<<p<<'\n';
    const std::string bytes="FPOL1\n"+digest(payload.str())+'\n'+payload.str();
    std::ofstream output(argv[3],std::ios::binary);output<<bytes;output.close();
    if(!output)throw std::runtime_error("Policy export write failed");
    std::cout<<"{\"passed\":true,\"seed\":"<<config.seed<<",\"policy_sha256\":\""<<digest(bytes)<<"\",\"checkpoint_sha256\":\""<<digest(checkpoint)<<"\"}\n";
  }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
