// Single preregistered experiment. Original neural weights and action space stay fixed.
#include "training/native_inference.hpp"
using namespace football::training;
int main(int argc,char** argv){
  try{
    inference::Require(argc==4,"policy old200cases balanced|phase_reset");const std::string mode=argv[3];
    inference::Require(mode=="balanced"||mode=="phase_reset","Unknown experimental mode");
    inference::PortablePolicy model(argv[1]);auto cases=inference::Cases(inference::Read(argv[2],128*1024));inference::Require(cases.size()==200,"Need old200cases");
    NativeTrainingEnv env(160,90,true,true,false,false);size_t decisions=0,total_resets=0;
    for(const auto& c:cases){
      auto scene=frame_sync::MakeDefaultScenario(1,0,42);ConfigureTwoOnOne(*scene);scene->deterministic=true;scene->game_engine_random_seed=c.seed;
      scene->left_team[1]=FormationEntry(c.ax,c.ay,e_PlayerRole_CF,false,true);scene->left_team[2]=FormationEntry(c.tx,c.ty,e_PlayerRole_CF,false,true);
      scene->right_team[1]=FormationEntry(c.dx,c.dy,e_PlayerRole_CB,false,false);scene->ball_position=blunted::Vector3(c.ax+.02f,c.ay,0);
      auto observation=env.reset(*scene,10);inference::Episode episode;episode.actions.set_state(c.action_seed);episode.metrics.observe(env.possession());
      bool previous_phase=false;size_t resets=0;
      while(episode.steps<256){
        const bool phase=episode.metrics.completed_passes>0;
        if(mode=="phase_reset"&&phase&&!previous_phase){episode.controller=BalancedInference{};++resets;++total_resets;}
        previous_phase=phase;inference::Require(resets<=1,"Reset occurred more than once");
        auto view=CooperationObservation(observation,phase,env.sticky_actions());auto output=model.policy.forward(view);CategoricalDistribution distribution(output.logits,1,19);
        const int action=episode.controller.choose(distribution.probabilities());inference::Require(action>=0&&action<19,"Learner action outside original space");
        episode.metrics.action(env.possession(),action);auto t=env.step(std::array<int,2>{action,19});episode.metrics.observe(env.possession());
        episode.reward+=t.rewards.front();episode.score+=t.score_reward;++episode.steps;++decisions;episode.terminated=t.terminated;observation=std::move(t.observations);if(t.terminated)break;
      }
      inference::Print(c,*scene,episode);
    }
    env.close();std::cout<<"{\"summary\":true,\"complete\":true,\"episodes\":200,\"decisions\":"<<decisions<<",\"phase_resets\":"<<total_resets
      <<",\"mode\":\""<<mode<<"\",\"policy_sha256\":\""<<model.sha<<"\"}\n";
  }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
