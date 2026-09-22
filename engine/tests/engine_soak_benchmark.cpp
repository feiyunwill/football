// 2026-09-13: separate long-run entry; the immutable short benchmark is unchanged.
// 2026-09-09: actual 11v11 startup, warmup and steady-state measurements.
#include "frame_sync/default_scenario.hpp"
#include "frame_sync/state_hash.hpp"
#include "game_env.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <climits>
#include <cmath>
#include <format>
#include <fstream>
#include <iostream>
#include <numeric>
#include <sched.h>
#include <stdexcept>
#include <sys/resource.h>
#include <unistd.h>

namespace {
using Clock = std::chrono::steady_clock;
using Input = std::array<frame_sync::SlotInput, 4>;
static_assert(sizeof(Input) == 4 * frame_sync::SLOT_INPUT_BYTES);
int assertions = 0;
void Require(bool condition, const char* message) {
  ++assertions;
  if (!condition) throw std::runtime_error(message);
}
uint64_t Elapsed(Clock::time_point start) {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start).count();
}
uint64_t ResidentBytes() {
  // 2026-09-09: statm uses approximate kernel counters; sample accurate rollup outside timed steps.
  // std::ifstream file("/proc/self/statm");
  // uint64_t total = 0, resident = 0;
  // if (!(file >> total >> resident)) throw std::runtime_error("Cannot read process RSS");
  // return resident * static_cast<uint64_t>(sysconf(_SC_PAGESIZE));
  std::ifstream file("/proc/self/smaps_rollup");
  std::string line;
  while (std::getline(file, line))
    if (line.starts_with("Rss:")) return std::stoull(line.substr(4)) * 1024;
  throw std::runtime_error("Cannot read accurate process RSS");
}
uint64_t CpuNanoseconds() {
  timespec time{};
  if (clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &time) != 0)
    throw std::runtime_error("Cannot read process CPU time");
  return uint64_t(time.tv_sec) * 1000000000 + time.tv_nsec;
}
std::string Hash(std::string_view state) {
  return std::format("{:016x}", frame_sync::ComputeStateHash(state.data(), state.size()));
}
Input FrameInput(int frame) {
  constexpr std::array<std::array<float, 2>, 8> directions{{
      {1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}, {0, -1}, {1, -1}}};
  Input inputs{};
  for (int slot = 0; slot < 4; ++slot) {
    const auto direction = directions[(frame / 25 + slot * 2) % directions.size()];
    inputs[slot].dir_x = direction[0];
    inputs[slot].dir_y = direction[1];
    if ((frame + slot * 17) % 80 < 45) inputs[slot].buttons |= 1u << e_ButtonFunction_Sprint;
    if ((frame + slot * 13) % 71 < 5) inputs[slot].buttons |= 1u << e_ButtonFunction_ShortPass;
    if ((frame + slot * 29) % 163 >= 80 && (frame + slot * 29) % 163 < 86)
      inputs[slot].buttons |= 1u << e_ButtonFunction_Shot;
  }
  return inputs;
}
uint64_t Quantile(std::vector<uint64_t> values, double fraction) {
  if (values.empty()) throw std::runtime_error("No samples for quantile");
  std::sort(values.begin(), values.end());
  return values[static_cast<size_t>(std::ceil(fraction * values.size())) - 1];
}
void Distribution(const std::vector<uint64_t>& values) {
  std::cout << "{\"count\":" << values.size();
  if (!values.empty()) {
    std::cout << ",\"sum_ns\":" << std::accumulate(values.begin(), values.end(), uint64_t{0})
              << ",\"p50_ns\":" << Quantile(values, .50) << ",\"p95_ns\":" << Quantile(values, .95)
              << ",\"p99_ns\":" << Quantile(values, .99) << ",\"max_ns\":" << *std::max_element(values.begin(), values.end());
  }
  std::cout << '}';
}
template<class T> void Numbers(const std::vector<T>& values) {
  std::cout << '[';
  for (size_t index = 0; index < values.size(); ++index) {
    if (index) std::cout << ',';
    std::cout << values[index];
  }
  std::cout << ']';
}
int Integer(const char* value, int minimum, int maximum) {
  size_t used = 0;
  const auto parsed = std::stoll(value, &used);
  if (value[used] != '\0' || parsed < minimum || parsed > maximum)
    throw std::invalid_argument("Benchmark argument is outside its supported range");
  return static_cast<int>(parsed);
}
}  // namespace

