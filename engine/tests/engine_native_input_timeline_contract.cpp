// 2026-09-13: independent deadline assignment and delayed-owner input contract.
#include "frame_sync/native_input_timeline.hpp"
#include "frame_sync/native_loop.hpp"
#include <iostream>
#include <limits>
#include <vector>
namespace fs=frame_sync;
namespace {
unsigned assertions=0;
constexpr std::int64_t ms=1000000;
void Require(bool value,const char* reason){++assertions;if(!value)throw std::runtime_error(reason);}
template<class E,class F>void Throws(F fn){bool found=false;try{fn();}catch(const E&){found=true;}Require(found,"Expected rejection missing");}
fs::PythonWindowInput::Sample Keys(std::vector<std::string> keys={}){
 fs::PythonWindowInput::Sample s;s.focused=true;s.keys=std::move(keys);return s;
}
bool Same(const fs::SlotInput& a,const fs::SlotInput& b){
 return a.dir_x==b.dir_x&&a.dir_y==b.dir_y&&a.buttons==b.buttons;
}
void ExactDebt(){
 fs::NativeInputTimeline t;
 t.Feed(Keys({"v"}),8*ms);t.Feed(Keys(),28*ms);
 Require(t.Take(0).buttons==0,"Future input leaked into earlier deadline");
 Require(t.Take(20*ms).buttons==8,"Held shot missing at its deadline");
 Require(t.Take(40*ms).buttons==0&&t.Take(60*ms).buttons==0,"Released shot stretched into debt");
 fs::NativeInputTimeline short_tap;
 short_tap.Feed(Keys({"v"}),8*ms);short_tap.Feed(Keys(),9*ms);
 Require(short_tap.Take(0).buttons==0,"Short edge was backdated");
 Require(short_tap.Take(20*ms).buttons==8&&short_tap.Take(20*ms).buttons==8,"Same deadline was not idempotent");
 Require(short_tap.Take(40*ms).buttons==0,"Short edge repeated at next deadline");
 fs::NativeInputTimeline held;
 held.Feed(Keys({"d","lshift"}),40*ms);
 Require(held.Take(0).dir_x==0&&held.Take(20*ms).dir_x==0,"Movement backdated");
 Require(Same(held.Take(40*ms),{1,0,512})&&Same(held.Take(60*ms),{1,0,512}),"Continuous state lost");
 held.SetSuspended(false,70*ms);
 Require(Same(held.Take(80*ms),{1,0,512}),"No-op suspend setter erased input");
 fs::NativeInputTimeline boundary;
 boundary.Take(20*ms);boundary.Feed(Keys({"v"}),20*ms);
 Require(boundary.Take(20*ms).buttons==0&&boundary.Take(40*ms).buttons==8,"Late same-timestamp event changed a committed deadline");
}
void Cancellation(){
 fs::NativeInputTimeline t;
 auto both=Keys({"v"});both.connected=true;both.buttons=1;
 t.Feed(both,2*ms);t.Feed(Keys(),3*ms);
 Require(t.Take(20*ms).buttons==8,"Pad disconnect lost keyboard edge or retained pad edge");
 fs::NativeInputTimeline blur;
 blur.Feed(both,2*ms);auto unfocused=Keys();unfocused.focused=false;blur.Feed(unfocused,3*ms);
 Require(blur.Take(20*ms).buttons==0,"Focus loss retained unadmitted edges");
 fs::NativeInputTimeline pause;
 pause.Feed(Keys({"v","d","lshift"}),2*ms);
 pause.SetSuspended(true,15*ms);pause.Feed(Keys({"v","d","lshift"}),20*ms);
 pause.SetSuspended(false,30*ms);Require(pause.release_required(),"Resume omitted release barrier");
 pause.Feed(Keys({"v","d","lshift"}),35*ms);Require(pause.Take(40*ms).buttons==0,"Held input crossed resume barrier");
 pause.Feed(Keys(),45*ms);Require(!pause.release_required(),"Neutral observation did not rearm");
 pause.Feed(Keys({"v","d","lshift"}),50*ms);
 Require(Same(pause.Take(60*ms),{1,0,520}),"Fresh press after release missing");
 Throws<std::invalid_argument>([&]{pause.Take(29*ms);});
 auto commands=Keys({"p","k","q"});fs::NativeInputTimeline control;
 control.Feed(commands,2*ms);auto c=control.TakeCommands();
 Require(c[0]&&c[1]&&c[2],"UI commands delayed behind simulation");
 c=control.TakeCommands();Require(c[0]&&!c[1]&&!c[2],"Command edge consumption changed");
}
void BudgetAndErrors(){
 Require(sizeof(fs::NativeInputTimeline)<=16384,"Timeline memory budget exceeded");
 Throws<std::invalid_argument>([]{fs::NativeInputTimeline bad(0);});
 Throws<std::invalid_argument>([]{fs::NativeInputTimeline bad(257);});
 fs::NativeInputTimeline t(1);
 for(int i=0;i<10000;++i)t.Feed(Keys({"d"}),std::int64_t(i)*ms);
 Require(t.size()==1,"Unchanged held samples consumed capacity");
 Throws<std::length_error>([&]{t.Feed(Keys(),10000*ms);});
 Require(t.size()==0&&t.quit_requested(),"Exhaustion did not close the owner");
 Require(Same(t.Take(10000*ms),fs::SlotInput::Default()),"Exhaustion retained movement");
 Throws<std::logic_error>([&]{t.Feed(Keys(),10001*ms);});
 fs::NativeInputTimeline errors;errors.Feed(Keys({"d"}),20*ms);
 Throws<std::invalid_argument>([&]{errors.Feed(Keys(),19*ms);});
 auto invalid=Keys();invalid.axes[0]=std::numeric_limits<float>::quiet_NaN();
 Throws<std::invalid_argument>([&]{errors.Feed(invalid,21*ms);});
 Require(errors.size()==1&&errors.Take(20*ms).dir_x==1,"Rejected observation damaged history");
 Throws<std::invalid_argument>([&]{errors.Take(-1);});
 errors.Close();Require(Same(errors.Take(40*ms),fs::SlotInput::Default()),"Close retained queued state");
}
void SnapshotCompatibility(){
 // Compare the new held+edge capture to the unchanged public Take contract,
 // including source-specific cancellations and repeated observations.
 fs::NativeInputBuffer direct,capture;
 for(unsigned i=0;i<12000;++i){
  auto s=Keys();s.focused=i%31!=0;s.connected=i%17!=0;
  if(i%7<3)s.keys={"d","lshift"};
  if(i%11==0)s.pressed_keys={"v"};
  s.buttons=(i%5<2)?1:0;s.pressed_buttons=(i%13==0)?2:0;
  direct.Feed(s);capture.Feed(s);
  const auto [held,key,pad]=capture.TakeObservation();
  auto combined=held;combined.buttons|=key|pad;
  Require(Same(direct.Take(),combined),"Captured observation differs from unchanged input contract");
  const auto [held_again,key_again,pad_again]=capture.TakeObservation();
  Require(Same(direct.Take(),held_again)&&!key_again&&!pad_again,"Capture consumed held state or repeated edges");
 }
}
void OfflineSchedule(){
 // Closed-right deadline bins are constructed ahead of execution. Each 100 ms
 // episode has movement at20/40, a1ms tap at40, and a held24ms tap at60/80.
 // Sampling proceeds at real observation times; the owner drains in batches.
 constexpr unsigned episodes=2000;
 for(unsigned batch: {1u,8u,64u}){
  fs::NativeInputTimeline timeline;
  std::vector<fs::SlotInput> expected(episodes*5+1,fs::SlotInput::Default());
  using Event=std::pair<std::int64_t,fs::PythonWindowInput::Sample>;
  std::vector<Event> events;
  for(unsigned i=0;i<episodes;++i){
   const auto base=std::int64_t(i)*100*ms;
   events.emplace_back(base+2*ms,Keys({"d","lshift"}));
   events.emplace_back(base+31*ms,Keys({"d","lshift","v"}));
   events.emplace_back(base+32*ms,Keys({"d","lshift"}));
   events.emplace_back(base+49*ms,Keys());
   events.emplace_back(base+59*ms,Keys({"v"}));
   events.emplace_back(base+83*ms,Keys());
   expected[i*5+1]={1,0,512};expected[i*5+2]={1,0,520};
   expected[i*5+3]={0,0,8};expected[i*5+4]={0,0,8};
  }
  std::size_t event=0;unsigned next=0;
  while(next<expected.size()){
   const unsigned stop=std::min<unsigned>(next+batch,expected.size());
   const auto owner_now=std::int64_t(stop-1)*20*ms;
   while(event<events.size()&&events[event].first<=owner_now){
    timeline.Feed(events[event].second,events[event].first);++event;
   }
   for(;next<stop;++next){
    const auto actual=timeline.Take(std::int64_t(next)*20*ms);
    Require(Same(actual,expected[next]),"Batch size changed independently assigned input frame");
   }
  }
  Require(event==events.size()&&timeline.size()==0,"Offline ledger did not drain all observations");
 }
}
void Clock(){
 fs::NativeLoopClock clock(100*ms,50,60);
 Throws<std::logic_error>([&]{clock.LastFixedDeadline();});
 for(unsigned i=0;i<10000;++i){
  const auto expected=(100+std::int64_t(i)*20)*ms;
  Require(clock.FixedLogicDue(expected+100*ms),"Fixed debt unexpectedly absent");
  Require(clock.LastFixedDeadline()==expected,"Consumed deadline shifted to owner wall time");
 }
 clock.RestartLogic(300000*ms);Throws<std::logic_error>([&]{clock.LastFixedDeadline();});
 Require(clock.FixedLogicDue(300000*ms)&&clock.LastFixedDeadline()==300000*ms,"Resume retained old deadline");
}
}
int main(int,char**){
 try{ExactDebt();Cancellation();BudgetAndErrors();SnapshotCompatibility();OfflineSchedule();Clock();
 std::cout<<"{\"passed\":true,\"skipped\":0,\"assertions\":"<<assertions
 <<",\"offline_frames\":30003,\"clock_events\":10000,\"capture_observations\":12000,\"timeline_bytes\":"<<sizeof(fs::NativeInputTimeline)<<"}\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
