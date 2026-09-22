#include "game_load.hpp"
#include "game_env.hpp"
#include "gametask.hpp"
#include "frame_sync/engine_tcp_bridge.hpp"
#include <iostream>
#include <thread>
#include <fstream>
#include <cstdlib>
namespace fs = frame_sync;
unsigned assertions = 0;
void Require(bool value,const char* reason) {
 ++assertions; if(!value) throw std::runtime_error(reason);
}
int main(int argc,char** argv) {
 try {
  Require(argc==3,"Expected cancellation checkpoint and repetition");
  std::string target=argv[1];unsigned repeat=std::stoul(argv[2]),hits=0;
  unsigned outer=0,inner=0;
  { GameLoadScope first([&](std::string_view){++outer;});
    GameLoadCheckpoint("test");
    { GameLoadScope second([&](std::string_view){++inner;});GameLoadCheckpoint("test"); }
    std::thread unrelated([]{GameLoadCheckpoint("test");});unrelated.join();
    GameLoadCheckpoint("test");
  }
  GameLoadCheckpoint("test");
  Require(outer==2 && inner==1,"Load callback leaked across scope or thread ownership");
  const char* expected=std::getenv("EXPECTED_CORE_PATH");
  Require(expected,"Expected core was not pinned");std::ifstream maps("/proc/self/maps");std::string line;unsigned mapped=0;
  while(std::getline(maps,line))if(line.find("libfootball_engine.so")!=std::string::npos){
   Require(line.find(expected)!=std::string::npos,"Wrong runtime core");++mapped;
  }
  Require(mapped>0,"Runtime core mapping absent");
  GameEnv env;env.game_config.render=false;env.game_config.physics_steps_per_frame=fs::NativeMatchContract::kPhysicsSteps;
  auto scenario=fs::MakeNativeMatchScenario(fs::NativeMatchContract(42,1,2));
  env.prepare_game(*scenario);const auto context=env.context;const int tracker=context->tracker_disabled;
  bool cancelled=false;
  { GameLoadScope loading([&](std::string_view phase){
      if(phase==target && ++hits==repeat)throw GameLoadCancelled();
    });
    try{env.reset(*scenario,false);}catch(const GameLoadCancelled&){cancelled=true;}
  }
  Require(cancelled && hits==repeat,"Cancellation checkpoint was not reached");
  Require(GetGame()==nullptr,"Cancellation leaked the active environment");
  Require(env.context==context,"Cancellation destroyed the UI runtime before its owner joined");
  Require(!context->gameTask->GetMatch(),"Partial match survived cancellation");
  Require(!context->menuTask->GetMatchData(),"Queued match data survived cancellation");
  Require(context->tracker_disabled==tracker,"Cancellation leaked tracker nesting");
  bool rejected=false;try{env.get_info();}catch(const std::logic_error&){rejected=true;}
  Require(rejected,"Cancelled environment exposed an incomplete match");
  // Retry after both substantial animation work and a fully registered match.
  if(target=="animations.file" || target=="match.finalized"){
   env.reset(*scenario,false);env.state=game_running;
   auto engine=fs::MakeGameEnvCallbacks(&env);
   Require(engine.compute_hash()==1086847095508428874ULL,"Retry after cancellation changed initial state");
   engine.step_frame(std::vector<fs::SlotInput>(3,fs::SlotInput::Default()));
   Require(engine.compute_hash()==12693704928474537033ULL,"Retry after cancellation changed first frame");
  }
  env.close();env.close();Require(!env.context && GetGame()==nullptr,"Cancelled close did not finish");
  std::cout<<"{\"passed\":true,\"assertions\":"<<assertions<<",\"actual_gameenv\":true,\"cancelled\":true,\"skipped\":0}\n";
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