int main(int argc, char** argv) {
  try {
    // 2026-09-13: this acceptance workload has fixed counts. Keep the original
    // short benchmark and its argument contract separate.
    // if (argc != 5) throw std::invalid_argument("Usage: engine_match_benchmark SEED WARMUP FRAMES CPU");
    // const int warmup = Integer(argv[2], 100, 10000);
    // const int samples = Integer(argv[3], 1000, 100000);
    // const int cpu = Integer(argv[4], 0, CPU_SETSIZE - 1);
    if (argc != 3) throw std::invalid_argument("Usage: engine_soak_benchmark SEED CPU");
    const uint32_t seed = Integer(argv[1], 0, INT_MAX);
    constexpr int warmup = 1000;
    constexpr int samples = 36000;
    const int cpu = Integer(argv[2], 0, CPU_SETSIZE - 1);
    cpu_set_t allowed, pinned;
    CPU_ZERO(&allowed);
    Require(sched_getaffinity(0, sizeof(allowed), &allowed) == 0 && CPU_ISSET(cpu, &allowed), "Requested CPU is not allowed");
    CPU_ZERO(&pinned);
    CPU_SET(cpu, &pinned);
    Require(sched_setaffinity(0, sizeof(pinned), &pinned) == 0, "Cannot pin benchmark CPU");
    std::vector<Input> inputs;
    inputs.reserve(warmup + samples);
    for (int frame = 0; frame < warmup + samples; ++frame) inputs.push_back(FrameInput(frame));
    const auto input_hash = Hash(std::string_view(reinterpret_cast<const char*>(inputs.data()), inputs.size() * sizeof(Input)));
    std::vector<uint64_t> warmup_ns, elapsed_ns, active_ns, stopped_ns, cpu_ns, rss_bytes;
    std::vector<int> active_flags;
    std::vector<std::string> hashes;
    warmup_ns.reserve(warmup);
    for (auto* buffer : {&elapsed_ns, &active_ns, &stopped_ns, &cpu_ns}) buffer->reserve(samples);
    active_flags.reserve(samples);
    rss_bytes.reserve(samples / 100 + 2);
    hashes.reserve(samples / 100 + 2);
    // 2026-09-13: retain the verified 2026-09-10 preflight measurement correction.
    // Construct and touch numeric measurement storage
    // before engine startup, then keep the original empty-vector append behavior.
    // No measured RSS subtraction, trim, engine reset or input change.
    for (auto* buffer : {&warmup_ns, &elapsed_ns, &active_ns, &stopped_ns, &cpu_ns, &rss_bytes}) {
      buffer->resize(buffer->capacity());
      for (auto& value : *buffer) static_cast<volatile uint64_t&>(value) = 0;
      buffer->clear();
    }
    active_flags.resize(active_flags.capacity());
    for (auto& value : active_flags) static_cast<volatile int&>(value) = 0;
    active_flags.clear();
    GameEnv environment;
    auto scenario = frame_sync::MakeDefaultScenario(2, 2, seed);
    scenario->game_duration = warmup + samples + 1;
    const auto initial_rss = ResidentBytes();
    auto start = Clock::now();
    environment.start_game(*scenario);
    environment.state = game_running;
    const auto startup_ns = Elapsed(start);
    const auto startup_rss = ResidentBytes();
    auto info = environment.get_info();
    Require(info.left_team.size() == 11 && info.right_team.size() == 11, "Benchmark is not 11v11");
    Require(environment.game_config.physics_steps_per_frame == 10 && !environment.game_config.render, "Wrong simulation mode");
    Match* match = nullptr;
    {
      ContextHolder selected(&environment);
      match = environment.context->gameTask->GetMatch();
      Require(match->GetTeam(0)->GetActivePlayersCount() == 11 && match->GetTeam(1)->GetActivePlayersCount() == 11,
              "Benchmark did not initialize twenty-two active players");
    }
    int kicked_history_frames = 0;
    for (int frame = 0; frame < warmup; ++frame) {
      start = Clock::now();
      environment.StepWithInput(inputs[frame].data(), sizeof(Input));
      warmup_ns.push_back(Elapsed(start));
      kicked_history_frames += match->GetLastTouchTeamID(e_TouchType_Intentional_Kicked) >= 0;
    }
    const auto warm_rss = ResidentBytes();
    const auto warm_snapshot = environment.get_state("benchmark-warmup");
    const auto warm_hash = Hash(environment.get_state_digest());
    const auto actual_start = match->GetActualTime_ms();
    rss_bytes.push_back(ResidentBytes());
    hashes.push_back(warm_hash);
    uint64_t diagnostics_ns = 0;
    const auto loop_start = Clock::now();
    for (int index = 0; index < samples; ++index) {
      const bool active = match->IsInPlay();
      const auto cpu_start = CpuNanoseconds();
      start = Clock::now();
      environment.StepWithInput(inputs[warmup + index].data(), sizeof(Input));
      const auto elapsed = Elapsed(start);
      cpu_ns.push_back(CpuNanoseconds() - cpu_start);
      elapsed_ns.push_back(elapsed);
      (active ? active_ns : stopped_ns).push_back(elapsed);
      active_flags.push_back(active ? 1 : 0);
      kicked_history_frames += match->GetLastTouchTeamID(e_TouchType_Intentional_Kicked) >= 0;
      if ((index + 1) % 100 == 0 || index + 1 == samples) {
        const auto diagnostic_start = Clock::now();
        hashes.push_back(Hash(environment.get_state_digest()));
        rss_bytes.push_back(ResidentBytes());
        diagnostics_ns += Elapsed(diagnostic_start);
      }
    }
    const auto loop_wall_ns = Elapsed(loop_start);
    const auto actual_end = match->GetActualTime_ms();
    const auto final_rss = ResidentBytes();
    const auto final_hash = Hash(environment.get_state_digest());
    Require(active_ns.size() >= static_cast<size_t>(samples / 4), "Too few active-play frames for meaningful timing");
    Require(kicked_history_frames > 0, "Fixture never produced a real intentional ball kick");
    Require(actual_end >= actual_start + static_cast<uint64_t>(samples) * 100, "Fixture did not run every physical tick");
    Require(*std::min_element(elapsed_ns.begin(), elapsed_ns.end()) > 0, "Timer yielded an empty sample");
    Require(GetGame() == nullptr, "Benchmark left a selected TLS environment");
    Require(environment.set_state(warm_snapshot) == "benchmark-warmup", "Warm snapshot did not restore");
    for (int frame = warmup; frame < warmup + samples; ++frame)
      environment.StepWithInput(inputs[frame].data(), sizeof(Input));
    Require(Hash(environment.get_state_digest()) == final_hash, "Measured trajectory could not be replayed");
    rusage usage{};
    Require(getrusage(RUSAGE_SELF, &usage) == 0, "Cannot read process peak RSS");
    start = Clock::now();
    environment.close();
    const auto close_ns = Elapsed(start);
    const auto closed_rss = ResidentBytes();
    Require(!environment.context && GetGame() == nullptr, "Benchmark teardown retained a context");
    std::cout << "{\"passed\":true,\"assertions\":" << assertions << ",\"skipped\":0,\"format\":1"
              << ",\"measurement_storage_prefaulted\":true,\"workload\":\"headless-11v11-long-v1\""
              << ",\"seed\":" << seed << ",\"warmup_frames\":" << warmup << ",\"measured_frames\":" << samples
              << ",\"cpu\":" << cpu << ",\"players\":[11,11],\"slots\":[2,2],\"physics_ticks_per_frame\":10"
              << ",\"logical_frame_budget_ns\":100000000,\"input_hash\":\"" << input_hash
              << "\",\"warm_hash\":\"" << warm_hash << "\",\"final_hash\":\"" << final_hash
              << "\",\"snapshot_replay\":true,\"startup_ns\":" << startup_ns << ",\"close_ns\":" << close_ns
              << ",\"initial_rss_bytes\":" << initial_rss << ",\"startup_rss_bytes\":" << startup_rss
              << ",\"warm_rss_bytes\":" << warm_rss << ",\"final_rss_bytes\":" << final_rss
              << ",\"closed_rss_bytes\":" << closed_rss << ",\"peak_rss_bytes\":" << uint64_t(usage.ru_maxrss) * 1024
              << ",\"actual_start_ms\":" << actual_start << ",\"actual_end_ms\":" << actual_end
              << ",\"kicked_history_frames\":" << kicked_history_frames << ",\"diagnostics_ns\":" << diagnostics_ns
              << ",\"loop_wall_ns\":" << loop_wall_ns << ",\"warmup\":";
    Distribution(warmup_ns);
    std::cout << ",\"steady\":"; Distribution(elapsed_ns);
    std::cout << ",\"active\":"; Distribution(active_ns);
    std::cout << ",\"stopped\":"; Distribution(stopped_ns);
    std::cout << ",\"cpu_time\":"; Distribution(cpu_ns);
    std::cout << ",\"raw_warmup_ns\":"; Numbers(warmup_ns);
    std::cout << ",\"raw_frame_ns\":"; Numbers(elapsed_ns);
    std::cout << ",\"raw_cpu_ns\":"; Numbers(cpu_ns);
    std::cout << ",\"active_flags\":"; Numbers(active_flags);
    std::cout << ",\"rss_checkpoints_bytes\":"; Numbers(rss_bytes);
    std::cout << ",\"state_checkpoints\":[";
    for (size_t index = 0; index < hashes.size(); ++index) {
      if (index) std::cout << ',';
      std::cout << '"' << hashes[index] << '"';
    }
    std::cout << "]}" << std::endl;
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Long-match benchmark: " << error.what() << std::endl;
    return 1;
  }
}
