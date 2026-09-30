// LD_PRELOAD-only inclusive phase timings for the fixed 11v11 match benchmark.
// These instrumented timings locate work; they never enter acceptance ratios.
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <dlfcn.h>

namespace {
using Clock = std::chrono::steady_clock;
struct Counter {
  uint64_t calls = 0;
  uint64_t ns = 0;
};
constexpr const char* names[] = {
    "frame", "match", "ball_collisions", "referee", "capture_prev_ball",
    "hold_check", "ball", "mental_images", "team_switch", "teams",
    "players", "officials", "possession_stats", "possession_decision",
    "humanoid_collisions", "sync_ecs", "run_players", "team_tactics",
    "team_possession", "player_possession", "reachability_estimate",
    "reachability_prepare", "reachability_grow", "ai_has_possession"};
Counter counters[sizeof(names) / sizeof(names[0])];
thread_local bool measured = false;
uint64_t steps_seen = 0;

template <class Function> Function Resolve(const char* symbol) {
  auto* address = dlsym(RTLD_NEXT, symbol);
  if (!address) {
    std::fprintf(stderr, "CPU phase symbol missing: %s\n", symbol);
    std::abort();
  }
  return reinterpret_cast<Function>(address);
}

struct Scope {
  explicit Scope(unsigned index) : index(index), enabled(measured), start(Clock::now()) {
    if (enabled) ++counters[index].calls;
  }
  ~Scope() {
    if (enabled) counters[index].ns +=
        std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start).count();
  }
  unsigned index;
  bool enabled;
  Clock::time_point start;
};

__attribute__((destructor)) void Report() {
  std::fprintf(stderr, "{\"cpu_phase_profile\":true,\"steps_seen\":%llu,\"buckets\":[",
               static_cast<unsigned long long>(steps_seen));
  for (unsigned index = 0; index < sizeof(names) / sizeof(names[0]); ++index) {
    const auto& value = counters[index];
    std::fprintf(stderr, "%s{\"name\":\"%s\",\"calls\":%llu,\"ns\":%llu}",
                 index ? "," : "", names[index],
                 static_cast<unsigned long long>(value.calls),
                 static_cast<unsigned long long>(value.ns));
  }
  std::fprintf(stderr, "]}\n");
}
}  // namespace

extern "C" void ProfileStep(void*, const void*, size_t) asm("_ZN7GameEnv13StepWithInputEPKvm");
extern "C" void ProfileStep(void* environment, const void* input, size_t bytes) {
  static const auto call = Resolve<void (*)(void*, const void*, size_t)>(
      "_ZN7GameEnv13StepWithInputEPKvm");
  measured = steps_seen >= 200 && steps_seen < 2200;
  ++steps_seen;
  {
    Scope scope(0);
    call(environment, input, bytes);
  }
  measured = false;
}

#define WRAP_STEP(name, symbol, index)                                      \
  extern "C" bool name(void*, bool) asm(symbol);                            \
  extern "C" bool name(void* match, bool reverse) {                          \
    static const auto call = Resolve<bool (*)(void*, bool)>(symbol);          \
    Scope scope(index);                                                      \
    return call(match, reverse);                                             \
  }

WRAP_STEP(ProfileBallCollisions, "_ZN5Match18StepBallCollisionsEb", 2)
WRAP_STEP(ProfileReferee, "_ZN5Match11StepRefereeEb", 3)
WRAP_STEP(ProfileCapturePreviousBall, "_ZN5Match26StepCapturePreviousBallPosEb", 4)
WRAP_STEP(ProfileHoldCheck, "_ZN5Match13StepHoldCheckEb", 5)
WRAP_STEP(ProfileBall, "_ZN5Match8StepBallEb", 6)
WRAP_STEP(ProfileMentalImages, "_ZN5Match16StepMentalImagesEb", 7)
WRAP_STEP(ProfileTeamSwitch, "_ZN5Match14StepTeamSwitchEb", 8)
WRAP_STEP(ProfileTeams, "_ZN5Match16StepTeamsProcessEb", 9)
WRAP_STEP(ProfilePlayers, "_ZN5Match18StepPlayersProcessEb", 10)
WRAP_STEP(ProfileOfficials, "_ZN5Match20StepOfficialsProcessEb", 11)
WRAP_STEP(ProfilePossessionStats, "_ZN5Match19StepPossessionStatsEb", 12)
WRAP_STEP(ProfilePossessionDecision, "_ZN5Match22StepPossessionDecisionEb", 13)
WRAP_STEP(ProfileHumanoidCollisions, "_ZN5Match22StepHumanoidCollisionsEb", 14)

