// 2026-09-13: independent timeline, scope, exception and thread ownership checks.
#include "systems/graphics/render_service.hpp"
#include "frame_sync/native_input_buffer.hpp"
#include <atomic>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <thread>
#include <vector>
using Service=blunted::ScopedRenderService;
namespace {
thread_local std::int64_t now=0;
thread_local unsigned clock_calls=0;
unsigned assertions=0;
std::int64_t Clock(){++clock_calls;return now;}
void Require(bool value,const char* message){++assertions;if(!value)throw std::runtime_error(message);}
template<class E,class F>void Throws(F fn){bool caught=false;try{fn();}catch(const E&){caught=true;}Require(caught,"Expected rejection missing");}
void Count(void* context){++*static_cast<unsigned*>(context);Service::Poll();}
void Timeline(){
 now=7000000;unsigned calls=0;std::int64_t bucket=-1;unsigned expected=0;
 {
  Service service(Count,&calls,Clock);
  std::int64_t elapsed=0;
  for(unsigned i=0;i<10000;++i){
   elapsed+=i%97==0?73000000:(i%11)*111111;
   now=7000000+elapsed;
   auto observed=elapsed/4000000;
   if(observed!=bucket){++expected;bucket=observed;}
   Service::Poll();
   Require(calls==expected,"Absolute opportunity ledger differs");
   Service::Poll();Require(calls==expected,"Repeated work opportunity dispatched twice");
  }
 }
 const auto before=clock_calls;Service::Poll();Require(clock_calls==before,"Dormant renderer invoked clock");
}
void Scopes(){
 for(unsigned i=0;i<64;++i){
  now=1000000;unsigned outer=0,inner=0;
  Service parent(Count,&outer,Clock);Service::Poll();
  {
   Service child(Count,&inner,Clock);Service::Poll();
   Require(outer==1&&inner==1,"Nested scope selected wrong owner");
  }
  now+=4000000;Service::Poll();Require(outer==2&&inner==1,"Nested scope did not restore owner");
  Throws<std::invalid_argument>([&]{Service bad(nullptr,nullptr,Clock);});
  Throws<std::invalid_argument>([&]{Service bad(Count,&inner,nullptr);});
  now=-1;Throws<std::invalid_argument>([&]{Service bad(Count,&inner,Clock);});
  now=9000000;Service::Poll();Require(outer==3,"Failed registration damaged existing scope");
  {
   Service throwing([](void*){throw std::runtime_error("callback");},nullptr,Clock);
   Throws<std::runtime_error>([]{Service::Poll();});
  }
  now+=4000000;Service::Poll();Require(outer==4,"Exception scope did not restore owner");
 }
 now=100;unsigned calls=0;
 {
  Service service(Count,&calls,Clock);now=99;
  Throws<std::invalid_argument>([]{Service::Poll();});Require(calls==0,"Backwards clock dispatched");
 }
 now=std::numeric_limits<std::int64_t>::max()-1;
 {
  Service service(Count,&calls,Clock);
  Throws<std::overflow_error>([]{Service::Poll();});Require(calls==0,"Overflow dispatched");
 }
}
void Threads(){
 now=0;unsigned owner=0;Service scope(Count,&owner,Clock);Service::Poll();
 std::atomic<unsigned> passed=0;
 std::vector<std::jthread> workers;
 for(unsigned i=0;i<8;++i)workers.emplace_back([&]{
  const auto before=clock_calls;Service::Poll();
  if(clock_calls!=before)return;
  now=0;unsigned local=0;
  {Service service(Count,&local,Clock);
   for(unsigned j=0;j<1000;++j){now=std::int64_t(j)*4000000;Service::Poll();}}
  if(local==1000)++passed;
 });
 for(auto& worker:workers)worker.join();
 Require(passed==8&&owner==1,"Render scopes leaked into other threads");
 now=4000000;Service::Poll();Require(owner==2,"Other render owner displaced this owner");
}
void ShortInput(){
 now=0;frame_sync::NativeInputBuffer buffer;unsigned observations=0;
 std::pair<frame_sync::NativeInputBuffer*,unsigned*> context{&buffer,&observations};
 {
  Service service([](void* opaque){
   auto& refs=*static_cast<decltype(context)*>(opaque);
   frame_sync::PythonWindowInput::Sample sample;sample.focused=true;
   if(now>=8000000&&now<28000000)sample.keys={"v"};
   refs.first->Feed(sample);++*refs.second;
  },&context,Clock);
  // A 60 ms draw services input without stepping the game; the 20 ms press is
  // observed and released before the next simulation admission.
  for(now=0;now<=60000000;now+=1000000)Service::Poll();
 }
 Require(observations==16,"Long draw failed to service sampling opportunities");
 Require(buffer.Take().buttons==8,"Short press was lost during long draw");
 Require(buffer.Take().buttons==0,"Released press stretched into another admission");
}
}
int main(int,char**){
 try{Timeline();Scopes();Threads();ShortInput();
 std::cout<<"{\"passed\":true,\"skipped\":0,\"assertions\":"<<assertions
 <<",\"timeline_events\":10000,\"nested_lifetimes\":64,\"thread_owners\":8,\"render_sampling\":true}\n";return 0;
 }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
