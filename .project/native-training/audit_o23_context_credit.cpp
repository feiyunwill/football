// Read-only carried-credit diagnosis. Fresh actions are shadow decisions only.
#include "training/native_inference.hpp"
#include <filesystem>
#include <fstream>
#include <iomanip>
using namespace football::training;
int main(int argc,char** argv){
  try{
    inference::Require(argc==4,"policy old200cases NEW_trace_path");
    inference::Require(!std::filesystem::exists(argv[3]),"Trace output must be new");
    inference::PortablePolicy model(argv[1]);auto cases=inference::Cases(inference::Read(argv[2],128*1024));
    inference::Require(cases.size()==200,"Need old200cases");std::ofstream trace(argv[3]);trace<<std::setprecision(17);
    NativeTrainingEnv env(160,90,true,true,false,false);size_t episodes=0,decisions=0,phase_changes=0,phase_different=0,all_different=0,low_probability=0,phase_low=0,goals=0;
    for(const auto& c:cases){
      if(c.index%40>=4)continue;
      auto scene=frame_sync::MakeDefaultScenario(1,0,42);ConfigureTwoOnOne(*scene);scene->deterministic=true;scene->game_engine_random_seed=c.seed;
      scene->left_team[1]=FormationEntry(c.ax,c.ay,e_PlayerRole_CF,false,true);scene->left_team[2]=FormationEntry(c.tx,c.ty,e_PlayerRole_CF,false,true);
      scene->right_team[1]=FormationEntry(c.dx,c.dy,e_PlayerRole_CB,false,false);scene->ball_position=blunted::Vector3(c.ax+.02f,c.ay,0);
      auto observation=env.reset(*scene,10);CooperationMetrics metrics;metrics.observe(env.possession());BalancedInference controller;
      bool previous_phase=false;int previous_team=-2,previous_player=-2;int score=0;size_t steps=0;
      for(;steps<256;++steps){
        const auto possession=env.possession();const bool phase=metrics.completed_passes>0;const bool changed=phase!=previous_phase;
        const bool owner_changed=steps>0&&(possession.team!=previous_team||possession.player!=previous_player);
        auto view=CooperationObservation(observation,phase,env.sticky_actions());auto output=model.policy.forward(view);CategoricalDistribution distribution(output.logits,1,19);
        auto p=distribution.probabilities();BalancedInference fresh;const auto before=controller.get_state();const int action=controller.choose(p),shadow=fresh.choose(p);
        const bool low=p[shadow]>.5&&p[action]<.25*p[shadow];
        phase_changes+=changed;phase_different+=changed&&action!=shadow;all_different+=action!=shadow;low_probability+=low;phase_low+=changed&&low;
        trace<<"{\"case\":"<<c.index<<",\"group\":"<<c.group<<",\"step\":"<<steps<<",\"team\":"<<possession.team<<",\"player\":"<<possession.player
          <<",\"passed\":"<<(phase?"true":"false")<<",\"phase_changed\":"<<(changed?"true":"false")<<",\"owner_changed\":"<<(owner_changed?"true":"false")
          <<",\"action\":"<<action<<",\"fresh_shadow\":"<<shadow<<",\"chosen_probability\":"<<p[action]<<",\"maximum_probability\":"<<p[shadow]
          <<",\"low_probability\":"<<(low?"true":"false")<<",\"controller_before\":"<<std::quoted(before)<<",\"probabilities\":[";
        for(size_t i=0;i<p.size();++i)trace<<(i?",":"")<<p[i];trace<<"]}\n";
        previous_phase=phase;previous_team=possession.team;previous_player=possession.player;
        metrics.action(possession,action);auto t=env.step(std::array<int,2>{action,19});metrics.observe(env.possession());score+=t.score_reward;++decisions;
        observation=std::move(t.observations);if(t.terminated){++steps;break;}
      }
      ++episodes;goals+=score>0;
    }
    trace.close();inference::Require(bool(trace)&&episodes==20,"Incomplete trace");env.close();
    std::cout<<"{\"passed\":true,\"episodes\":"<<episodes<<",\"decisions\":"<<decisions<<",\"goals\":"<<goals<<",\"phase_changes\":"<<phase_changes
      <<",\"phase_different\":"<<phase_different<<",\"all_different\":"<<all_different<<",\"low_probability\":"<<low_probability<<",\"phase_low_probability\":"<<phase_low
      <<",\"trace_path\":"<<std::quoted(std::string(argv[3]))<<",\"trace_sha256\":\""<<inference::Digest(inference::Read(argv[3],32*1024*1024))
      <<"\",\"mode\":\"balanced_shadow_reset\",\"updated_weights\":false,\"intervened\":false}\n";
  }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
