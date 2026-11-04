// Frozen-model evaluation only. Compiled with the accepted CLI flags/libraries.
#include "training/ppo_learner.hpp"
#include "frame_sync/default_scenario.hpp"
#include <array>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <string>

using namespace football::training;
int main(int argc,char** argv) {
  try {
    if(argc!=5) throw std::invalid_argument("seed checkpoint-or-dash mode cases-file");
    const std::string mode=argv[3];
    if(mode!="sample" && mode!="argmax" && mode!="uniform_random" && mode!="builtin_ai")
      throw std::invalid_argument("Unknown evaluation mode");
    PpoLearnerConfig config;config.seed=std::stoull(argv[1]);config.policy.hidden=64;
    config.parameters.epochs=4;config.parameters.minibatch=64;
    config.scenario=frame_sync::MakeDefaultScenario(1,0,42);
    ConfigureTwoOnOne(*config.scenario);config.scenario->deterministic=true;
    config.scenario_variation=PpoScenarioVariation::TwoOnOne;
    PpoLearner learner(config);
    if(std::string(argv[2])!="-") learner.load(argv[2]);
    const auto before=learner.get_state();
    if(std::string(argv[2])!="-") {
      std::ifstream saved(argv[2],std::ios::binary);
      const std::string bytes((std::istreambuf_iterator<char>(saved)),{});
      if(!saved || bytes!=before) throw std::runtime_error("Loaded state does not equal frozen checkpoint bytes");
    }
    std::ifstream cases(argv[4]);if(!cases) throw std::runtime_error("Cannot open cases");
    NativeTrainingEnv env(160,90,true,config.policy.fixed_positions,false,false);
    size_t count=0,index,group;int legacy;uint32_t seed;uint64_t action_seed;
    float ax,ay,tx,ty,dx,dy;
    std::cout<<std::setprecision(17);
    while(cases>>index>>group>>legacy>>seed>>action_seed>>ax>>ay>>tx>>ty>>dx>>dy) {
      if(index!=count || count>=400 || group>4 || (legacy!=0 && legacy!=1))
        throw std::invalid_argument("Invalid case identity/budget");
      auto scene=*config.scenario;scene.game_engine_random_seed=seed;
      if(legacy) ApplyPpoStart(scene,PpoScenarioVariation::TwoOnOne,seed,StartPartition::Holdout);
      else {
        if(!std::isfinite(ax+ay+tx+ty+dx+dy) || ax<.25f || ax>.72f || tx<.25f || tx>.94f || dx<.25f || dx>.95f ||
           std::abs(ay)>.4f || std::abs(ty)>.4f || std::abs(dy)>.4f)
          throw std::invalid_argument("Geometry outside registered bounds");
        scene.left_team[1]=FormationEntry(ax,ay,e_PlayerRole_CF,false,true);
        scene.left_team[2]=FormationEntry(tx,ty,e_PlayerRole_CF,false,true);
        scene.right_team[1]=FormationEntry(dx,dy,e_PlayerRole_CB,false,false);
        scene.ball_position=blunted::Vector3(ax+.02f,ay,0);
      }
      auto observation=env.reset(scene,10);PolicyRng actions(action_seed);
      CooperationMetrics metrics;metrics.observe(env.possession());
      size_t steps=0;bool terminated=false;double reward=0,score=0;
      while(steps<256) {
        int action;
        if(mode=="builtin_ai") action=19;
        else if(mode=="uniform_random") action=actions.index(config.policy.actions());
        else action=learner.policy().decide(CooperationObservation(observation,metrics.completed_passes>0,env.sticky_actions()),actions,mode=="argmax").actions.front();
        metrics.action(env.possession(),action);
        auto transition=env.step(std::array<int,2>{action,19});
        metrics.observe(env.possession());reward+=transition.rewards.front();score+=transition.score_reward;
        ++steps;terminated=transition.terminated;observation=std::move(transition.observations);
        if(terminated) break;
      }
      std::cout<<"{\"index\":"<<index<<",\"group\":"<<group<<",\"engine_seed\":"<<seed
        <<",\"start_x\":"<<scene.ball_position.coords[0]<<",\"start_y\":"<<scene.ball_position.coords[1]
        <<",\"steps\":"<<steps<<",\"terminated\":"<<(terminated?"true":"false")
        <<",\"truncated\":"<<(!terminated && steps==256?"true":"false")
        <<",\"reward\":"<<reward<<",\"controlled_score_delta\":"<<score
        <<",\"pass_requests\":"<<metrics.pass_requests<<",\"completed_passes\":"<<metrics.completed_passes
        <<",\"teammate_transfers\":"<<metrics.teammate_transfers<<",\"turnovers\":"<<metrics.turnovers<<"}\n";
      ++count;
    }
    if(!cases.eof() || count==0) throw std::invalid_argument("Malformed/empty cases");
    env.close();if(before!=learner.get_state()) throw std::runtime_error("Evaluation mutated learner");
    std::cout<<"{\"summary\":true,\"isolated\":true,\"episodes\":"<<count
      <<",\"version\":"<<learner.version()<<",\"transitions\":"<<learner.transitions()<<"}\n";
    return 0;
  } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
