// 2026-09-13: actual TCP disconnect/dead-ball replay and AI recovery.

#include "frame_sync/engine_tcp_bridge.hpp"
#include "frame_sync/native_match_replay.hpp"
#include <iostream>
#include <fstream>
#include <cmath>
#include <tuple>
namespace fs=frame_sync;
unsigned assertions=0,unavailable=0,recovered=0;
void Require(bool v,const char*m){++assertions;if(!v)throw std::runtime_error(m);}
using Recorded = std::tuple<float,float,unsigned,int,float,float>;
const Recorded tail[]={
#include "fixtures/native_bot_transition_tail_handfeel_20261002.inc"
};
const std::uint64_t semantic_hashes[]={
#include "fixtures/native_bot_transition_hashes_handfeel_20261002.inc"
};
const char replay_bytes[] =
#include "fixtures/native_bot_transition_replay_20260913.inc"
;
// 2026-09-13: match the entry declaration inherited from main.hpp.
// int main(){
int main(int argc, char** argv){
 try {
  const bool emit_reference =
      argc == 4 && std::string(argv[1]) == "--emit-reference";
  Require(argc == 1 || emit_reference, "Unexpected bot-selection arguments");
  std::ofstream hashes_output, tail_output;
  if (emit_reference) {
    hashes_output.open(argv[2]);
    tail_output.open(argv[3]);
    Require(hashes_output.is_open() && tail_output.is_open(),
            "Reference output could not be opened");
  }
  const std::string bytes(replay_bytes,sizeof(replay_bytes)-1);
  fs::NativeReplayPlayer replay;Require(replay.LoadReplay(bytes),"Native replay rejected");
  Require(replay.GetTotalFrames()==512,"Actual prefix changed");
  Require(std::size(semantic_hashes)==replay.GetTotalFrames(),"Semantic prefix oracle incomplete");
  Require(replay.contract()==fs::NativeMatchContract(42,1,1),"Native failure scenario changed");
  GameEnv env;env.game_config.render=false;env.game_config.physics_steps_per_frame=fs::NativeMatchContract::kPhysicsSteps;
  auto scenario=fs::MakeNativeMatchScenario(replay.contract());env.start_game(*scenario);env.state=game_running;
  auto engine=fs::MakeGameEnvCallbacks(&env);auto observe=fs::MakeGameEnvBotObserver(&env,1,1);
  for(unsigned i=0;i<replay.GetTotalFrames();++i){
   auto frame=replay.GetFrameAt(i);Require(frame.has_value(),"Prefix frame missing");
   // The first recorded manual turn must reach the same player within this step.
   int manual_player=-1;
   float manual_vx_before=0.f;
   if(i==123){
    auto before=env.get_info();
    manual_player=before.left_controllers[0].controlled_player;
    Require(frame->inputs[0].dir_x>.9f && manual_player>=0,"First manual turn changed");
    manual_vx_before=before.left_team[manual_player].player_direction[0];
   }
   engine.step_frame(frame->inputs);
   if(i==123){
    auto after=env.get_info();
    Require(after.left_controllers[0].controlled_player==manual_player,"Manual turn changed selected player");
    Require(after.left_team[manual_player].player_direction[0]-manual_vx_before>=.1f,
            "Manual turn waited for the previous animation");
   }
   const auto hash = engine.compute_hash();
   if (emit_reference)
    hashes_output << "0x" << std::hex << hash << "ULL,\n" << std::dec;
   else
    Require(hash==semantic_hashes[i],"Semantic authority diverged");
  }
  fs::BotTakeoverManager bots(fs::NativeMatchContract::kHz);bots.Takeover(0,0);
  bool seen_unavailable=false;
  unsigned opponent_restart_wait_frames=0;
  for(const auto&[x,y,buttons,owned,px,py]:tail){
   const auto before=env.get_info();
   const auto snapshot=observe();
   const auto bot_input=bots.GenerateInput(0,snapshot);
   const int selected=before.left_controllers[0].controlled_player;
   Require(bool(snapshot.unavailable_slots & 1)==(selected==-1),"Snapshot availability differs from real selection");
   if(selected==-1){
    seen_unavailable=true;
    ++unavailable;
    Require(bot_input.dir_x==0 && bot_input.dir_y==0 && bot_input.buttons==0,
            "Unavailable slot received gameplay");
   }else if(seen_unavailable){
    ++recovered;
    Require(fs::IsValidSlotInput(bot_input),"Recovered bot input invalid");
    if(!bot_input.dir_x && !bot_input.dir_y && !bot_input.buttons){
     Require(snapshot.tactics && snapshot.tactics->set_piece &&
             snapshot.tactics->restart_team==1,
             "Recovered bot stayed idle outside an opponent restart");
     ++opponent_restart_wait_frames;
    }
   }
   const std::array inputs{fs::SlotInput{x,y,static_cast<std::uint16_t>(buttons)},fs::SlotInput::Default()};
   engine.step_frame(inputs);
   auto info=env.get_info();Require(info.left_controllers.size()==MAX_PLAYERS,"Controller disappeared");
   const int actual_owned=info.left_controllers[0].controlled_player;
   if(emit_reference){
    const float actual_x=actual_owned>=0 ? info.left_team[actual_owned].player_position[0] : 0.f;
    const float actual_y=actual_owned>=0 ? info.left_team[actual_owned].player_position[1] : 0.f;
    tail_output << "{" << std::hexfloat << x << "f," << y << "f,"
                << std::dec << buttons << "," << actual_owned << ","
                << std::hexfloat << actual_x << "f," << actual_y << "f},\n"
                << std::defaultfloat;
   }else{
    Require(actual_owned==owned,"Recorded selection diverged");
    if(owned>=0){
     const auto&p=info.left_team[owned].player_position;
     Require(std::abs(p[0]-px)<.0001 && std::abs(p[1]-py)<.0001,"Recorded position diverged");
    }
   }
  }
  Require(unavailable>0 && recovered>0,"Bot did not resume after real selection recovery");
  std::cout<<"{\"passed\":true,\"assertions\":"<<assertions<<",\"prefix_frames\":512,\"recorded_tail_frames\":"<<std::size(tail)
           <<",\"unavailable_frames\":"<<unavailable<<",\"skipped\":0,\"actual_gameenv\":true,\"recovered_frames\":"<<recovered
           <<",\"opponent_restart_wait_frames\":"<<opponent_restart_wait_frames<<"}\n";
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
}
