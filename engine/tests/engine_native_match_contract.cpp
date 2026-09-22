// 2026-09-13: independent wire, fixed-grid, bot time and actual engine replay contracts.
#include "frame_sync/native_match_scenario.hpp"
#include "frame_sync/native_match_replay.hpp"
#include "frame_sync/engine_bridge.hpp"
// 2026-09-13: test input publication and readback against an independent map oracle.
// #include "frame_sync/bot_takeover.hpp"
#include "frame_sync/bot_takeover.hpp"
#include "frame_sync/native_input_publication.hpp"
#include <map>
#include <iostream>
namespace {
namespace fs=frame_sync;
size_t assertions=0,engine_frames=0,clock_events=0;
void Require(bool value,const char* reason) { ++assertions;if(!value)throw std::runtime_error(reason); }
template<class Error,class F> void Throws(F&& f) {
  bool caught=false;try{f();}catch(const Error&){caught=true;}Require(caught,"Expected rejection missing");
}
void Wire() {
  const std::array<uint8_t,18> hello{64,70,78,65,84,1,0,0,50,0,50,0,2,0,16,39,0,0};
  Require(fs::NativeMatchContract::IsHello(hello),"Independent native hello differs");
  for(size_t i=0;i<hello.size();++i)for(unsigned bit=0;bit<8;++bit) {
    auto altered=hello;altered[i]^=1u<<bit;
    Require(!fs::NativeMatchContract::IsHello(altered),"Invalid hello admitted");
  }
  for(size_t n=0;n<hello.size();++n)Require(!fs::NativeMatchContract::IsHello({hello.data(),n}),"Partial hello admitted");
  for(uint16_t left=0;left<=11;++left)for(uint16_t right=0;right<=11;++right) {
    if(!left&&!right)continue;
    const fs::NativeMatchContract contract(0x12345678,left,right);
    auto bytes=contract.Packet();
    Require(bytes[18]==0x78 && bytes[19]==0x56 && bytes[20]==0x34 && bytes[21]==0x12,"Seed byte order");
    Require(bytes[22]==left && bytes[23]==right && bytes[24]==1 && bytes[28]==0x98 && bytes[29]==0x3a,"Scenario byte order");
    fs::NativeMatchContract decoded;
    Require(fs::NativeMatchContract::Decode(bytes,66,decoded) && decoded==contract,"Session roundtrip");
    for(size_t n=0;n<bytes.size();++n) {
      Require(!fs::NativeMatchContract::Decode({bytes.data(),n},66,decoded),"Partial session admitted");
      Require(decoded==contract,"Rejected session changed state");
    }
    for(size_t i=0;i<18;++i) {
      auto altered=bytes;altered[i]^=1;
      Require(!fs::NativeMatchContract::Decode(altered,66,decoded) && decoded==contract,"Wrong family or cadence admitted");
    }
    Require(!fs::NativeMatchContract::Decode(bytes,65,decoded),"Session accepted as Ready");
    bytes=contract.Packet(65);
    Require(fs::NativeMatchContract::Decode(bytes,65,decoded) && decoded==contract,"Ready roundtrip");
    auto scenario=fs::MakeNativeMatchScenario(contract);
    Require(scenario->game_duration==15000 && scenario->left_agents==left &&
            scenario->right_agents==right && scenario->game_engine_random_seed==0x12345678,"Scenario identity");
  }
  Throws<std::invalid_argument>([]{fs::NativeMatchContract(42,0,0);});
  Throws<std::invalid_argument>([]{fs::NativeMatchContract(42,12,1);});
  Throws<std::invalid_argument>([]{fs::NativeMatchContract{}.Packet(64);});
}
void Clock() {
  using namespace std::chrono;
  using Time=fs::NativeFrameDeadline::Time;
  auto now=Time{}+nanoseconds(1234567);auto expected=now+milliseconds(20);
  fs::NativeFrameDeadline clock(now);
  uint64_t random=123981;
  for(int i=0;i<10000;++i) {
    Require(clock.deadline()==expected,"Authority deadline drifted");
    const auto saved=clock.deadline();
    Throws<std::invalid_argument>([&]{clock.Advance(saved-nanoseconds(1));});
    Require(clock.deadline()==saved,"Rejected clock changed grid");
    random=random*6364136223846793005ULL+1;
    now=expected+nanoseconds((random>>32)%100000001);
    do { expected+=milliseconds(20); } while(expected<=now); // independent enumeration
    clock.Advance(now);++clock_events;
  }
  Throws<std::invalid_argument>([]{fs::NativeFrameDeadline clock(Time{}-nanoseconds(1));});
  Throws<std::overflow_error>([]{fs::NativeFrameDeadline clock(Time::max());});
  fs::NativeFrameDeadline end(Time::max()-milliseconds(21));
  const auto saved=end.deadline();
  Throws<std::overflow_error>([&]{end.Advance(Time::max());});
  Require(end.deadline()==saved,"Overflow changed last deadline");
}
void Bots() {
  for(int hz:{10,50})for(bool attack:{false,true}) {
    fs::BotTakeoverManager bots(hz);bots.Takeover(0,0);
    fs::BotGameSnapshot snapshot;
    snapshot.num_slots=1;snapshot.ball_x=attack?90.f:-95.f;
    snapshot.player_positions={snapshot.ball_x,0.f};
    const unsigned button=1u<<(attack?3:0);
    const int interval=(attack?3:4)*hz;
    for(int frame=0;frame<=2*interval;++frame)
      Require(bool(bots.GenerateInput(0,snapshot).buttons&button)==(frame%interval==0),"Bot cooldown changed simulation duration");
    bots.Handback(0);Require(bots.GenerateInput(0,snapshot)==fs::SlotInput::Default(),"Bot handback retained action");
  }
  Throws<std::invalid_argument>([]{fs::BotTakeoverManager bots(0);});
}
std::string Serialize(const fs::ReplayRecorder& recorder,fs::NativeMatchContract contract) {
  fs::NativeReplayView view(recorder,contract);std::string bytes;
  const auto written=view.SerializeTo([&](std::string_view chunk){bytes.append(chunk);});
  Require(written==bytes.size() && written==view.GetSerializedBytes(),"Replay writer accounting");
  return bytes;
}
// 2026-09-13: a stalled renderer must neither retarget committed frames nor repeat a short edge.
// void Engine() {
void Publication() {
  fs::LocalInputHistory history;
  std::map<fs::frame_id_t,fs::SlotInput> expected;
  size_t samples=0,sends=0;
  for(uint32_t frame=0;frame<10000;++frame) {
    while(!expected.empty() && expected.begin()->first<frame)expected.erase(expected.begin());
    const uint32_t next=frame+(frame%7==0?3:0);
    const uint32_t target=next>frame+1?next:frame+1;
    const bool fresh=!expected.contains(target);
    const fs::SlotInput proposed{frame%2?1.f:-1.f,0.f,static_cast<uint16_t>(frame%5?512:8)};
    const auto old_samples=samples,old_sends=sends;
    auto sample=[&](uint32_t){++samples;return proposed;};
    auto send=[&](uint32_t at,const fs::SlotInput& input) {
      ++sends;Require(at==target && input==proposed,"Input published for wrong authority opportunity");return true;
    };
    Require(fs::PublishNativeInput(history,frame,frame,next,sample,send)==target,"Input target differs from oracle");
    if(fresh)expected.emplace(target,proposed);
    Require(samples==old_samples+fresh && sends==old_sends+fresh,"Published input consumed or sent twice");
    Require(history.Find(target)==expected.at(target),"Prediction changed sent input");
    Require(fs::PublishNativeInput(history,frame,frame,next,sample,send)==target,"Repeated wait moved input");
    Require(samples==old_samples+fresh && sends==old_sends+fresh,"Repeated wait consumed another edge");
    const auto before=history.size();
    Require(!history.Find(frame+1024) && history.size()==before,"Missing input lookup allocates history");
    for(const auto& [at,input]:expected)Require(history.Find(at)==input,"Future history was evicted before confirmation");
  }
  const auto size=history.size();
  Throws<std::overflow_error>([]{fs::NativeInputTarget(UINT32_MAX,0);});
  Throws<std::overflow_error>([]{fs::NativeInputTarget(0,UINT32_MAX);});
  Require(history.size()==size,"Rejected schedule mutated input");
  fs::LocalInputHistory failed;
  Throws<std::runtime_error>([&]{
    fs::PublishNativeInput(failed,0,0,0,[](uint32_t){return fs::SlotInput{1,0,8};},
                          [](uint32_t,const auto&){return false;});
  });
  Require(failed.Find(1)==fs::SlotInput{1,0,8},"Failed transport erased the published edge");
}
void Engine() {
  for(const auto contract:{fs::NativeMatchContract(42,1,1),fs::NativeMatchContract(43,0,2)}) {
    fs::ReplayRecorder recorder;recorder.StartRecording(contract.seed,"default_11v11",2);
    {
      GameEnv env;env.game_config.render=false;env.game_config.physics_steps_per_frame=2;
      auto scenario=fs::MakeNativeMatchScenario(contract);env.start_game(*scenario);env.state=game_running;
      auto callbacks=fs::MakeGameEnvCallbacks(&env);
      for(unsigned frame=0;frame<150;++frame) {
        std::vector<fs::SlotInput> inputs{{frame%30<15?1.f:-1.f,0.f,512},{0.f,frame%20<10?1.f:-1.f,512}};
        if(frame%31==0)inputs[0].buttons|=8;
        callbacks.step_frame(inputs);++engine_frames;
        Require(GetGame()==nullptr,"Product frame left environment selected");
        Require(recorder.RecordFrame(frame,callbacks.compute_hash(),inputs),"Product recording rejected");
      }
      env.close();
    }
    const auto bytes=Serialize(recorder,contract);
    fs::NativeReplayPlayer player;
    Require(player.LoadReplay(bytes) && player.contract()==contract,"Product replay not self describing");
    fs::ReplayPlayer legacy;Require(!legacy.LoadReplay(bytes),"Legacy silently interpreted native time");
    Require(!player.LoadReplay(recorder.Serialize()),"Native silently interpreted legacy time");
    for(size_t n=0;n<40;++n) {
      Require(!player.LoadReplay(std::string_view(bytes).substr(0,n)),"Truncated envelope admitted");
      Require(player.GetTotalFrames()==150 && player.contract()==contract,"Rejected replay replaced committed state");
    }
    for(size_t at=0;at<40;++at) {
      auto altered=bytes;altered[at]^=1;
      Require(!player.LoadReplay(altered),"Mutated envelope admitted");
      Require(player.GetTotalFrames()==150 && player.contract()==contract,"Mutation changed committed state");
    }
    {
      GameEnv env;env.game_config.render=false;env.game_config.physics_steps_per_frame=2;
      auto scenario=fs::MakeNativeMatchScenario(player.contract());env.start_game(*scenario);env.state=game_running;
      auto callbacks=fs::MakeGameEnvCallbacks(&env);
      for(size_t i=0;i<player.GetTotalFrames();++i) {
        auto frame=player.GetFrameAt(i);Require(frame.has_value(),"Product replay missing frame");
        callbacks.step_frame(frame->inputs);++engine_frames;
        Require(callbacks.compute_hash()==frame->state_hash,"Product replay changed actual engine digest");
        Require(GetGame()==nullptr,"Product replay left environment selected");
      }
      env.close();
    }
    fs::ReplayRecorder gap;gap.StartRecording(contract.seed,"default_11v11",2);
    Require(gap.RecordFrame(1,123,std::vector<fs::SlotInput>(2)),"Gap fixture failed");
    Require(!player.LoadReplay(Serialize(gap,contract)) && player.GetTotalFrames()==150,"Nonzero replay origin admitted");
  }
}
}
// 2026-09-13: match the actual engine main declaration included by scenario construction.
// int main() {
int main(int, char**) {
  try {
// 2026-09-13: exercise publication before actual engine regression.
//     Wire();Clock();Bots();Engine();
    Wire();Clock();Bots();Publication();Engine();
    std::cout<<"{\"passed\":true,\"skipped\":0,\"assertions\":"<<assertions
             <<",\"clock_events\":"<<clock_events<<",\"engine_frames\":"<<engine_frames
             <<",\"actual_gameenv\":true,\"native_contract\":1}\n";return 0;
  } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
