#include "game_env.hpp"
#include "frame_sync/native_match_scenario.hpp"
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <thread>
int main(int argc,char**) {
 try {
  const char* expected=std::getenv("EXPECTED_CORE_PATH");
  if(!expected)throw std::runtime_error("Expected core missing");
  std::ifstream maps("/proc/self/maps");std::string line;unsigned found=0;
  while(std::getline(maps,line))if(line.find("libfootball_engine.so")!=std::string::npos){
   if(line.find(expected)==std::string::npos)throw std::runtime_error("Wrong core mapping");++found;
  }
  if(!found)throw std::runtime_error("No core mapping");
  GameEnv first,second;
  auto scenario=frame_sync::MakeNativeMatchScenario(frame_sync::NativeMatchContract(42,1,2));
  for(auto* env:{&first,&second}){
   env->game_config.render=false;
   env->game_config.physics_steps_per_frame=frame_sync::NativeMatchContract::kPhysicsSteps;
   env->start_game(*scenario);env->state=game_running;env->tracker_setup(1,1);
  }
  std::atomic<unsigned> completed{0},entered{0};
  std::cout<<"TRACKER_RENDEZVOUS_ENTER"<<std::endl;
  std::thread watchdog([&]{
   const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
   while(completed.load()<2 && std::chrono::steady_clock::now()<deadline)
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
   if(completed.load()!=2){
    std::cerr<<"TRACKER_OWNER_DEADLOCK entered="<<entered.load()<<std::endl;
    std::_Exit(42);  // Explicit failed-witness terminal outcome, not successful cleanup.
   }
  });
  auto work=[&](GameEnv& env){
   {ContextHolder owner(&env);++entered;GetTracker()->verify(20260914,"loading-tracker-contract");}
   if(GetGame()!=nullptr)std::_Exit(43);
   ++completed;
  };
  std::thread a([&]{work(first);}),b([&]{work(second);});
  a.join();b.join();watchdog.join();
  if(completed.load()!=2)throw std::runtime_error("Paired comparison did not finish");
  first.close();second.close();
  std::cout<<"{\"passed\":true,\"paired_tracker\":true,\"workers\":2,\"skipped\":0}\n";
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
