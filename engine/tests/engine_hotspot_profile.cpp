// 2026-09-09: Linux/glibc diagnostic interposer for the unchanged match benchmark.
// Inclusive counters on the benchmark thread only; never use these instrumented
// timings as the release-performance gate. Keep the warmup/steady fixture fixed.
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <dlfcn.h>
#include <new>

extern "C" void* __libc_malloc(size_t);
extern "C" void* __libc_calloc(size_t, size_t);
extern "C" void* __libc_realloc(void*, size_t);
extern "C" void __libc_free(void*);

namespace {
using Clock = std::chrono::steady_clock;
struct Counters {
  uint64_t calls = 0, ns = 0, allocations = 0, bytes = 0;
};
constexpr const char* names[] = {"frame", "players", "physics_sync", "collisions_cache", "full_cache"};
Counters counters[5];
thread_local unsigned active = 0;
uint64_t step_number = 0;
struct Caller {
  void* address = nullptr;
  uint64_t calls = 0, bytes = 0, player_calls = 0;
};
Caller callers[4096];
uint64_t caller_overflow = 0;

void RecordCaller(void* address, size_t bytes) {
  if (!active) return;
  const auto first = (reinterpret_cast<uintptr_t>(address) >> 4) % 4096;
  for (unsigned probe = 0; probe < 4096; ++probe) {
    auto& entry = callers[(first + probe) % 4096];
    if (!entry.address || entry.address == address) {
      entry.address = address;
      ++entry.calls;
      entry.bytes += bytes;
      entry.player_calls += (active & (1u << 1)) != 0;
      return;
    }
  }
  ++caller_overflow;
}

void Allocation(size_t bytes) {
  for (unsigned index = 0; index < 5; ++index)
    if (active & (1u << index)) {
      ++counters[index].allocations;
      counters[index].bytes += bytes;
    }
}

template<class Function> Function Resolve(const char* name) {
  auto* address = dlsym(RTLD_NEXT, name);
  if (!address) {
    std::fprintf(stderr, "Profile symbol missing: %s\n", name);
    std::abort();
  }
  return reinterpret_cast<Function>(address);
}

class Scope {
 public:
  explicit Scope(unsigned index) : previous_(active), index_(index), start_(Clock::now()) {
    if (active) {
      active |= 1u << index_;
      ++counters[index_].calls;
    }
  }
  ~Scope() {
    if (previous_) counters[index_].ns +=
        std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start_).count();
    active = previous_;
  }
  Scope(const Scope&) = delete;
  Scope& operator=(const Scope&) = delete;
  Scope(Scope&&) = delete;
  Scope& operator=(Scope&&) = delete;
 private:
  unsigned previous_, index_;
  Clock::time_point start_;
};

__attribute__((destructor)) void Report() {
  std::fprintf(stderr, "{\"hotspot_profile\":true,\"steps_seen\":%llu,\"buckets\":[",
               static_cast<unsigned long long>(step_number));
  for (unsigned index = 0; index < 5; ++index) {
    const auto& value = counters[index];
    std::fprintf(stderr, "%s{\"name\":\"%s\",\"calls\":%llu,\"ns\":%llu,\"allocations\":%llu,\"bytes\":%llu}",
        index ? "," : "", names[index], static_cast<unsigned long long>(value.calls),
        static_cast<unsigned long long>(value.ns), static_cast<unsigned long long>(value.allocations),
        static_cast<unsigned long long>(value.bytes));
  }
  // 2026-09-09: identify dominant C++ allocation call sites after the first
  // formal run showed that cache-only speed gains remain close to noise.
  // std::fprintf(stderr, "]}\n");
  std::fprintf(stderr, "],\"caller_overflow\":%llu,\"operator_new_callers\":[",
               static_cast<unsigned long long>(caller_overflow));
  bool printed[4096]{};
  for (unsigned rank = 0; rank < 30; ++rank) {
    unsigned best = 4096;
    for (unsigned index = 0; index < 4096; ++index)
      if (!printed[index] && callers[index].calls &&
          (best == 4096 || callers[index].calls > callers[best].calls)) best = index;
    if (best == 4096) break;
    printed[best] = true;
    const auto& caller = callers[best];
    Dl_info info{};
    dladdr(caller.address, &info);
    std::fprintf(stderr, "%s{\"symbol\":\"%s\",\"object\":\"%s\",\"offset\":%llu,\"calls\":%llu,\"bytes\":%llu,\"player_calls\":%llu}",
        rank ? "," : "", info.dli_sname ? info.dli_sname : "<local>", info.dli_fname ? info.dli_fname : "<unknown>",
        static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(caller.address) - reinterpret_cast<uintptr_t>(info.dli_fbase)),
        static_cast<unsigned long long>(caller.calls), static_cast<unsigned long long>(caller.bytes),
        static_cast<unsigned long long>(caller.player_calls));
  }
  std::fprintf(stderr, "]}\n");
}
}  // namespace

extern "C" void* malloc(size_t bytes) {
  void* result = __libc_malloc(bytes);
  if (result) Allocation(bytes);
  return result;
}
extern "C" void* calloc(size_t count, size_t bytes) {
  void* result = __libc_calloc(count, bytes);
  if (result) Allocation(count * bytes);
  return result;
}
extern "C" void* realloc(void* pointer, size_t bytes) {
  void* result = __libc_realloc(pointer, bytes);
  if (result) Allocation(bytes);
  return result;
}
extern "C" void free(void* pointer) { __libc_free(pointer); }

void* operator new(size_t bytes) {
  static const auto call = Resolve<void* (*)(size_t)>("_Znwm");
  RecordCaller(__builtin_extract_return_addr(__builtin_return_address(0)), bytes);
  return call(bytes);
}

extern "C" void ProfileStep(void*, const void*, size_t) asm("_ZN7GameEnv13StepWithInputEPKvm");
extern "C" void ProfileStep(void* environment, const void* input, size_t bytes) {
  static const auto call = Resolve<void (*)(void*, const void*, size_t)>("_ZN7GameEnv13StepWithInputEPKvm");
  const bool measured = step_number >= 200 && step_number < 2200;
  ++step_number;
  active = measured ? 1u : 0u;
  {
    Scope scope(0);
    call(environment, input, bytes);
  }
  active = 0;
}

extern "C" void ProfilePlayers(void*) asm("_Z16RunPlayerSystemsP5Match");
extern "C" void ProfilePlayers(void* match) {
  static const auto call = Resolve<void (*)(void*)>("_Z16RunPlayerSystemsP5Match");
  Scope scope(1);
  call(match);
}
extern "C" void ProfilePhysics(void*) asm("_Z23SyncPlayerPhysicsSystemP5Match");
extern "C" void ProfilePhysics(void* match) {
  static const auto call = Resolve<void (*)(void*)>("_Z23SyncPlayerPhysicsSystemP5Match");
  Scope scope(2);
  call(match);
}
extern "C" void ProfileCollisions(void*) asm("_Z24PopulateCollisionResultsP5Match");
extern "C" void ProfileCollisions(void* match) {
  static const auto call = Resolve<void (*)(void*)>("_Z24PopulateCollisionResultsP5Match");
  Scope scope(3);
  call(match);
}
extern "C" void ProfileCache(void*) asm("_ZN5Match14SyncEcsFromOopEv");
extern "C" void ProfileCache(void* match) {
  static const auto call = Resolve<void (*)(void*)>("_ZN5Match14SyncEcsFromOopEv");
  Scope scope(4);
  call(match);
}
