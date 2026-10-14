#include "training/ppo_learner.hpp"
#include "training/snapshot_identity.hpp"
#include "frame_sync/state_hash.hpp"
#include "frame_sync/rl_training/checkpoint_file.hpp"
#include <array>
#include <bit>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#if defined(_WIN32)
#include <process.h>
#else
#include <unistd.h>
#endif

namespace football::training {
namespace {
void require(bool condition, const char* message) { if (!condition) throw std::invalid_argument(message); }
uint64_t pid() {
#if defined(_WIN32)
  return ::_getpid();
#else
  return ::getpid();
#endif
}
std::array<uint8_t, 32> digest(std::string_view bytes) {
  frame_sync::SHA256 hash; hash.update(reinterpret_cast<const uint8_t*>(bytes.data()), bytes.size());
  std::array<uint8_t, 32> result; hash.finalize(result.data()); return result;
}
std::string hex(std::string_view bytes) {
  std::string result; const char* alphabet = "0123456789abcdef";
  for (auto value : digest(bytes)) { result += alphabet[value >> 4]; result += alphabet[value & 15]; }
  return result;
}
struct Writer {
  std::string bytes;
  void u32(uint32_t value) { for (int i = 0; i < 4; ++i) bytes += char(value >> (8 * i)); }
  void u64(uint64_t value) { for (int i = 0; i < 8; ++i) bytes += char(value >> (8 * i)); }
  void f32(float value) { require(std::isfinite(value), "Nonfinite PPO checkpoint float"); u32(std::bit_cast<uint32_t>(value)); }
  void f64(double value) { require(std::isfinite(value), "Nonfinite PPO checkpoint double"); u64(std::bit_cast<uint64_t>(value)); }
  void blob(std::string_view value, size_t limit) {
    require(!value.empty() && value.size() <= limit, "PPO checkpoint blob exceeds budget");
    u32(static_cast<uint32_t>(value.size())); bytes.append(value);
    require(bytes.size() <= kMaxPpoCheckpointBytes - 44, "PPO checkpoint exceeds byte budget");
  }
};
struct Reader {
  std::string_view bytes;
  std::string_view take(size_t length) {
    require(length <= bytes.size(), "Truncated PPO checkpoint");
    auto value = bytes.substr(0, length); bytes.remove_prefix(length); return value;
  }
  uint32_t u32() { auto data = take(4); uint32_t value = 0; for (int i = 0; i < 4; ++i) value |= uint32_t(uint8_t(data[i])) << (8*i); return value; }
  uint64_t u64() { auto data = take(8); uint64_t value = 0; for (int i = 0; i < 8; ++i) value |= uint64_t(uint8_t(data[i])) << (8*i); return value; }
  bool flag() { auto value = u32(); require(value <= 1, "Invalid PPO checkpoint flag"); return value != 0; }
  float f32() { auto value = std::bit_cast<float>(u32()); require(std::isfinite(value), "Nonfinite PPO checkpoint float"); return value; }
  double f64() { auto value = std::bit_cast<double>(u64()); require(std::isfinite(value), "Nonfinite PPO checkpoint double"); return value; }
  std::string_view blob(size_t limit) { auto length = u32(); require(length > 0 && length <= limit, "PPO checkpoint blob exceeds budget"); return take(length); }
};
std::shared_ptr<ScenarioConfig> scene(std::string_view bytes) {
  Reader reader{bytes}; require(reader.u32() == 1, "Unknown PPO scenario identity version");
  auto result = ScenarioConfig::make();
  auto vector = [&]() { float x = reader.f32(), y = reader.f32(), z = reader.f32(); return blunted::Vector3(x,y,z); };
  result->ball_position = vector();
  for (auto* team : {&result->left_team, &result->right_team}) {
    const auto count = reader.u32(); require(count >= 1 && count <= 11, "Invalid PPO team size");
    team->resize(count);
    for (auto& player : *team) {
      const auto role = reader.u32(); require(role <= uint32_t(e_PlayerRole_CF), "Invalid PPO player role");
      player.role = static_cast<e_PlayerRole>(role);
      player.position = vector(); player.start_position = vector();
      player.lazy = reader.flag(); player.controllable = reader.flag();
    }
  }
  result->left_agents = std::bit_cast<int32_t>(reader.u32()); result->right_agents = std::bit_cast<int32_t>(reader.u32());
  result->use_magnet = reader.flag(); result->offsides = reader.flag(); result->real_time = reader.flag();
  result->game_engine_random_seed = reader.u32(); result->reverse_team_processing = reader.flag();
  result->left_team_difficulty = reader.f32(); result->right_team_difficulty = reader.f32();
  result->deterministic = reader.flag(); result->end_episode_on_score = reader.flag();
  result->end_episode_on_possession_change = reader.flag(); result->end_episode_on_out_of_play = reader.flag();
  result->game_duration = std::bit_cast<int32_t>(reader.u32()); result->control_all_players = reader.flag();
  result->second_half = std::bit_cast<int32_t>(reader.u32());
  require(reader.bytes.empty() && ScenarioIdentity(*result) == bytes, "PPO scenario identity mismatch");
  return result;
}
PpoLearnerConfig checked(PpoLearnerConfig config) {
  config.policy.validate(); config.parameters.validate();
  require(config.scenario && config.cadence >= 1 && config.cadence <= 1000 &&
          config.episode_limit >= 1 && config.episode_limit <= 4096, "Invalid PPO learner configuration");
  config.scenario = scene(ScenarioIdentity(*config.scenario));
  const auto& value = *config.scenario;
  require(!value.real_time && !value.control_all_players && value.left_agents >= 0 && value.right_agents >= 0 &&
          value.left_agents <= 11 && value.right_agents <= 11 &&
          (value.left_agents == 0) != (value.right_agents == 0) &&
          size_t(value.left_agents + value.right_agents) == config.policy.players, "PPO scenario/player mismatch");
  return config;
}
void specification(Writer& writer, const PolicySpec& spec) {
  writer.u32(spec.players); writer.u32(spec.features); writer.u32(spec.hidden);
  writer.u32(spec.fixed_positions); writer.u32(spec.builtin_ai_action);
}
PolicySpec specification(Reader& reader) {
  PolicySpec result; result.players = reader.u32(); result.features = reader.u32(); result.hidden = reader.u32();
  result.fixed_positions = reader.flag(); result.builtin_ai_action = reader.flag(); result.validate(); return result;
}
void parameters(Writer& writer, const PpoParameters& params) {
  for (double value : {params.gamma, params.lambda, params.clip, params.value_coefficient, params.entropy_coefficient,
                       params.learning_rate, params.beta1, params.beta2, params.adam_epsilon, params.max_gradient_norm}) writer.f64(value);
  writer.u32(params.epochs); writer.u32(params.minibatch); writer.u32(params.normalize_advantage);
}
PpoParameters parameters(Reader& reader) {
  PpoParameters result;
  for (double* value : {&result.gamma, &result.lambda, &result.clip, &result.value_coefficient, &result.entropy_coefficient,
                        &result.learning_rate, &result.beta1, &result.beta2, &result.adam_epsilon, &result.max_gradient_norm}) *value = reader.f64();
  result.epochs = reader.u32(); result.minibatch = reader.u32(); result.normalize_advantage = reader.flag();
  result.validate(); return result;
}
}
PpoLearner::PpoLearner(PpoLearnerConfig config)
    : config_(checked(std::move(config))), policy_(config_.policy, config_.seed ^ UINT64_C(0xa0761d6478bd642f)),
      optimizer_(policy_.parameters().size()), sampling_(config_.seed ^ UINT64_C(0xe7037ed1a0b428db)),
      shuffle_(config_.seed ^ UINT64_C(0x8ebc6af09c88c6e3)), episodes_(config_.seed ^ UINT64_C(0x589965cc75374cc3)),
      env_(std::make_unique<NativePolicyEnvironment>(config_.policy, config_.checkpoint_rewards)),
      owner_thread_(std::this_thread::get_id()), owner_process_(pid()) { reset_episode(); }
void PpoLearner::check_owner() const {
  if (owner_thread_ != std::this_thread::get_id() || owner_process_ != pid())
    throw std::logic_error("PPO learner requires its creating process/thread");
}
PpoLearnerConfig PpoLearner::config() const {
  check_owner(); auto result = config_;
  result.scenario = scene(ScenarioIdentity(*config_.scenario)); return result;
}
void PpoLearner::reset_episode() {
  require(next_episode_ < kMaxPpoCounter, "PPO episode counter exceeded");
  auto proposed = episodes_;
  auto next_scene = scene(ScenarioIdentity(*config_.scenario));
  next_scene->game_engine_random_seed = static_cast<uint32_t>(proposed.index(2000000001));
  env_->reset(*next_scene, config_.cadence);
  current_scene_ = std::move(next_scene); current_episode_ = next_episode_++;
  episode_steps_ = 0; episode_reward_ = 0; episodes_ = proposed;
}
PpoIteration PpoLearner::train(size_t steps) {
  check_owner();
  if (busy_ || failed_) throw std::logic_error("PPO learner is busy or failed; restore a checkpoint");
  require(steps >= 1 && steps <= kMaxPpoRollout && transitions_ <= kMaxPpoCounter - steps &&
          version_ < kMaxPpoCounter, "PPO rollout/counter budget exceeded");
  busy_ = true;
  try {
    std::vector<PpoSample> samples; samples.reserve(steps);
    Writer trajectory;
    PpoIteration result;
    for (size_t i = 0; i < steps; ++i) {
      if (env_->needs_reset()) reset_episode();
      auto value = env_->step(policy_, sampling_, false, episode_steps_ + 1 == config_.episode_limit);
      PpoSample sample;
      sample.observation = std::move(value.observation); sample.actions = value.decision.actions;
      sample.old_log_probability = value.decision.log_probability; sample.old_value = value.decision.value;
      sample.reward = value.reward; sample.terminated = value.following.terminated; sample.truncated = value.truncated;
      sample.next_value = sample.terminated ? 0 : policy_.forward(value.following.observations).value;
      sample.policy_version = version_;
      trajectory.u64(current_episode_); trajectory.u32(episode_steps_);
      for (int action : sample.actions) trajectory.u32(action);
      for (float observed : value.following.observations.buffer()) trajectory.f32(observed);
      for (float reward : value.following.rewards) trajectory.f32(reward);
      trajectory.f64(sample.old_log_probability); trajectory.f64(sample.old_value); trajectory.f64(sample.reward);
      trajectory.u32(sample.terminated); trajectory.u32(sample.truncated);
      episode_reward_ += value.reward; result.reward += value.reward; ++episode_steps_; ++transitions_;
      if (sample.terminated || sample.truncated) ++result.completed_episodes;
      samples.push_back(std::move(sample));
    }
    result.update = UpdatePpo(policy_, optimizer_, shuffle_, samples, version_, config_.parameters);
    ++version_; result.transitions = steps; result.trajectory_sha256 = hex(trajectory.bytes);
    busy_ = false; return result;
  } catch (...) { busy_ = false; failed_ = true; env_->close(); throw; }
}
std::string PpoLearner::get_state() {
  check_owner();
  if (busy_ || failed_) throw std::logic_error("PPO checkpoint requires a successful update boundary");
  static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559);
  Writer payload;
  payload.u32(1); payload.u32(kCategoricalPolicyVersion); payload.u32(kPolicyRngVersion);
  specification(payload, config_.policy); parameters(payload, config_.parameters);
  payload.u64(config_.seed); payload.u32(config_.cadence); payload.u32(config_.episode_limit); payload.u32(config_.checkpoint_rewards);
  payload.blob(ScenarioIdentity(*config_.scenario), snapshot::kMaxScenarioBytes);
  payload.blob(ScenarioIdentity(*current_scene_), snapshot::kMaxScenarioBytes);
  for (auto value : {version_, transitions_, current_episode_, next_episode_}) payload.u64(value);
  payload.u32(episode_steps_); payload.f64(episode_reward_);
  for (auto value : {sampling_.state(), shuffle_.state(), episodes_.state()}) payload.u64(value);
  payload.u32(policy_.parameters().size());
  for (auto values : std::array<std::span<const double>, 3>{policy_.parameters(), optimizer_.first, optimizer_.second})
    for (double value : values) payload.f64(value);
  payload.u64(optimizer_.step);
  auto native = env_->snapshot();
  payload.blob(native.native, snapshot::kMaxBytes + blunted::snapshot::kHeaderBytes);
  payload.u32(native.observation.buffer().size());
  for (float value : native.observation.buffer()) payload.f32(value);
  payload.u32(native.terminated); payload.u32(native.truncated);
  require(payload.bytes.size() <= kMaxPpoCheckpointBytes - 44, "PPO checkpoint budget exceeded");
  Writer envelope; envelope.bytes = "FPPO"; envelope.u32(kPpoCheckpointVersion); envelope.u32(payload.bytes.size());
  const auto checksum = digest(payload.bytes);
  envelope.bytes.append(reinterpret_cast<const char*>(checksum.data()), checksum.size());
  envelope.bytes += payload.bytes; return envelope.bytes;
}
void PpoLearner::set_state(std::string_view bytes) {
  check_owner();
  if (busy_) throw std::logic_error("Cannot restore a busy PPO learner");
  require(bytes.size() >= 44 && bytes.size() <= kMaxPpoCheckpointBytes && bytes.substr(0,4) == "FPPO", "Invalid PPO checkpoint envelope");
  Reader header{bytes.substr(4)};
  require(header.u32() == kPpoCheckpointVersion, "Unsupported PPO checkpoint version");
  const auto length = header.u32(); auto checksum = header.take(32);
  require(length == header.bytes.size(), "PPO checkpoint length mismatch");
  const auto actual = digest(header.bytes);
  require(std::memcmp(checksum.data(), actual.data(), 32) == 0, "PPO checkpoint checksum mismatch");
  Reader reader{header.bytes};
  require(reader.u32() == 1 && reader.u32() == kCategoricalPolicyVersion && reader.u32() == kPolicyRngVersion,
          "Unsupported PPO algorithm/policy/RNG schema");
  const auto spec = specification(reader); const auto params = parameters(reader);
  const auto seed = reader.u64(); const auto cadence = reader.u32(); const auto limit = reader.u32(); const auto checkpoints = reader.flag();
  require(spec == config_.policy && params == config_.parameters && seed == config_.seed && cadence == config_.cadence &&
          limit == config_.episode_limit && checkpoints == config_.checkpoint_rewards, "PPO checkpoint configuration mismatch");
  require(reader.blob(snapshot::kMaxScenarioBytes) == ScenarioIdentity(*config_.scenario), "PPO base scenario mismatch");
  auto current_scene = scene(reader.blob(snapshot::kMaxScenarioBytes));
  auto expected_scene = scene(ScenarioIdentity(*config_.scenario));
  expected_scene->game_engine_random_seed = current_scene->game_engine_random_seed;
  require(current_scene->game_engine_random_seed <= 2000000000 && ScenarioIdentity(*expected_scene) == ScenarioIdentity(*current_scene),
          "PPO current scenario mismatch");
  const auto version = reader.u64(), transitions = reader.u64(), current_episode = reader.u64(), next_episode = reader.u64();
  const auto episode_steps = reader.u32(); const auto episode_reward = reader.f64();
  PolicyRng sampling(reader.u64()), shuffle(reader.u64()), episodes(reader.u64());
  require(version <= kMaxPpoCounter && transitions <= kMaxPpoCounter && current_episode < kMaxPpoCounter &&
          next_episode == current_episode + 1 && current_episode <= transitions &&
          episode_steps <= limit && episode_steps <= transitions &&
          (version == 0 ? transitions == 0 : transitions >= version && transitions <= version * kMaxPpoRollout),
          "PPO checkpoint counters disagree");
  CategoricalPolicy policy(spec, 0);
  require(reader.u32() == policy.parameters().size(), "PPO checkpoint parameter count mismatch");
  auto weights = policy.parameters(); AdamState optimizer(weights.size());
  for (auto* values : {&weights, &optimizer.first, &optimizer.second})
    for (double& value : *values) value = reader.f64();
  policy.set_parameters(weights); optimizer.step = reader.u64();
  require(optimizer.step <= kMaxPpoCounter && (version == 0 ? optimizer.step == 0 :
          optimizer.step >= version * params.epochs && optimizer.step <= version * params.epochs *
          ((kMaxPpoRollout + params.minibatch - 1) / params.minibatch)), "PPO optimizer/version mismatch");
  for (size_t i = 0; i < weights.size(); ++i) {
    require(optimizer.second[i] >= 0 && (optimizer.step != 0 || (optimizer.first[i] == 0 && optimizer.second[i] == 0)),
            "Invalid PPO optimizer moments");
  }
  NativePolicySnapshot native;
  native.native = std::string(reader.blob(snapshot::kMaxBytes + blunted::snapshot::kHeaderBytes));
  require(reader.u32() == spec.inputs(), "PPO checkpoint observation count mismatch");
  native.observation = ObservationBuffer(spec.players, spec.features);
  for (float& value : native.observation.buffer()) value = reader.f32();
  native.terminated = reader.flag(); native.truncated = reader.flag();
  require(reader.bytes.empty() && !(native.terminated && native.truncated) &&
          native.truncated == (episode_steps == limit && !native.terminated) &&
          (episode_steps > 0 || (!native.terminated && !native.truncated && episode_reward == 0)),
          "PPO checkpoint lifecycle mismatch");
  // Validate/restore a separate engine, so every target field remains unchanged on failure.
  auto prepared_env = std::make_unique<NativePolicyEnvironment>(spec, checkpoints);
  prepared_env->reset(*current_scene, cadence);
  prepared_env->restore(native);
  // Verify current observation also evaluates finitely before commit.
  (void)policy.forward(native.observation);
  policy_ = std::move(policy); optimizer_.swap(optimizer);
  sampling_ = sampling; shuffle_ = shuffle; episodes_ = episodes;
  env_.swap(prepared_env); current_scene_.swap(current_scene);
  version_ = version; transitions_ = transitions; current_episode_ = current_episode; next_episode_ = next_episode;
  episode_steps_ = episode_steps; episode_reward_ = episode_reward; failed_ = false;
}
void PpoLearner::save(const std::filesystem::path& path) {
  auto bytes = get_state();
  const auto result = SaveCheckpointFile(std::span<const char>(bytes.data(), bytes.size()), path, kMaxPpoCheckpointBytes);
  if (!result) throw std::runtime_error(std::string("PPO checkpoint write failed: ") + result.stage);
}
void PpoLearner::load(const std::filesystem::path& path) {
  check_owner();
  const auto result = ReadCheckpointFile(path, kMaxPpoCheckpointBytes);
  if (!result) throw std::runtime_error(std::string("PPO checkpoint read failed: ") + result.stage);
  set_state(std::string_view(result.bytes.data(), result.bytes.size()));
}
}  // namespace football::training
