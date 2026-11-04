// Bounded diagnosis: standard-sampled rollout adapter vs official inference path.
#include "training/native_policy.hpp"
#include "training/native_inference.hpp"
#include <iostream>
#include <stdexcept>
using namespace football::training;
void require(bool value,const char* why){if(!value)throw std::runtime_error(why);}
int main(int argc,char** argv){
  try{
    require(argc==3,"policy.fpol old-validation-cases.txt");
    inference::PortablePolicy model(argv[1]);auto cases=inference::Cases(inference::Read(argv[2],128*1024));
    require(cases.size()==200,"Expected old200-case validation");
    NativePolicyEnvironment training(model.policy.spec(),false,160,90,true);
    NativeTrainingEnv inference_env(160,90,true,true,false,false);
    size_t episodes=0,decisions=0;
    for(const auto& c:cases){
      if(c.index%40>=4)continue; // Four preregistered cases per geometry family.
      auto scene=frame_sync::MakeDefaultScenario(1,0,42);ConfigureTwoOnOne(*scene);scene->deterministic=true;scene->game_engine_random_seed=c.seed;
      scene->left_team[1]=FormationEntry(c.ax,c.ay,e_PlayerRole_CF,false,true);scene->left_team[2]=FormationEntry(c.tx,c.ty,e_PlayerRole_CF,false,true);
      scene->right_team[1]=FormationEntry(c.dx,c.dy,e_PlayerRole_CB,false,false);scene->ball_position=blunted::Vector3(c.ax+.02f,c.ay,0);
      training.reset(*scene,10);auto observation=inference_env.reset(*scene,10);
      CooperationMetrics a,b;a.observe(training.possession());b.observe(inference_env.possession());
      PolicyRng ar(c.action_seed),br(c.action_seed);
      for(size_t step=0;step<256;++step){
        require(training.kernel_state()==inference_env.get_state_digest(),"Pre-step engine state mismatch");
        require(training.sticky_actions()==inference_env.sticky_actions(),"Sticky mismatch");
        auto view=CooperationObservation(observation,b.completed_passes>0,inference_env.sticky_actions());
        auto decision=model.policy.decide(view,br,false);auto before=training.possession();
        b.action(inference_env.possession(),decision.actions.front());auto direct=inference_env.step(std::array<int,2>{decision.actions.front(),19});b.observe(inference_env.possession());
        auto adapted=training.step(model.policy,ar,false,step==255,a.completed_passes>0);
        a.action(before,adapted.decision.actions.front());a.observe(training.possession());
        require(adapted.observation==view,"Policy view mismatch");
        require(adapted.decision.actions==decision.actions&&ar.state()==br.state(),"Action/RNG mismatch");
        require(adapted.decision.log_probability==decision.log_probability&&adapted.decision.value==decision.value,"Log-probability/value mismatch");
        require(adapted.following.observations==PrimaryCooperationObservation(direct.observations),"Following observation mismatch");
        require(adapted.reward==direct.rewards.front()&&adapted.following.score_reward==direct.score_reward&&adapted.following.terminated==direct.terminated,"Reward/lifecycle mismatch");
        require(a.pass_requests==b.pass_requests&&a.completed_passes==b.completed_passes&&a.turnovers==b.turnovers,"Cooperation history mismatch");
        require(training.kernel_state()==inference_env.get_state_digest(),"Post-step engine state mismatch");
        observation=std::move(direct.observations);++decisions;if(direct.terminated)break;
      }
      ++episodes;
    }
    training.close();inference_env.close();require(episodes==20,"Episode budget mismatch");
    std::cout<<"{\"passed\":true,\"episodes\":"<<episodes<<",\"decisions\":"<<decisions<<",\"mode\":\"sample\",\"updated_weights\":false}\n";
  }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
