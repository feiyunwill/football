// 2026-09-13: receipt batches, fixed publication, bounded lead, edges and concurrency.

#include "frame_sync/native_input_publication.hpp"
#include "frame_sync/native_shared_input.hpp"
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <iostream>
#include <map>
#include <mutex>
#include <thread>
namespace fs=frame_sync;
namespace {
size_t assertions=0;
unsigned resync_frames=0,resync_max_lead=0;
std::int64_t clock_now=0;
std::int64_t FakeNow(){return clock_now;}
std::int64_t Zero(){return 0;}
void Require(bool v,const char* m){++assertions;if(!v)throw std::runtime_error(m);}
bool Same(const fs::SlotInput&a,const fs::SlotInput&b){return a.dir_x==b.dir_x&&a.dir_y==b.dir_y&&a.buttons==b.buttons;}
template<class E,class Fn>void Throws(Fn f){bool caught=false;try{f();}catch(const E&){caught=true;}Require(caught,"Missing rejection");}
fs::PythonWindowInput::Sample Keys(bool hold=false,bool shot=false){
 fs::PythonWindowInput::Sample s;s.focused=true;
 if(hold)s.keys={"d","lshift"};if(shot)s.pressed_keys={"v"};return s;
}
void Cadence(){
 fs::NativePublicationClock schedule;
 constexpr auto P=fs::NativePublicationClock::kPeriod;
 auto now=std::int64_t(0);uint32_t authority=0;
 // 6000 actual 50-Hz slots; withhold authority for three slots in each ten.
 for(uint32_t frame=0;frame<6000;++frame){
  if(frame%10<6||frame%10==9)authority=frame;
  auto result=schedule.Next(authority,0,now);
  Require(result && *result==frame+1,"Authority batch skipped a publication");
  for(int phase=1;phase<5;++phase)
   Require(!schedule.Next(authority,0,now+phase*(P/5)),"A 4ms pump oversampled its 50Hz input");
  now+=P;
 }
 // Stale snapshots from the two callers do not rewind the known authority.
 Require(!schedule.Next(authority-1,0,now-1),"Stale snapshot republished");
 Throws<std::invalid_argument>([&]{schedule.Next(authority,0,-1);});
 Throws<std::invalid_argument>([&]{schedule.Next(authority,0,now-2);});
}
void Bounds(){
 constexpr auto P=fs::NativePublicationClock::kPeriod;
 fs::NativePublicationClock c;
 Require(c.Next(100,0,0)==101,"Initial lead changed");
 for(uint32_t f=102;f<=115;++f)Require(c.Next(100,0,(f-101)*P)==f,"Clock failed during receipt pause");
 Require(!c.Next(100,0,1000*P),"Clock exceeded the real server admission window");
 // 2026-09-13: fresh receipt drains immutable lead before extending it.
 // Require(c.Next(101,0,1001*P)==116,"Authority progress did not reopen bounded publication");
 Require(!c.Next(101,0,1001*P),"Fresh authority extended an already queued speculative lead");
 Require(!c.Next(100,0,1001*P+1),"Old receipt rewound publication");
 fs::NativePublicationClock late;
 Require(late.Next(0,0,0)==1,"Initial late fixture");
 Require(late.Next(0,0,5*P)==6,"Expired opportunities were backfilled with current input");
 Require(!late.Next(0,0,5*P+1),"Skipped-debt publication repeated");
 fs::NativePublicationClock ahead;
 Require(!ahead.Next(0,16,0),"Prediction outside the server window consumed a slot");
 Require(ahead.Next(1,16,P)==16,"Admissible prediction did not resume");
 fs::NativePublicationClock overflow;
 Throws<std::overflow_error>([&]{overflow.Next(UINT32_MAX,0,0);});
 Throws<std::overflow_error>([&]{overflow.Next(0,0,INT64_MAX);});
 Require(overflow.Next(0,0,0)==1,"Rejected input corrupted fresh schedule");
}

void Resynchronization(){
 constexpr auto P=fs::NativePublicationClock::kPeriod;
 fs::NativePublicationClock c;
 uint32_t authority=0,last=0,max_lead=0,sent=0;
 // Server takes 21ms per frame; a 50Hz local clock must not accumulate 300ms of input.
 for(std::int64_t now=0;now<12000000000LL;now+=1000000){
  authority=now/21000000;
  auto target=c.Next(authority,0,now);
  if(target){
   Require(*target>last,"Publication rewound or repeated");last=*target;++sent;
   max_lead=std::max(max_lead,*target-authority);
  }
 }
 Require(max_lead<=2,"Slow authority accumulated speculative input latency");
 Require(sent>=570,"Authority resynchronization starved publication");
 resync_frames=sent;resync_max_lead=max_lead;
 // 100ms receipt silence still publishes all five currently clocked inputs.
 fs::NativePublicationClock batches;
 Require(batches.Next(100,0,0)==101,"Batch initial");
 for(unsigned i=1;i<=5;++i)Require(batches.Next(100,0,i*P)==101+i,"Receipt silence stopped publication");
 Require(batches.Next(106,0,6*P)==107,"Batch recovery lost the current input");
 // On an actual authority stall, immutable future input drains before resampling.
 fs::NativePublicationClock stalled;
 Require(stalled.Next(100,0,0)==101,"Stall initial");
 Require(stalled.Next(100,0,5*P)==106,"Stall fixture");
 for(unsigned i=1;i<=5;++i)
  Require(!stalled.Next(100+i,0,(5+i)*P),"Slow server recovery retained excess lead");
 Require(stalled.Next(106,0,11*P)==107,"Server caught up but input remained blocked");
}
void EdgeOwnership(){
 fs::LocalInputHistory history;fs::NativePublishedHistory pub(history,FakeNow);
 fs::NativeSharedInputBuffer input;std::map<uint32_t,fs::SlotInput> sent;size_t samples=0;
 auto pump=[&](uint32_t a){return pub.PublishTimed(a,[&](auto){++samples;return input.Take();},
  [&](auto f,const auto& v){if(!sent.emplace(f,v).second)throw std::runtime_error("Duplicate wire input");return true;});};
 clock_now=0;input.Feed(Keys(true));Require(pump(0)==1,"Initial publish absent");
 clock_now=8000000;input.Feed(Keys(false,true));input.Feed(Keys());
 Require(!pump(0),"Short press forced an early publication");
 clock_now=20000000;Require(pump(0)==2,"Clock did not consume buffered edge");
 clock_now=24000000;Require(!pump(0),"Repeated pump consumed a frame");
 clock_now=40000000;Require(pump(0)==3,"Third timed input absent");
 Require(sent.at(1).buttons==512 && sent.at(1).dir_x==1,"Held input changed");
 Require(sent.at(2).buttons==8 && sent.at(2).dir_x==0,"Short edge lost");
 Require(Same(sent.at(3),fs::SlotInput::Default()),"Short edge repeated");
 input.SetSuspended(true);input.Feed(Keys(true));clock_now=60000000;pump(0);
 input.SetSuspended(false);clock_now=80000000;pump(0);
 Require(Same(sent.at(4),fs::SlotInput::Default())&&Same(sent.at(5),fs::SlotInput::Default()),"Resume re-used held state");
 input.Feed(Keys());input.Feed(Keys(true));clock_now=100000000;pump(0);
 Require(sent.at(6).buttons==512 && sent.at(6).dir_x==1,"Release/repress barrier did not recover");
 pub.Advance(6,6);Require(Same(pub.Read(6,6),sent.at(6)),"Prediction differs from the immutable wire input");
 Require(samples==6,"Idle timer consumed input edges");
 fs::LocalInputHistory tiny(0,2);fs::NativePublishedHistory limited(tiny,FakeNow);
 clock_now=0;size_t consumed=0;
 auto produce=[&](auto){++consumed;return fs::SlotInput::Default();};
 limited.PublishTimed(0,produce,[](auto,const auto&){return true;});
 clock_now=20000000;Throws<std::out_of_range>([&]{limited.PublishTimed(0,produce,[](auto,const auto&){return true;});});
 Require(consumed==1,"Rejected capacity consumed input");
 Throws<std::invalid_argument>([&]{fs::NativePublishedHistory invalid(tiny,nullptr);});
 fs::LocalInputHistory bad;fs::NativePublishedHistory failed(bad,FakeNow);
 Throws<std::runtime_error>([&]{failed.PublishTimed(0,produce,[](auto,const auto&){return false;});});
}
void Concurrent(){
 fs::LocalInputHistory history;fs::NativePublishedHistory pub(history,Zero);
 std::atomic<uint32_t> authority=0;std::atomic<bool> done=false,failed=false;
 std::mutex mu;std::condition_variable ready;std::map<uint32_t,fs::SlotInput> sent;size_t samples=0;
 auto work=[&]{
  try{while(!done.load()){
   pub.PublishTimed(authority.load(),[&](auto){++samples;return fs::SlotInput{1,0,512};},[&](auto f,const auto& v){
    std::lock_guard lock(mu);if(!sent.emplace(f,v).second)throw std::runtime_error("Concurrent duplicate");ready.notify_all();return true;});
   std::this_thread::yield();
  }}catch(...){failed=true;ready.notify_all();}
 };
 std::jthread a(work),b(work);
 bool complete=true;
 for(uint32_t f=0;f<512;++f){
  pub.Advance(f,f);authority.store(f);
  std::unique_lock lock(mu);
  if(!ready.wait_for(lock,std::chrono::seconds(3),[&]{return failed.load()||sent.contains(f+1);})){complete=false;break;}
  if(failed){complete=false;break;}
 }
 done=true;a.join();b.join();
 Require(complete&&!failed,"Concurrent timed publication failed");
 Require(sent.size()==512&&samples==512,"Same timestamp sampled twice or lost a slot");
 for(const auto& [f,v]:sent)Require(v.dir_x==1&&v.buttons==512,"Concurrent input torn");
}
}
int main(){
 // 2026-09-13: retain the original contracts and add slow-authority recovery.
 // try{Cadence();Bounds();EdgeOwnership();Concurrent();
 try{Cadence();Bounds();Resynchronization();EdgeOwnership();Concurrent();
  std::cout<<"{\"passed\":true,\"skipped\":0,\"assertions\":"<<assertions<<",\"cadence_frames\":6000,\"concurrent_frames\":512,\"edge_frames\":6,\"schedule_bytes\":"<<sizeof(fs::NativePublicationClock)<<",\"resync_frames\":"<<resync_frames<<",\"resync_max_lead\":"<<resync_max_lead<<"}\n";
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
}
