// 2026-09-13: absolute-deadline oracle plus replay of actual XTEST-confirmed authority.
#include "frame_sync/native_loop.hpp"
// 2026-09-13: reconstruct actual product replay from its own scenario and cadence.
// #include "frame_sync/default_scenario.hpp"
#include "frame_sync/native_match_scenario.hpp"
#include "frame_sync/native_match_replay.hpp"
#include "frame_sync/engine_bridge.hpp"
#include "frame_sync/replay_system.hpp"
#include <array>
#include <fstream>
#include <iostream>
#include <iterator>
namespace {
namespace fs = frame_sync;
size_t assertions=0, clock_events=0, replay_frames=0;
void Require(bool value,const char* reason) {
  ++assertions;if (!value) throw std::runtime_error(reason);
}
template<class Error,class Function> void Throws(Function f) {
  bool caught=false;try { f(); } catch (const Error&) { caught=true; }
  Require(caught,"Expected clock rejection missing");
}
void Clocks() {
  for (const auto rates : {std::array{10,60},std::array{25,144},std::array{50,60},std::array{1000,1}}) {
    int64_t now=100001123;
    fs::NativeLoopClock clock(now,rates[0],rates[1]);
    std::array<int64_t,3> next{now,now,now};
    std::array<int64_t,3> period{4000000,1000000000/rates[0],1000000000/rates[1]};
    uint64_t random=1147381;
    for (int event=0;event<10000;++event) {
      random=random*6364136223846793005ULL+1;
      now+=static_cast<int64_t>((random>>32)%20000001);
      if (event%79==0) { clock.RestartLogic(now);next[1]=now; }
      std::array<bool,3> expected{};
      // Enumerate elapsed deadlines; independent of production remainder arithmetic.
      for (size_t i=0;i<3;++i) while(next[i]<=now) { expected[i]=true;next[i]+=period[i]; }
      Require(clock.PollDue(now)==expected[0],"Polling deadline drifted");
      Require(clock.LogicDue(now)==expected[1],"Logic deadline drifted");
      Require(clock.RenderDue(now)==expected[2],"Display deadline drifted");
      Require(!clock.PollDue(now),"Repeated wall opportunity polled twice");
      Require(!clock.LogicDue(now),"Repeated wall opportunity stepped twice");
      Require(!clock.RenderDue(now),"Repeated wall opportunity drew twice");
      Require(clock.Next(false,false)==next[0],"Disabled work affects wait");
      Require(clock.Next(true,false)==std::min(next[0],next[1]),"Headless wait differs");
      Require(clock.Next(false,true)==std::min(next[0],next[2]),"Paused wait differs");
      Require(clock.Next(true,true)==std::min({next[0],next[1],next[2]}),"Active wait differs");
      ++clock_events;
    }
  }
  for (int invalid : {-1,0,1001})
    Throws<std::invalid_argument>([&]{ fs::NativeLoopClock clock(0,invalid,60); });
  Throws<std::invalid_argument>([]{fs::NativeLoopClock clock(-1,10,60);});
  fs::NativeLoopClock clock(0,10,60);
  Require(clock.PollDue(100),"Initial poll missing");
  Throws<std::invalid_argument>([&]{clock.PollDue(99);});
  Require(!clock.PollDue(100),"Rejected rewind altered next poll");
  Throws<std::invalid_argument>([&]{clock.RestartLogic(99);});
  Require(clock.LogicDue(100),"Rejected restart altered logic");
  fs::NativeLoopClock exhausted(INT64_MAX,10,60);
  Throws<std::overflow_error>([&]{exhausted.PollDue(INT64_MAX);});
  Require(exhausted.Next(false,false)==INT64_MAX,"Exhausted clock wrapped");
// 2026-09-13: verify conservation of simulation time under long and repeated render stalls.
//   Require(fs::NativeLoopClock::Period(60)==16666666,"Render uses truncated milliseconds");
  Require(fs::NativeLoopClock::Period(60)==16666666,"Render uses truncated milliseconds");
  // Independent fixed-time ledger: variable render stalls preserve total steps;
  // an eight-step owner budget returns to polling without forgiving old debt.
  for (const int hz : {10,50,1000}) {
    fs::NativeLoopClock fixed(0,hz,60);
    const int64_t period=1000000000/hz;
    int64_t now=0,consumed=0;
    for (int stall=0;stall<1000;++stall) {
      now += (stall%11+1)*17000000LL;
      const int64_t expected=now/period+1;
      while (consumed < expected) {
        Require(fixed.PollDue(now) || fixed.Next(false,false)>now,"Catchup failed to poll");
        for (int work=0;work<8 && fixed.FixedLogicDue(now);++work) ++consumed;
        Require(consumed<=expected,"Fixed simulation stepped into future");
        Require(fixed.LogicPending(now)==(consumed<expected),"Fixed debt differs from elapsed time");
      }
      Require(consumed==expected && !fixed.FixedLogicDue(now),"Slow render lost fixed time");
    }
    const auto restart=now+5000000000LL;
    fixed.RestartLogic(restart);  // a paused interval creates no simulation debt
    Require(fixed.FixedLogicDue(restart) && !fixed.FixedLogicDue(restart),"Resume replayed paused time");
    Require(!fixed.LogicPending(restart),"Resume retained pause debt");
    Throws<std::invalid_argument>([&]{fixed.FixedLogicDue(restart-1);});
    Require(!fixed.FixedLogicDue(restart),"Rejected rewind altered fixed deadline");
  }
  fs::NativeLoopClock fixed_limit(INT64_MAX,50,60);
  Throws<std::overflow_error>([&]{fixed_limit.FixedLogicDue(INT64_MAX);});
  Require(fixed_limit.Next(true,false)==INT64_MAX,"Fixed overflow wrapped deadline");
}
std::string Read(const std::filesystem::path& file) {
  std::ifstream input(file,std::ios::binary);
  Require(bool(input),"Saved actual replay missing");
  return {std::istreambuf_iterator<char>(input),std::istreambuf_iterator<char>()};
}
bool Same(const fs::ReplayFrame& a,const fs::ReplayFrame& b) {
  if (a.frame_number!=b.frame_number || a.state_hash!=b.state_hash || a.inputs.size()!=b.inputs.size())
    return false;
  for(size_t i=0;i<a.inputs.size();++i)
    if(std::memcmp(&a.inputs[i],&b.inputs[i],sizeof(fs::SlotInput))!=0)return false;
  return true;
}
void Replay(const std::filesystem::path& directory) {
// 2026-09-13: require the native product envelope on current executable output.
//   fs::ReplayPlayer prefix,full;
  fs::NativeReplayPlayer prefix,full;
  Require(prefix.LoadReplay(Read(directory/"midmatch-replay.bin")),"Native player rejected midmatch prefix");
  Require(full.LoadReplay(Read(directory/"replay_42.bin")),"Native player rejected final replay");
  Require(prefix.GetTotalFrames()>0 && full.GetTotalFrames()>prefix.GetTotalFrames(),"Recording did not continue");
  Require(full.GetMetadata().seed==42 && full.GetMetadata().num_slots==2 &&
          full.GetMetadata().scenario=="default_11v11","Fixture session differs");
  Require(prefix.GetMetadata().seed==full.GetMetadata().seed &&
          prefix.GetMetadata().num_slots==full.GetMetadata().num_slots &&
          prefix.GetMetadata().scenario==full.GetMetadata().scenario,"Prefix metadata changed");
// 2026-09-13: validated native metadata selects the replay simulation; no external cadence guess.
//   // The legacy replay lacks team/cadence metadata. These are pinned by the actual XTEST fixture.
//   GameEnv env;
//   env.game_config.render=false;env.game_config.physics_steps_per_frame=10;
//   auto scenario=fs::MakeDefaultScenario(1,1,42);
  Require(prefix.contract()==full.contract() && full.contract()==fs::NativeMatchContract(42,1,1),
          "Native product replay contract changed");
  GameEnv env;
  env.game_config.render=false;env.game_config.physics_steps_per_frame=fs::NativeMatchContract::kPhysicsSteps;
  auto scenario=fs::MakeNativeMatchScenario(full.contract());
  env.start_game(*scenario);env.state=game_running;
  auto callbacks=fs::MakeGameEnvCallbacks(&env);
  bool move=false,shot=false;
  for(size_t i=0;i<full.GetTotalFrames();++i) {
    const auto frame=full.GetFrameAt(i);
    Require(frame.has_value() && frame->frame_number==i,"Confirmed replay frame omitted");
    if (i<prefix.GetTotalFrames()) Require(Same(*prefix.GetFrameAt(i),*frame),"Saved prefix was changed");
    callbacks.step_frame(frame->inputs);++replay_frames;
    Require(callbacks.compute_hash()==frame->state_hash,"Actual recorded authority hash failed replay");
    Require(GetGame()==nullptr,"Replay left environment selected");
    move|=frame->inputs[0].dir_x==1 && (frame->inputs[0].buttons&512);
    shot|=(frame->inputs[0].buttons&8)!=0;
    if(i+1==prefix.GetTotalFrames())
      Require(callbacks.compute_hash()==prefix.GetMetadata().final_state_hash,"Midmatch final hash failed replay");
  }
  Require(callbacks.compute_hash()==full.GetMetadata().final_state_hash,"Final replay hash differs");
  Require(move && shot,"Physical nonzero inputs never confirmed");
  env.close();Require(GetGame()==nullptr,"Replay close left environment selected");
}
}
int main(int argc,char** argv) {
  try {
    Require(argc==2,"Actual window evidence directory required");
    Clocks();Replay(std::filesystem::path(argv[1])/"tcp");Replay(std::filesystem::path(argv[1])/"udp");
    std::cout<<"{\"passed\":true,\"skipped\":0,\"assertions\":"<<assertions
             <<",\"clock_events\":"<<clock_events<<",\"replay_frames\":"<<replay_frames
             <<",\"actual_gameenv\":true,\"device_latency_acceptance\":false}\n";
    return 0;
  } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
