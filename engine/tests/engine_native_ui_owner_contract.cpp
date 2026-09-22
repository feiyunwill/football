// 2026-09-13: UI progress during blocked work, owned cancellation and concurrent input.
#include "frame_sync/native_ui_owner.hpp"
#include "frame_sync/native_shared_timeline.hpp"
#include <atomic>
#include <chrono>
#include <iostream>
#include <semaphore>
#include <stdexcept>
#include <string>
#include <thread>
namespace {
std::atomic<int> assertions{0};
std::atomic<std::int64_t> fake_now{0};
std::int64_t FakeNow() { return fake_now.load(); }
std::int64_t Now() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
}
void Require(bool value,const char* message) {
  ++assertions;
  if (!value) throw std::runtime_error(message);
}
template<class Function> void LogicRejected(Function&& function) {
  bool rejected=false;
  try { function(); } catch(const std::logic_error&) { rejected=true; }
  Require(rejected,"Foreign owner or reentrant run was accepted");
}
void Neutral(const frame_sync::SlotInput& input) {
  Require(input.dir_x==0 && input.dir_y==0 && input.buttons==0,"Expected neutral input");
}
frame_sync::PythonWindowInput::Sample Keys(bool held) {
  frame_sync::PythonWindowInput::Sample sample;
  sample.focused=true;
  if (held) sample.keys={"d","lshift"};
  return sample;
}
void OwnerLifetimes() {
  frame_sync::NativeUIOwner owner;
  const auto ui_thread=std::this_thread::get_id();
  LogicRejected([&]{owner.CheckWorker();});
  std::jthread foreign([&]{LogicRejected([&]{owner.Run([]{},[]{});});});
  foreign.join();
  for (int iteration=0;iteration<64;++iteration) {
    std::atomic<bool> started=false,finish=false,left=false;
    int polls=0;
    owner.Run([&] {
      owner.CheckWorker();
      Require(std::this_thread::get_id()!=ui_thread,"Game did not leave the UI thread");
      started.store(true,std::memory_order_release);
      while (!finish.load(std::memory_order_acquire)) {
        owner.CheckWorker();
        std::this_thread::yield();
      }
      left.store(true,std::memory_order_release);
    },[&] {
      Require(owner.IsOwnerThread(),"Device service left its creating thread");
      while (!started.load(std::memory_order_acquire)) std::this_thread::yield();
      if (polls<3) Require(!left.load(std::memory_order_acquire),"Blocked work finished without UI progress");
      if (++polls==3) finish.store(true,std::memory_order_release);
    });
    Require(polls>=3 && left.load(),"Work was not joined after UI service completed");
  }
  bool worker_error=false;
  try {owner.Run([]{throw std::runtime_error("worker-marker");},[]{});}
  catch(const std::runtime_error& error) {worker_error=std::string(error.what())=="worker-marker";}
  Require(worker_error,"Worker error was lost");

  std::atomic<bool> started=false,unwound=false;
  bool service_error=false;
  try {
    owner.Run([&] {
      started.store(true,std::memory_order_release);
      try { for (;;) {owner.CheckWorker();std::this_thread::yield();} }
      catch (...) {unwound.store(true,std::memory_order_release);throw;}
    },[&] {
      while (!started.load(std::memory_order_acquire)) std::this_thread::yield();
      throw std::runtime_error("service-marker");
    });
  } catch(const std::runtime_error& error) {service_error=std::string(error.what())=="service-marker";}
  Require(service_error && unwound.load(),"UI failure did not cancel/join work before returning");

  std::atomic<bool> release=false;
  bool nested=false;
  owner.Run([&] {
    while (!release.load(std::memory_order_acquire)) {owner.CheckWorker();std::this_thread::yield();}
  },[&] {
    if (!nested) {LogicRejected([&]{owner.Run([]{},[]{});});nested=true;}
    release.store(true,std::memory_order_release);
  });
  Require(nested,"Reentry case was not exercised");
  // A previous exception must not poison a later run.
  owner.Run([&]{owner.CheckWorker();},[]{});
}
void TimedHandoff() {
  std::binary_semaphore posted(0),consumed(0);
  frame_sync::NativeSharedInputTimeline input(FakeNow);
  std::jthread game([&] {
    for (int frame=0;frame<64;++frame) {
      const std::int64_t base=frame*100;
      posted.acquire();
      Neutral(input.Take(base));
      const auto held=input.Take(base+10);
      Require(held.dir_x==1 && held.dir_y==0 && held.buttons==512,"Sample was lost or backdated");
      const auto repeated=input.Take(base+10);
      Require(repeated.dir_x==held.dir_x && repeated.buttons==held.buttons,"Same deadline changed");
      consumed.release();
      posted.acquire();
      Neutral(input.Take(base+20));
      consumed.release();
    }
  });
  for (int frame=0;frame<64;++frame) {
    fake_now.store(frame*100+8);input.Feed(Keys(true));posted.release();consumed.acquire();
    fake_now.store(frame*100+12);input.Feed(Keys(false));posted.release();consumed.acquire();
  }
  game.join();
}
void ConcurrentInput() {
  frame_sync::NativeSharedInputTimeline input;
  std::atomic<int> produced=0,consumed=0;
  constexpr int count=20000;
  std::jthread devices([&] {
    for (int i=0;i<count;++i) {
      while (i-consumed.load(std::memory_order_acquire)>=64) std::this_thread::yield();
      input.Feed(Keys(i%3!=0));
      const auto commands=input.TakeCommands();
      Require(!commands[0] && !commands[1] && !commands[2],"Gameplay input produced a UI command");
      produced.store(i+1,std::memory_order_release);
    }
  });
  int passes=0;
  while (consumed.load()<count) {
    const auto available=produced.load(std::memory_order_acquire);
    const auto value=input.Take(Now());
    Require(value.dir_y==0 && (value.dir_x==0 || value.dir_x==1) &&
            (value.buttons==0 || value.buttons==512),"Concurrent sample was torn");
    if (++passes%17==0) {
      input.SetSuspended(true);
      Neutral(input.Take(Now()));
      input.SetSuspended(false);
    }
    (void)input.TakeCommands();
    consumed.store(available,std::memory_order_release);
    std::this_thread::yield();
  }
  devices.join();
  input.SetSuspended(true);Neutral(input.Take(Now()));
  Require(produced.load()==count,"Concurrent producer did not finish");
}
}  // namespace
int main() {
  try {
    static_assert(sizeof(frame_sync::NativeSharedInputTimeline)<=16384);
    bool invalid=false;
    try {frame_sync::NativeSharedInputTimeline input(nullptr);}
    catch(const std::invalid_argument&) {invalid=true;}
    Require(invalid,"Missing observation clock accepted");
    OwnerLifetimes();TimedHandoff();ConcurrentInput();
    std::cout<<"{\"passed\":true,\"skipped\":0,\"assertions\":"<<assertions.load()
             <<",\"joined_lifetimes\":64,\"handoff_frames\":256,\"concurrent_observations\":20000"
             <<",\"shared_timeline_bytes\":"<<sizeof(frame_sync::NativeSharedInputTimeline)<<"}\n";
    return 0;
  } catch(const std::exception& error) {std::cerr<<error.what()<<"\n";return 1;}
}
