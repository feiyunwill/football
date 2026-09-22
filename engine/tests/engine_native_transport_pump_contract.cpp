// 2026-09-13: concurrent publication, edge ownership and worker lifetime contract.
#include "frame_sync/native_input_publication.hpp"
#include "frame_sync/native_shared_input.hpp"
#include "frame_sync/native_transport_pump.hpp"
#include <atomic>
#include <condition_variable>
#include <iostream>
#include <map>
#include <mutex>
#include <thread>
namespace fs=frame_sync;
// 2026-09-13: the public sample type belongs to frame_sync.
using PythonWindowInput=fs::PythonWindowInput;
namespace {
size_t assertions=0;
void Require(bool value,const char* reason) {++assertions;if(!value)throw std::runtime_error(reason);}
template<class Error,class Fn> void Throws(Fn fn) {
 bool found=false;try{fn();}catch(const Error&){found=true;}Require(found,"Expected rejection missing");
}
bool Same(const fs::SlotInput& a,const fs::SlotInput& b) {
 return a.dir_x==b.dir_x && a.dir_y==b.dir_y && a.buttons==b.buttons;
}
// 2026-09-13: a default sample is unfocused; explicitly model the live window.
PythonWindowInput::Sample Focused() {
 PythonWindowInput::Sample result;result.focused=true;return result;
}
void Ledger() {
 fs::NativeSharedInputBuffer buffer;
 fs::LocalInputHistory history;
 fs::NativePublishedHistory publication(history);
 size_t samples=0,sends=0;
 for(uint32_t frame=0;frame<4000;++frame) {
// 2026-09-13: keep window focus while modelling held, released and short input.
//   PythonWindowInput::Sample state;
  PythonWindowInput::Sample state=Focused();
  if(frame%7<3)state.keys={"d","lshift"};
  else if(frame%7==3)state.pressed_keys={"v"};
  buffer.Feed(state);
// 2026-09-13: keep window focus while modelling held, released and short input.
//   if(frame%7==3)buffer.Feed(PythonWindowInput::Sample{});
  if(frame%7==3)buffer.Feed(Focused());
  const fs::SlotInput expected=frame%7<3 ? fs::SlotInput{1,0,512} :
      (frame%7==3 ? fs::SlotInput{0,0,8} : fs::SlotInput::Default());
  publication.Advance(frame,frame);
  const auto first=publication.Publish(frame,[&](auto){++samples;return buffer.Take();},
      [&](auto target,const auto& value){Require(target==frame+1 && Same(value,expected),"Published value differs");++sends;return true;});
  const auto second=publication.Publish(frame,[&](auto){++samples;return buffer.Take();},
      [&](auto,const auto&){++sends;return true;});
  Require(first==frame+1 && second==first,"Same authority targeted different frames");
  Require(samples==frame+1 && sends==samples,"Repeated target consumed an edge or sent twice");
  Require(Same(publication.Read(frame+1,frame),expected),"Prediction changed the published input");
  Require(history.size()<=2,"History retained confirmed entries");
 }
 buffer.SetSuspended(true);
 Require(Same(buffer.Take(),fs::SlotInput::Default()),"Suspended shared input is nonzero");
 buffer.SetSuspended(false);
 Require(buffer.release_required(),"Shared input omitted resume barrier");
// 2026-09-13: keep window focus while modelling held, released and short input.
//  buffer.Feed(PythonWindowInput::Sample{});
 buffer.Feed(Focused());
 Require(!buffer.release_required(),"Neutral observation did not release resume barrier");
 Throws<std::invalid_argument>([&]{publication.Advance(3999,4000);});
 Throws<std::invalid_argument>([&]{publication.Read(3999,4000);});
 fs::LocalInputHistory tiny(0,2);fs::NativePublishedHistory limited(tiny);
 size_t sampled=0;
 limited.Publish(0,[&](auto){++sampled;return fs::SlotInput::Default();},[](auto,const auto&){return true;});
 Throws<std::out_of_range>([&]{limited.Publish(1,[&](auto){++sampled;return fs::SlotInput::Default();},[](auto,const auto&){return true;});});
 Require(sampled==1,"Rejected capacity consumed an input edge");
}
void Concurrent() {
 fs::NativeSharedInputBuffer buffer;
// 2026-09-13: keep window focus while modelling held, released and short input.
//  PythonWindowInput::Sample hold;hold.keys={"d","lshift"};buffer.Feed(hold);
 PythonWindowInput::Sample hold=Focused();hold.keys={"d","lshift"};buffer.Feed(hold);
 fs::LocalInputHistory history;fs::NativePublishedHistory publication(history);
 std::mutex mu;std::condition_variable changed;
 std::map<uint32_t,fs::SlotInput> sent;
 std::atomic<uint32_t> authority{0};
 std::atomic<bool> server_failed{false};
 bool advance_second=false,abort=false;
 const auto owner=std::this_thread::get_id();
 std::atomic<bool> wrong_thread{false};
 fs::NativeTransportPump pump([&]{
  if(std::this_thread::get_id()==owner)wrong_thread=true;
  publication.Publish(authority.load(),[&](auto){return buffer.Take();},
    [&](auto frame,const auto& value){
      std::lock_guard lock(mu);
      if(!sent.emplace(frame,value).second)throw std::runtime_error("Duplicate wire submission");
      changed.notify_all();return true;
    });
 });
 std::jthread server([&]{
  try {
   for(uint32_t frame=0;frame<128;++frame) {
    std::unique_lock lock(mu);
    if(frame==64 && !changed.wait_for(lock,std::chrono::seconds(3),[&]{return advance_second||abort;}))
      throw std::runtime_error("UI control deadline");
    if(abort)return;
    authority=frame;
    if(!changed.wait_for(lock,std::chrono::seconds(3),[&]{return sent.contains(frame+1)||abort;}))
      throw std::runtime_error("Publication stopped during owner wait");
    if(abort)return;
   }
  }catch(...){server_failed=true;changed.notify_all();}
 });
 {
  std::unique_lock lock(mu);
  if(!changed.wait_for(lock,std::chrono::seconds(5),[&]{return sent.size()>=64||server_failed.load();}))abort=true;
 }
 // The UI did no networking while the first 64 held-input frames were admitted.
// 2026-09-13: keep window focus while modelling held, released and short input.
//  buffer.Feed(PythonWindowInput::Sample{});
 buffer.Feed(Focused());
// 2026-09-13: keep window focus while modelling held, released and short input.
//  PythonWindowInput::Sample edge;edge.pressed_keys={"v"};buffer.Feed(edge);
 PythonWindowInput::Sample edge=Focused();edge.pressed_keys={"v"};buffer.Feed(edge);
// 2026-09-13: keep window focus while modelling held, released and short input.
//  buffer.Feed(PythonWindowInput::Sample{});
 buffer.Feed(Focused());
 {
  std::lock_guard lock(mu);advance_second=true;changed.notify_all();
 }
 server.join();pump.Stop();pump.Check();
 Require(!server_failed && !abort && !wrong_thread,"Transport worker violated execution ownership");
 Require(sent.size()==128,"Worker did not submit every controlled authority opportunity");
 for(uint32_t frame=1;frame<=128;++frame) {
  Require(sent.contains(frame),"Continuous input has a missing frame");
  const auto expected=frame<=64 ? fs::SlotInput{1,0,512} :
     (frame==65 ? fs::SlotInput{0,0,8} : fs::SlotInput::Default());
  Require(Same(sent.at(frame),expected),"Held/released/short-edge publication differs");
 }
 const auto count=sent.size();std::this_thread::sleep_for(std::chrono::milliseconds(12));
 Require(sent.size()==count,"Joined worker still called destroyed-owner work");
 pump.Stop(); // idempotent shutdown
}
void Failures() {
 std::atomic<bool> called=false;
 fs::NativeTransportPump failure([&]{called=true;throw std::runtime_error("Worker error");});
 while(!called)std::this_thread::yield();
 failure.Stop();
 Throws<std::runtime_error>([&]{failure.Check();});
 std::atomic<unsigned> count=0;
 {fs::NativeTransportPump disabled([&]{++count;},false);disabled.Check();}
 Require(count==0,"Disabled legacy pump executed work");
 Throws<std::invalid_argument>([]{fs::NativeTransportPump invalid(std::function<void()>{});});
 for(unsigned round=0;round<64;++round) {
  std::atomic<unsigned> lifetime=0;
  {fs::NativeTransportPump scoped([&]{++lifetime;});
   while(!lifetime)std::this_thread::yield();}
  const auto done=lifetime.load();
  std::this_thread::sleep_for(std::chrono::microseconds(100));
  Require(done==lifetime,"Worker outlived scoped owner");
 }
}
}
int main(int argc,char** argv) {
 try{
  Ledger();Concurrent();Failures();
  std::cout<<"{\"passed\":true,\"skipped\":0,\"assertions\":"<<assertions
    <<",\"ledger_frames\":4000,\"concurrent_frames\":128,\"joined_lifetimes\":64}\n";return 0;
 }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
