#pragma once
#include "training/deterministic_inference.hpp"
#include "training/cooperation_metrics.hpp"
#include "training/scenario_sampling.hpp"
#include "training/categorical_policy.hpp"
#include "frame_sync/default_scenario.hpp"
#include "frame_sync/state_hash.hpp"
#include "frame_sync/rl_training/checkpoint_file.hpp"
#include <charconv>
#include <chrono>
#include <fstream>
#include <iostream>
#include <limits>
#include <set>

namespace football::training::inference {
inline std::string Digest(std::string_view bytes) {
  frame_sync::SHA256 h;h.update(reinterpret_cast<const uint8_t*>(bytes.data()),bytes.size());
  uint8_t out[32];h.finalize(out);std::string result;const char* hex="0123456789abcdef";
  for(auto x:out){result+=hex[x>>4];result+=hex[x&15];}return result;
}
inline void Require(bool value,const char* message){if(!value)throw std::invalid_argument(message);}
inline std::string Read(const std::string& path,size_t limit) {
  auto result=ReadCheckpointFile(path,limit);
  if(!result)throw std::runtime_error(std::string("Inference read failed: ")+result.stage);
  return std::string(result.bytes.data(),result.bytes.size());
}
inline void Save(const std::string& path,const std::string& bytes,size_t limit) {
  auto result=SaveCheckpointFile(std::span<const char>(bytes.data(),bytes.size()),path,limit);
  if(!result)throw std::runtime_error(std::string("Inference write failed: ")+result.stage);
}
inline std::string Seal(const std::string& magic,const std::string& payload){return magic+'\n'+Digest(payload)+'\n'+payload;}
inline std::string Unseal(const std::string& bytes,const std::string& magic) {
  Require(bytes.starts_with(magic+'\n')&&bytes.size()>=magic.size()+66,"Invalid inference envelope/version");
  const auto payload=bytes.substr(magic.size()+66);
  Require(bytes[magic.size()+65]=='\n'&&bytes.substr(magic.size()+1,64)==Digest(payload),"Inference checksum mismatch");
  return payload;
}
inline uint64_t Number(std::string_view text,uint64_t maximum) {
  uint64_t value=0;auto p=std::from_chars(text.data(),text.data()+text.size(),value);
  Require(p.ec==std::errc{}&&p.ptr==text.data()+text.size()&&value<=maximum,"Invalid inference numeric option");return value;
}
struct PortablePolicy {
  uint64_t seed=0;std::string checkpoint_sha,sha;
  CategoricalPolicy policy;
  explicit PortablePolicy(const std::string& path):policy(PolicySpec{},0) {
    const auto bytes=Read(path,2*1024*1024);sha=Digest(bytes);
    std::istringstream in(Unseal(bytes,"FPOL1"));std::string task,extra;uint32_t version,rng;size_t hidden,count;
    Require(bool(in>>task>>version>>rng>>seed>>hidden>>count>>checkpoint_sha),"Invalid portable policy metadata");
    Require(task=="two_on_one_sticky_v1"&&version==kCategoricalPolicyVersion&&rng==kPolicyRngVersion,
            "Unsupported portable policy task/version");
    Require(checkpoint_sha.size()==64&&checkpoint_sha.find_first_not_of("0123456789abcdef")==std::string::npos,"Invalid policy provenance");
    PolicySpec spec;spec.hidden=hidden;spec.validate();CategoricalPolicy proposed(spec,0);
    Require(count==proposed.parameters().size(),"Portable policy parameter count mismatch");
    std::vector<double> parameters(count);
    for(double& value:parameters)Require(bool(in>>value)&&std::isfinite(value),"Invalid portable policy weight");
    Require(!(in>>extra),"Trailing portable policy data");proposed.set_parameters(parameters);policy=std::move(proposed);
  }
};
inline void ExportPolicy(const CategoricalPolicy& policy,uint64_t seed,const std::string& checkpoint,const std::string& path) {
  const auto& spec=policy.spec();
  Require(spec.players==1&&spec.features==115&&spec.fixed_positions&&!spec.builtin_ai_action,"Portable inference requires one fixed simple115 19-action policy");
  std::ostringstream payload;payload<<std::setprecision(17)<<"two_on_one_sticky_v1 "<<kCategoricalPolicyVersion<<' '<<kPolicyRngVersion<<' '
    <<seed<<' '<<spec.hidden<<' '<<policy.parameters().size()<<' '<<Digest(checkpoint)<<'\n';
  for(double p:policy.parameters())payload<<p<<'\n';
  Save(path,Seal("FPOL1",payload.str()),2*1024*1024);
}
struct Case {size_t index,group;uint32_t seed;uint64_t action_seed;float ax,ay,tx,ty,dx,dy;};
inline std::vector<Case> Cases(const std::string& bytes) {
  Require(!bytes.empty()&&bytes.size()<=128*1024,"Inference case file budget");
  std::istringstream input(bytes);std::vector<Case> cases;std::string line;
  while(std::getline(input,line)) {
    std::istringstream in(line);Case c{};int legacy;std::string extra;
    Require(bool(in>>c.index>>c.group>>legacy>>c.seed>>c.action_seed>>c.ax>>c.ay>>c.tx>>c.ty>>c.dx>>c.dy)&&!(in>>extra),"Malformed inference case");
    Require(c.index==cases.size()&&cases.size()<400&&c.group<5&&legacy==0&&c.seed<=2000000000,"Invalid inference case identity");
    Require(std::isfinite(c.ax+c.ay+c.tx+c.ty+c.dx+c.dy)&&c.ax>=.25f&&c.ax<=.72f&&c.tx>=.25f&&c.tx<=.94f&&c.dx>=.25f&&c.dx<=.95f&&std::abs(c.ay)<=.4f&&std::abs(c.ty)<=.4f&&std::abs(c.dy)<=.4f,"Inference geometry outside bounds");
    cases.push_back(c);
  }
  Require(!cases.empty(),"Empty inference case file");return cases;
}
struct Episode {
  size_t steps=0;double reward=0;int score=0;bool terminated=false;
  CooperationMetrics metrics;BalancedInference controller;PolicyRng actions;
};
inline void Print(const Case& c,const ScenarioConfig& scene,const Episode& e) {
  std::cout<<std::setprecision(17)<<"{\"index\":"<<c.index<<",\"group\":"<<c.group<<",\"engine_seed\":"<<c.seed
    <<",\"start_x\":"<<scene.ball_position.coords[0]<<",\"start_y\":"<<scene.ball_position.coords[1]
    <<",\"steps\":"<<e.steps<<",\"terminated\":"<<(e.terminated?"true":"false")
    <<",\"truncated\":"<<(!e.terminated&&e.steps==256?"true":"false")
    <<",\"reward\":"<<e.reward<<",\"controlled_score_delta\":"<<e.score
    <<",\"pass_requests\":"<<e.metrics.pass_requests<<",\"completed_passes\":"<<e.metrics.completed_passes
    <<",\"teammate_transfers\":"<<e.metrics.teammate_transfers<<",\"turnovers\":"<<e.metrics.turnovers<<"}\n";
}
// An inference session is distinct from an FPPO training checkpoint. Native
// snapshots still enforce the current source/build/ABI/resource identity.
inline int Run(int argc,char** argv) {
  std::string mode,policy_path,cases_path,state_in,state_out;uint64_t budget=102400;
  std::set<std::string> seen;
  for(int i=1;i<argc;++i) {
    std::string option=argv[i];Require(seen.insert(option).second,"Duplicate inference option");
    Require(i+1<argc,"Missing inference option value");std::string value=argv[++i];
    if(option=="--inference-mode")mode=value;
    else if(option=="--policy")policy_path=value;
    else if(option=="--inference-cases")cases_path=value;
    else if(option=="--inference-state-in")state_in=value;
    else if(option=="--inference-state-out")state_out=value;
    else if(option=="--inference-decisions")budget=Number(value,102400);
    else throw std::invalid_argument("Unknown or training-only inference option");
  }
  Require(mode=="balanced"||mode=="argmax"||mode=="sample"||mode=="uniform_random"||mode=="builtin_ai","Unknown inference mode");
  Require(!policy_path.empty()&&!cases_path.empty()&&budget>0,"Inference requires policy, cases and positive decision budget");
  Require(state_out.empty()||(state_out!=policy_path&&state_out!=cases_path),"Inference output would overwrite an input");
  PortablePolicy model(policy_path);const auto cases_bytes=Read(cases_path,128*1024);auto cases=Cases(cases_bytes);
  const auto cases_sha=Digest(cases_bytes);size_t index=0;Episode episode;std::string native;
  if(!state_in.empty()) {
    std::istringstream in(Unseal(Read(state_in,32*1024*1024),"FIFS1"));std::string policy_sha,case_sha,saved_mode,control;
    uint64_t rng;size_t native_size;auto& m=episode.metrics;
    Require(bool(in>>policy_sha>>case_sha>>saved_mode>>index>>episode.steps>>episode.reward>>episode.score>>rng
      >>m.pass_requests>>m.completed_passes>>m.teammate_transfers>>m.turnovers>>m.last_team>>m.last_player>>m.pending_player>>m.pending_age),"Malformed inference session");
    Require(policy_sha==model.sha&&case_sha==cases_sha&&saved_mode==mode,"Inference session policy/cases/mode mismatch");
    Require(index<cases.size()&&episode.steps<256&&std::isfinite(episode.reward)&&std::abs(episode.score)<=256,"Invalid inference session counters");
    Require(m.completed_passes<=m.pass_requests&&m.pass_requests<=episode.steps&&m.teammate_transfers<=episode.steps+1&&m.turnovers<=episode.steps+1&&m.pending_age<=31&&m.last_team>=-1&&m.last_team<=1&&m.last_player>=-1&&m.last_player<=2&&(m.pending_player==-1||m.pending_player==1),"Invalid inference cooperation state");
    in.ignore(std::numeric_limits<std::streamsize>::max(),'\n');Require(bool(std::getline(in,control)),"Missing inference controller state");
    episode.controller.set_state(control);episode.actions.set_state(rng);
    Require(bool(in>>native_size)&&native_size>0&&native_size<32*1024*1024,"Invalid inference native size");
    Require(in.get()=='\n',"Invalid inference native boundary");
    native.assign(std::istreambuf_iterator<char>(in),{});Require(native.size()==native_size,"Inference native length mismatch");
  }
  const auto start=std::chrono::steady_clock::now();uint64_t decisions=0,emitted=0;
  NativeTrainingEnv env(160,90,true,true,false,false);
  for(;index<cases.size();++index) {
    const auto& c=cases[index];auto scene=frame_sync::MakeDefaultScenario(1,0,42);ConfigureTwoOnOne(*scene);
    scene->deterministic=true;scene->game_engine_random_seed=c.seed;
    scene->left_team[1]=FormationEntry(c.ax,c.ay,e_PlayerRole_CF,false,true);
    scene->left_team[2]=FormationEntry(c.tx,c.ty,e_PlayerRole_CF,false,true);
    scene->right_team[1]=FormationEntry(c.dx,c.dy,e_PlayerRole_CB,false,false);
    scene->ball_position=blunted::Vector3(c.ax+.02f,c.ay,0);
    auto observation=env.reset(*scene,10);
    if(!native.empty()){env.set_state(native);observation=env.current_observation();native.clear();}
    else {episode=Episode{};episode.actions.set_state(c.action_seed);episode.metrics.observe(env.possession());}
    while(episode.steps<256) {
      if(decisions==budget) {
        Require(!state_out.empty(),"Decision budget exhausted; provide --inference-state-out");
        std::ostringstream payload;auto& m=episode.metrics;
        payload<<std::setprecision(17)<<model.sha<<' '<<cases_sha<<' '<<mode<<' '<<index<<' '<<episode.steps<<' '<<episode.reward<<' '<<episode.score<<' '<<episode.actions.state()<<' '
          <<m.pass_requests<<' '<<m.completed_passes<<' '<<m.teammate_transfers<<' '<<m.turnovers<<' '<<m.last_team<<' '<<m.last_player<<' '<<m.pending_player<<' '<<m.pending_age<<'\n'
          <<episode.controller.get_state()<<'\n';
        const auto bytes=env.get_state();payload<<bytes.size()<<'\n'<<bytes;Save(state_out,Seal("FIFS1",payload.str()),32*1024*1024);
        std::cout<<"{\"summary\":true,\"complete\":false,\"episodes\":"<<emitted<<",\"decisions\":"<<decisions<<"}\n";return 0;
      }
      int action;
      if(mode=="builtin_ai")action=19;
      else if(mode=="uniform_random")action=episode.actions.index(19);
      else {
        auto view=CooperationObservation(observation,episode.metrics.completed_passes>0,env.sticky_actions());
        if(mode=="balanced"){
          const auto output=model.policy.forward(view);CategoricalDistribution distribution(output.logits,1,19);
          action=episode.controller.choose(distribution.probabilities());
        }else action=model.policy.decide(view,episode.actions,mode=="argmax").actions.front();
      }
      episode.metrics.action(env.possession(),action);
      auto t=env.step(std::array<int,2>{action,19});episode.metrics.observe(env.possession());
      episode.reward+=t.rewards.front();episode.score+=t.score_reward;++episode.steps;++decisions;
      episode.terminated=t.terminated;observation=std::move(t.observations);if(t.terminated)break;
    }
    Print(c,*scene,episode);++emitted;
  }
  env.close();const double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
  std::cout<<std::setprecision(17)<<"{\"summary\":true,\"complete\":true,\"episodes\":"<<emitted<<",\"decisions\":"<<decisions
    <<",\"wall_seconds\":"<<seconds<<",\"policy_sha256\":\""<<model.sha<<"\"}\n";return 0;
}
} // namespace football::training::inference