extern "C" bool ProfileMatch(void*) asm("_ZN5Match7ProcessEv");
extern "C" bool ProfileMatch(void* match) {
  static const auto call = Resolve<bool (*)(void*)>("_ZN5Match7ProcessEv");
  Scope scope(1);
  return call(match);
}

extern "C" void ProfileSyncEcs(void*) asm("_ZN5Match14SyncEcsFromOopEv");
extern "C" void ProfileSyncEcs(void* match) {
  static const auto call = Resolve<void (*)(void*)>("_ZN5Match14SyncEcsFromOopEv");
  Scope scope(15);
  call(match);
}

extern "C" void ProfileRunPlayers(void*) asm("_Z16RunPlayerSystemsP5Match");
extern "C" void ProfileRunPlayers(void* match) {
  static const auto call = Resolve<void (*)(void*)>("_Z16RunPlayerSystemsP5Match");
  Scope scope(16);
  call(match);
}

extern "C" void ProfileTeamTactics(void*, int) asm("_Z24TeamTacticsSystemProcessP5Matchi");
extern "C" void ProfileTeamTactics(void* match, int team) {
  static const auto call = Resolve<void (*)(void*, int)>(
      "_Z24TeamTacticsSystemProcessP5Matchi");
  Scope scope(17);
  call(match, team);
}

#define WRAP_VOID(name, symbol, index)                                       \
  extern "C" void name(void*) asm(symbol);                                   \
  extern "C" void name(void* self) {                                          \
    static const auto call = Resolve<void (*)(void*)>(symbol);                \
    Scope scope(index);                                                      \
    call(self);                                                               \
  }

WRAP_VOID(ProfileTeamPossession, "_ZN4Team21UpdatePossessionStatsEv", 18)
WRAP_VOID(ProfilePlayerPossession, "_ZN6Player21UpdatePossessionStatsEv", 19)
WRAP_VOID(ProfileReachabilityPrepare, "_ZN24AIReachabilityTrajectory7PrepareEv", 21)

struct TimeNeededResult {
  unsigned int usual_ms;
  unsigned int optimistic_ms;
};
extern "C" TimeNeededResult ProfileReachabilityEstimate(void*, const void*, bool, unsigned int)
    asm("_ZN24AIReachabilityTrajectory8EstimateERKN7blunted7Vector3Ebj");
extern "C" TimeNeededResult ProfileReachabilityEstimate(
    void* self, const void* target, bool precise, unsigned int maximum_ms) {
  static const auto call = Resolve<TimeNeededResult (*)(void*, const void*, bool, unsigned int)>(
      "_ZN24AIReachabilityTrajectory8EstimateERKN7blunted7Vector3Ebj");
  Scope scope(20);
  return call(self, target, precise, maximum_ms);
}

extern "C" void ProfileReachabilityGrow(void*, unsigned int)
    asm("_ZN24AIReachabilityTrajectory6GrowToEj");
extern "C" void ProfileReachabilityGrow(void* self, unsigned int step) {
  static const auto call = Resolve<void (*)(void*, unsigned int)>(
      "_ZN24AIReachabilityTrajectory6GrowToEj");
  Scope scope(22);
  call(self, step);
}

extern "C" bool ProfileAIHasPossession(void*, void*)
    asm("_Z16AI_HasPossessionP4BallP6Player");
extern "C" bool ProfileAIHasPossession(void* ball, void* player) {
  static const auto call = Resolve<bool (*)(void*, void*)>(
      "_Z16AI_HasPossessionP4BallP6Player");
  Scope scope(23);
  return call(ball, player);
}
