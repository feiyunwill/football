// 2026-09-13: temporal presentation contract; fake pose arithmetic, not image evidence.
// 2026-09-13: formal gate compiles the canonical implementation.
// #include "native_presentation.hpp"
#include "frame_sync/native_presentation.hpp"
#include <cmath>
#include <iostream>
#include <limits>
#include <thread>
#include <vector>

namespace {
std::uint64_t assertions = 0;
constexpr std::int64_t ms = 1000000;
void Require(bool ok, const char* message) {
  ++assertions;
  if (!ok) throw std::runtime_error(message);
}
template<class Call> void Reject(Call call) {
  bool rejected = false;
  try { call(); } catch (const std::exception&) { rejected = true; }
  Require(rejected, "Invalid presentation operation accepted");
}
class Poses {
 public:
  Poses() = default;
  ~Poses() = default;
  Poses(const Poses&) = delete;
  Poses& operator=(const Poses&) = delete;
  Poses(Poses&&) = delete;
  Poses& operator=(Poses&&) = delete;
  void save_render_state(bool display) {
    previous = display ? visible : physics;
    captures.push_back(display);
  }
  void render_interpolated(float alpha) {
    visible = previous * (1. - alpha) + physics * alpha;
    ++presents;
  }
  double physics = 0, previous = 0, visible = 0;
  int presents = 0;
  std::vector<bool> captures;
};
using Presentation = frame_sync::NativePresentation<Poses>;
void Draw(Presentation& presentation, Poses& poses, std::int64_t time, double expected) {
  const int before = poses.presents;
  Require(presentation.Render(time), "Enabled presentation did not draw");
  Require(poses.presents == before + 1, "A draw did not issue exactly one public presentation");
  Require(std::abs(poses.visible - expected) < 0.00001, "Visible pose or blend phase differs");
}
void OrdinaryWaitAndCatchup() {
  Poses poses; Presentation owner(poses, true, std::chrono::milliseconds(100));
  owner.Initialize(0); Draw(owner, poses, 0, 0);
  for (int frame = 1; frame <= 1000; ++frame) {
    const auto now = frame * 100 * ms;
    owner.BeginTick(now); owner.BeforeStep(); poses.physics = frame;
    Require(owner.CommitTick(now), "Changed ordinary tick was not published");
    Draw(owner, poses, now + 25 * ms, frame - .75);
    Require(!poses.captures.back(), "Ordinary frames accumulated displayed-pose lag");
    const auto captured = poses.captures.size();
    owner.BeginTick(now + 40 * ms);
    Require(!owner.CommitTick(now + 40 * ms), "Waiting became a new publication");
    Require(poses.captures.size() == captured, "Waiting replaced interpolation history");
    Draw(owner, poses, now + 50 * ms, frame - .5);
  }
  owner.BeginTick(100100 * ms);
  for (int i = 0; i < 3; ++i) { owner.BeforeStep(); ++poses.physics; }
  Require(owner.CommitTick(100100 * ms), "Catchup was not published");
  Draw(owner, poses, 100125 * ms, 1002.25);
  Draw(owner, poses, 100200 * ms, 1003);
  Draw(owner, poses, 1000000 * ms, 1003);
}
void CorrectThenRetarget() {
  Poses poses; Presentation owner(poses, true, std::chrono::milliseconds(100));
  owner.Initialize(0); Draw(owner, poses, 0, 0);
  owner.BeginTick(100 * ms); owner.BeforeStep(); poses.physics = 10;
  owner.CommitTick(100 * ms); Draw(owner, poses, 150 * ms, 5);
  owner.BeginTick(160 * ms); owner.BeforeRestore(); poses.physics = -100;
  owner.BeforeStep(); poses.physics = -10;
  owner.CommitTick(160 * ms);
  Draw(owner, poses, 160 * ms, 5);
  Draw(owner, poses, 210 * ms, -2.5);
  // A regular step during correction also starts from the last visible pose.
  owner.BeginTick(220 * ms); owner.BeforeStep(); poses.physics = 20;
  owner.CommitTick(220 * ms);
  Draw(owner, poses, 220 * ms, -2.5);
  Draw(owner, poses, 270 * ms, 8.75);
  owner.BeginTick(280 * ms); owner.BeforeRestore(); poses.physics = -30;
  owner.BeforeStep(); poses.physics = -20;
  owner.CommitTick(280 * ms);
  Draw(owner, poses, 280 * ms, 8.75);
  Draw(owner, poses, 330 * ms, -5.625);
  Draw(owner, poses, 380 * ms, -20);
  owner.BeginTick(400 * ms); owner.BeforeStep(); poses.physics = -10;
  owner.CommitTick(400 * ms);
  Require(!poses.captures.back(), "Settled correction continued adding visual lag");
  Draw(owner, poses, 425 * ms, -17.5);
}
void PauseResumeAndInitial() {
  Poses poses; poses.physics = 3;
  Presentation owner(poses, true, std::chrono::milliseconds(100));
  owner.Initialize(0);
  owner.BeginTick(0); owner.BeforeStep(); poses.physics = 10; owner.CommitTick(0);
  Draw(owner, poses, 0, 10);  // first image is the current pose
  owner.BeginTick(100 * ms); owner.BeforeStep(); poses.physics = 20;
  owner.CommitTick(100 * ms); Draw(owner, poses, 125 * ms, 12.5);
  owner.Pause(150 * ms); owner.Pause(150 * ms);
  Reject([&] { owner.BeginTick(10000 * ms); });  // cannot poison the clock
  Draw(owner, poses, 200 * ms, 12.5);
  owner.Resume(210 * ms); owner.Resume(210 * ms);
  Draw(owner, poses, 210 * ms, 12.5);
  Draw(owner, poses, 260 * ms, 16.25);
  owner.BeginTick(270 * ms); owner.BeforeStep(); poses.physics = 30;
  owner.CommitTick(270 * ms); Draw(owner, poses, 270 * ms, 16.25);
  Draw(owner, poses, 320 * ms, 23.125);
  Draw(owner, poses, 370 * ms, 30);
}
void OrderingOwnershipAndCallbacks() {
  Poses poses; Presentation owner(poses, true, std::chrono::milliseconds(100));
  Reject([&] { owner.Render(10000 * ms); });
  owner.Initialize(0);
  Reject([&] { owner.Initialize(10000 * ms); });
  Reject([&] { owner.BeforeStep(); });
  Reject([&] { owner.BeforeRestore(); });
  Reject([&] { owner.CommitTick(10000 * ms); });
  Draw(owner, poses, 0, 0);
  owner.BeginTick(10 * ms);
  Reject([&] { owner.BeginTick(10000 * ms); });
  Reject([&] { owner.Render(10000 * ms); });
  Reject([&] { owner.Pause(10000 * ms); });
  Reject([&] { owner.Resume(10000 * ms); });
  Require(!owner.CommitTick(10 * ms), "Rejected partial operation changed the clock");
  Reject([&] { owner.Render(-1); });
  Reject([&] { owner.Render(9 * ms); });
  bool rejected_thread = false;
  std::thread other([&] {
    try { owner.Render(10000 * ms); } catch (const std::logic_error&) { rejected_thread = true; }
  });
  other.join();
  Require(rejected_thread, "Foreign thread presented this environment");
  Draw(owner, poses, 10 * ms, 0);
  frame_sync::EngineCallbacks callbacks;
  callbacks.step_frame = [&](std::span<const frame_sync::SlotInput> input) { poses.physics += input[0].dir_x; };
  callbacks.step = [&](const frame_sync::SlotInput& input) { poses.physics += input.dir_x; };
  callbacks.restore_state = [&](const frame_sync::StateBlob&) { poses.physics = -1; };
  auto wrapped = owner.Wrap(callbacks);
  const frame_sync::SlotInput input{1.f, 0.f, 0};
  owner.BeginTick(20 * ms);
  wrapped.step_frame(std::span<const frame_sync::SlotInput>(&input, 1));
  owner.CommitTick(20 * ms); Draw(owner, poses, 70 * ms, .5);
  owner.BeginTick(80 * ms);
  wrapped.restore_state({}); wrapped.step(input);
  owner.CommitTick(80 * ms); Draw(owner, poses, 80 * ms, .5);
  Draw(owner, poses, 180 * ms, 0);
  Reject([&] { owner.Wrap({}); });
  Poses hidden;
  Presentation disabled(hidden, false, std::chrono::milliseconds(100));
  disabled.Initialize(0);
  Require(!disabled.Render(0) && hidden.captures.empty() && hidden.presents == 0,
          "Headless owner performed graphics work");
  auto unchanged = disabled.Wrap(callbacks);
  unchanged.step(input);
  Require(poses.physics == 1, "Headless decorator added a tick dependency");
  Reject([&] { Presentation invalid(poses, true, std::chrono::nanoseconds(0)); });
  Reject([&] { Presentation invalid(poses, true, std::chrono::seconds(2)); });
}
}  // namespace
int main() {
  try {
    OrdinaryWaitAndCatchup();
    CorrectThenRetarget();
    PauseResumeAndInitial();
    OrderingOwnershipAndCallbacks();
    std::cout << "{\"passed\":true,\"skipped\":0,\"assertions\":" << assertions
              << ",\"ordinary_frames\":1000,\"actual_gameenv\":false"
              << ",\"actual_images\":false}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n'; return 1;
  }
}
