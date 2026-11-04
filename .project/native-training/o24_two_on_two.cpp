// Exploratory fixed-geometry2v2: two jointly learned outfield players vs two AI
// defenders,plus required goalkeepers. Not the one-learner/fixed-AI2v1 task.
#include "training/ppo_learner.hpp"
#include "frame_sync/default_scenario.hpp"
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <set>
#include <stdexcept>
using namespace football::training;

ScenarioConfig scenario(){
  auto scene=frame_sync::MakeDefaultScenario(2,0,42);
  scene->left_team={FormationEntry(-1,0,e_PlayerRole_GK,false,false),FormationEntry(.5f,-.14f,e_PlayerRole_CF,false,true),FormationEntry(.65f,.14f,e_PlayerRole_CF,false,true)};
  scene->right_team={FormationEntry(1,0,e_PlayerRole_GK,false,false),FormationEntry(.65f,-.035f,e_PlayerRole_CB,false,false),FormationEntry(.78f,.14f,e_PlayerRole_CB,false,false)};
  scene->left_agents=2;scene->right_agents=0;scene->ball_position=blunted::Vector3(.52f,-.14f,0);
  scene->game_duration=400;scene->offsides=false;scene->deterministic=true;
  scene->end_episode_on_score=true;scene->end_episode_on_out_of_play=true;scene->end_episode_on_possession_change=false;
  return *scene;
}
void evaluate(const CategoricalPolicy& policy,const std::string& mode,const std::vector<uint32_t>& seeds,const std::filesystem::path& path){
  std::ofstream out(path);if(!out)throw std::runtime_error("Cannot write evaluation");out<<std::setprecision(17);
  NativeTrainingEnv env(160,90,true,true,false,false);
  for(size_t i=0;i<seeds.size();++i){
    auto scene=scenario();scene.game_engine_random_seed=seeds[i];auto observation=env.reset(scene,10);
    PolicyRng actions(UINT64_C(20261020025)^UINT64_C(0x13198a2e03707344)^(i*UINT64_C(0x9e3779b97f4a7c15)));
    size_t steps=0;bool terminated=false;int score=0;double reward=0;
    while(steps<256){
      std::vector<int> chosen(2);
      if(mode=="builtin_ai")std::fill(chosen.begin(),chosen.end(),19);
      else if(mode=="uniform_random")for(auto& a:chosen)a=actions.index(19);
      else chosen=policy.decide(observation,actions,mode=="argmax").actions;
      auto transition=env.step(chosen);score+=transition.score_reward;
      reward+=(transition.rewards[0]+transition.rewards[1])/2.;++steps;terminated=transition.terminated;observation=std::move(transition.observations);
      if(terminated)break;
    }
    out<<"{\"index\":"<<i<<",\"engine_seed\":"<<seeds[i]<<",\"steps\":"<<steps<<",\"terminated\":"<<(terminated?"true":"false")
      <<",\"truncated\":"<<(!terminated&&steps==256?"true":"false")<<",\"reward\":"<<reward<<",\"score\":"<<score<<"}\n";
  }
  out.close();if(!out)throw std::runtime_error("Incomplete evaluation write");env.close();
}
int main(int argc,char** argv){
  try{
    if(argc!=4)throw std::invalid_argument("training-seed NEW_OUTPUT_DIRECTORY heldout-engine-seeds.txt");
    const auto seed=std::stoull(argv[1]);const std::filesystem::path out(argv[2]);
    std::ifstream input(argv[3]);if(!input)throw std::invalid_argument("Cannot open cases");
    std::vector<uint32_t> cases;uint32_t value;
    while(input>>value){if(value>2000000000||cases.size()>=50)throw std::invalid_argument("Case budget");cases.push_back(value);}
    if(!input.eof()||cases.size()!=50||std::set<uint32_t>(cases.begin(),cases.end()).size()!=50)throw std::invalid_argument("Need50 unique engine seeds");
    if(!std::filesystem::create_directory(out))throw std::invalid_argument("Output must be new");
    PpoLearnerConfig config;config.seed=seed;config.policy.players=2;config.policy.hidden=64;
    config.parameters.epochs=4;config.parameters.minibatch=64;config.scenario=ScenarioConfig::make();
    *config.scenario=scenario();
    PpoLearner learner(config);const auto initial=learner.get_state();
    evaluate(learner.policy(),"sample",cases,out/"initial_sample.jsonl");
    if(initial!=learner.get_state())throw std::runtime_error("Initial evaluation changed learner");
    std::ofstream iterations(out/"iterations.jsonl");iterations<<std::setprecision(17);
    for(size_t update=0;update<512;++update){
      auto result=learner.train(256);
      iterations<<"{\"version\":"<<learner.version()<<",\"transitions\":"<<result.transitions<<",\"reward\":"<<result.reward<<",\"loss\":"<<result.update.loss
        <<",\"parameter_delta\":"<<result.update.parameter_delta<<",\"trajectory_sha256\":\""<<result.trajectory_sha256<<"\"}\n";
      if(update%64==63){iterations.flush();std::cerr<<"updates "<<update+1<<"/512\n";}
    }
    iterations.close();if(!iterations)throw std::runtime_error("Incomplete training log");
    learner.save(out/"model.fppo");const auto before=learner.get_state();
    for(const std::string mode:{"sample","argmax","uniform_random","builtin_ai"})evaluate(learner.policy(),mode,cases,out/(mode+".jsonl"));
    if(before!=learner.get_state())throw std::runtime_error("Final evaluation changed learner");
    std::cout<<"{\"passed\":true,\"seed\":"<<seed<<",\"version\":"<<learner.version()<<",\"transitions\":"<<learner.transitions()
      <<",\"episodes_per_strategy\":50,\"learned_players\":2,\"features_per_player\":115,\"fixed_ai_teammate\":false}\n";
  }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
