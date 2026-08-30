// Copyright 2019 Google LLC & Contributors
// Integrated frame sync client: connects to server, runs GameEnv,
// implements prediction & rollback with real game state.

#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"
#include "frame_sync/client_state.hpp"
#include "frame_sync/engine_integration.hpp"
#include "frame_sync/engine_bridge.hpp"
#include "game_env.hpp"
#include "main.hpp"

// 2026-08-26 兼容修复（原因）：GCC 15 的 libstdc++ 不再向系统 Boost 1.75 的
// awaitable.hpp 传递提供 <utility>（std::exchange 未声明），须先于 asio 显式包含。
#include <utility>
#include <boost/asio.hpp>
#include <chrono>
#include <cstring>
#include <deque>
#include <iostream>
#include <print>
#include <memory>
#include <mutex>
#include <queue>
#include <string>
#include <thread>
#include <vector>

namespace asio = boost::asio;
using tcp = asio::ip::tcp;

// ===== FrameSyncClient (same as asio_client.cpp but with GameEnv integration) =====

class IntegratedFrameSyncClient {
 public:
  IntegratedFrameSyncClient(asio::io_context& io, const std::string& host,
                            unsigned short port, GameEnv* env,
                            const frame_sync::MultiplayerConfig& config)
      : io_(io), socket_(io), host_(host), port_(port),
        env_(env), config_(config),
        client_state_(frame_sync::MAX_PREDICT_AHEAD_FRAMES + 4) {
    // Wire up engine callbacks to GameEnv
    engine_ = frame_sync::MakeGameEnvCallbacks(env);
  }

  bool connect() {
    boost::system::error_code ec;
    tcp::resolver resolver(io_);
    auto endpoints = resolver.resolve(host_, std::to_string(port_), ec);
    if (ec) {
      std::println(stderr, "Resolve failed: {}", ec.message());
      return false;
    }
    asio::connect(socket_, endpoints, ec);
    if (ec) {
      std::println(stderr, "Connect failed: {}", ec.message());
      return false;
    }
    recv_buf_.clear();
    if (!receive_session_start()) return false;
    if (!receive_slot_assignment()) return false;

    // Initialize game environment with session params
    init_game_env();

    send_ready();
    do_read();
    return true;
  }

  enum class StepResult {
    kNormal,
    kWaitForAuthority,
    kRollback,
    kCatchup,
  };

  StepResult tick(const frame_sync::SlotInput& my_input) {
    // 1. Dynamic frame catching
    int frames_to_process = client_state_.catchup_count(
        last_confirmed_frame_, current_frame_id_);
    if (frames_to_process < 0) {
      return StepResult::kWaitForAuthority;
    }
    if (frames_to_process == 0) frames_to_process = 1;

    // 2. Check prediction cap
    auto lag = current_frame_id_ - last_confirmed_frame_;
    if (lag >= static_cast<frame_sync::frame_id_t>(
            frame_sync::MAX_PREDICT_AHEAD_FRAMES)) {
      return StepResult::kWaitForAuthority;
    }
    if (frames_without_packet_ >= frame_sync::MAX_FRAMES_WITHOUT_PACKET) {
      return StepResult::kWaitForAuthority;
    }

    // 3. Process frames
    StepResult result = StepResult::kNormal;
    for (int f = 0; f < frames_to_process; ++f) {
      // Save snapshot
      if (engine_.save_state) {
        client_state_.save_snapshot(current_frame_id_, my_input,
                                   engine_.save_state);
      }

      // Step with input
      if (engine_.step) {
        engine_.step(my_input);
      }
      predicted_inputs_[current_frame_id_] = my_input;
      ++current_frame_id_;
      ++frames_without_packet_;

      if (frames_to_process > 1) {
        result = StepResult::kCatchup;
      }
    }

    // 4. Process authoritative frames
    frame_sync::frame_id_t auth_fid;
    std::vector<frame_sync::SlotInput> auth_inputs;
    while (pop_authoritative_frame(&auth_fid, &auth_inputs)) {
      if (auth_fid <= last_confirmed_frame_) {
        continue;
      }

      if (auth_fid < current_frame_id_) {
        // Rollback needed
        if (engine_.restore_state && engine_.step) {
          bool ok = client_state_.rollback_to(
              auth_fid, auth_inputs[my_slot_index_],
              engine_.restore_state, engine_.step);
          if (ok) {
            // Re-simulate from auth_fid+1 to current
            for (auto f = auth_fid + 1; f < current_frame_id_; ++f) {
              auto it = predicted_inputs_.find(f);
              if (it != predicted_inputs_.end() && engine_.step) {
                engine_.step(it->second);
              }
            }
            result = StepResult::kRollback;
          }
        }
      } else {
        // Auth frame ahead — apply directly
        if (engine_.step) {
          for (size_t i = 0; i < auth_inputs.size(); ++i) {
            engine_.step(auth_inputs[i]);
          }
        }
        current_frame_id_ = auth_fid + 1;
      }

      last_confirmed_frame_ = auth_fid;
      frames_without_packet_ = 0;
    }

    // 5. Record frame arrival
    auto now = std::chrono::steady_clock::now();
    double now_ms = std::chrono::duration<double, std::milli>(
        now.time_since_epoch()).count();
    client_state_.record_frame_arrival(now_ms);

    // 6. Evict old snapshots
    client_state_.evict_old(current_frame_id_);

    return result;
  }

  void send_frame_input(frame_sync::frame_id_t frame_id,
                        const uint16_t* slot_indices,
                        const frame_sync::SlotInput* inputs,
                        uint16_t num_slots) {
    std::vector<uint8_t> buf(256);
    size_t n = frame_sync::PackClientFrameInput(
        frame_id, slot_indices, inputs, num_slots, buf.data(), buf.size());
    if (n == 0) return;
    boost::system::error_code ec;
    asio::write(socket_, asio::buffer(buf.data(), n), ec);
  }

  bool pop_authoritative_frame(frame_sync::frame_id_t* frame_id,
                               std::vector<frame_sync::SlotInput>* inputs) {
    std::lock_guard<std::mutex> lock(mu_);
    if (auth_queue_.empty()) return false;
    *frame_id = auth_queue_.front().first;
    *inputs = auth_queue_.front().second;
    auth_queue_.pop();
    return true;
  }

  // Accessors
  const std::vector<uint16_t>& my_slots() const { return my_slots_; }
  uint32_t seed() const { return seed_; }
  uint16_t left_agents() const { return left_agents_; }
  uint16_t right_agents() const { return right_agents_; }
  frame_sync::frame_id_t current_frame_id() const { return current_frame_id_; }
  frame_sync::frame_id_t last_confirmed_frame() const { return last_confirmed_frame_; }
  int rollback_count() const { return client_state_.rollback_count(); }

 private:
  void init_game_env() {
    // Create scenario config from session params
    auto scenario = ScenarioConfig::make();
    scenario->left_agents = left_agents_;
    scenario->right_agents = right_agents_;
    scenario->game_engine_random_seed = seed_;

    // Initialize the game environment
    env_->start_game();
    env_->reset(*scenario, false);

    std::println("Game environment initialized: {}v{}, seed={}",
                 left_agents_, right_agents_, seed_);
  }

  bool receive_session_start() {
    uint8_t buf[32];
    size_t n = read_exact(buf, 1 + frame_sync::SESSION_START_PARAMS_BYTES);
    if (n == 0) return false;
    return frame_sync::UnpackSessionStart(buf, n, &seed_, &left_agents_,
                                          &right_agents_) != 0;
  }

  bool receive_slot_assignment() {
    uint8_t buf[64];
    size_t n = read_exact(buf, 1 + 2);
    if (n < 3) return false;
    if (buf[0] != static_cast<uint8_t>(frame_sync::MessageType::SlotAssignment))
      return false;
    uint16_t num;
    memcpy(&num, buf + 1, 2);
    if (num > 32) return false;
    n = read_exact(buf, num * 2);
    if (n != num * 2) return false;
    my_slots_.resize(num);
    for (uint16_t i = 0; i < num; ++i)
      memcpy(&my_slots_[i], buf + i * 2, 2);
    if (!my_slots_.empty()) my_slot_index_ = my_slots_[0];
    return true;
  }

  size_t read_exact(uint8_t* buf, size_t need) {
    size_t got = 0;
    while (got < need) {
      boost::system::error_code ec;
      size_t n = asio::read(socket_, asio::buffer(buf + got, need - got), ec);
      if (ec || n == 0) return 0;
      got += n;
    }
    return got;
  }

  void send_ready() {
    uint8_t buf[4];
    size_t n = frame_sync::PackReady(buf, sizeof(buf));
    asio::write(socket_, asio::buffer(buf, n));
  }

  void do_read() {
    auto buf = std::make_shared<std::vector<uint8_t>>(4096);
    socket_.async_read_some(
        asio::buffer(*buf),
        [this, buf](boost::system::error_code ec, std::size_t length) {
          if (ec) return;
          std::lock_guard<std::mutex> lock(mu_);
          recv_buf_.insert(recv_buf_.end(), buf->begin(), buf->begin() + length);
          while (parse_one_message()) {}
          do_read();
        });
  }

  bool parse_one_message() {
    if (recv_buf_.empty()) return false;
    uint8_t type = recv_buf_[0];

    if (type == static_cast<uint8_t>(frame_sync::MessageType::AuthoritativeFrame)) {
      if (recv_buf_.size() < 7u) return false;
      uint16_t num_slots;
      memcpy(&num_slots, recv_buf_.data() + 5, 2);
      size_t need = 7 + num_slots * frame_sync::SLOT_INPUT_BYTES;
      if (recv_buf_.size() < need) return false;
      frame_sync::frame_id_t fid;
      std::vector<frame_sync::SlotInput> inputs;
      size_t used = frame_sync::UnpackAuthoritativeFrame(
          recv_buf_.data(), recv_buf_.size(), &fid, &inputs);
      if (used == 0) return false;
      auth_queue_.emplace(fid, std::move(inputs));
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + used);
      return true;
    }

    if (type == static_cast<uint8_t>(frame_sync::MessageType::StateHash)) {
      if (recv_buf_.size() < frame_sync::STATE_HASH_PACK_BYTES) return false;
      frame_sync::frame_id_t fid;
      uint64_t hash;
      size_t used = frame_sync::UnpackStateHash(
          recv_buf_.data(), recv_buf_.size(), &fid, &hash);
      if (used == 0) return false;
      client_state_.record_server_hash(fid, hash);
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + used);
      return true;
    }

    recv_buf_.erase(recv_buf_.begin());
    return true;
  }

  // Members
  asio::io_context& io_;
  tcp::socket socket_;
  std::string host_;
  unsigned short port_;
  std::mutex mu_;
  std::vector<uint8_t> recv_buf_;
  std::queue<std::pair<frame_sync::frame_id_t, std::vector<frame_sync::SlotInput>>> auth_queue_;
  std::vector<uint16_t> my_slots_;
  uint16_t my_slot_index_ = 0;
  uint32_t seed_ = 0;
  uint16_t left_agents_ = 0, right_agents_ = 0;

  // Game environment
  GameEnv* env_;
  frame_sync::MultiplayerConfig config_;
  frame_sync::EngineCallbacks engine_;

  // Prediction state
  frame_sync::frame_id_t current_frame_id_ = 0;
  frame_sync::frame_id_t last_confirmed_frame_ = 0;
  int frames_without_packet_ = 0;
  std::unordered_map<frame_sync::frame_id_t, frame_sync::SlotInput> predicted_inputs_;

  // Client state ring buffer
  frame_sync::ClientState client_state_;
};

// ===== Main =====

int main(int argc, char* argv[]) {
  if (argc < 3) {
    std::println(stderr, "Usage: {} <host> <port> [left_agents] [right_agents] [seed]",
                 argv[0]);
    return 1;
  }

  frame_sync::MultiplayerConfig config;
  config.host = argv[1];
  config.port = static_cast<unsigned short>(std::stoi(argv[2]));
  if (argc >= 4) config.left_agents = static_cast<uint16_t>(std::stoi(argv[3]));
  if (argc >= 5) config.right_agents = static_cast<uint16_t>(std::stoi(argv[4]));
  if (argc >= 6) config.seed = static_cast<uint32_t>(std::stoul(argv[5]));
  config.is_server = false;

  std::println("Connecting to {}:{} ({}v{}, seed={})",
               config.host, config.port,
               config.left_agents, config.right_agents, config.seed);

  // Initialize game environment
  GameEnv env;

  asio::io_context io;
  IntegratedFrameSyncClient client(io, config.host, config.port, &env, config);

  if (!client.connect()) {
    std::println(stderr, "Failed to connect");
    return 1;
  }

  std::println("Connected! My slots: {}, seed={}", client.my_slots().size(), client.seed());

  // Main game loop
  auto period = std::chrono::milliseconds(1000 / config.frame_rate_hz);
  frame_sync::SlotInput my_input = frame_sync::SlotInput::Default();

  while (true) {
    auto t0 = std::chrono::steady_clock::now();

    // Send input for current frame
    client.send_frame_input(client.current_frame_id(), nullptr, &my_input, 0);

    // Run prediction tick
    auto result = client.tick(my_input);

    switch (result) {
      case IntegratedFrameSyncClient::StepResult::kRollback:
        std::println("Rollback at frame {} (total: {})",
                     client.current_frame_id(), client.rollback_count());
        break;
      case IntegratedFrameSyncClient::StepResult::kWaitForAuthority:
        break;
      default:
        break;
    }

    // Render
    env.render();

    // Maintain frame rate
    auto elapsed = std::chrono::steady_clock::now() - t0;
    if (elapsed < period)
      std::this_thread::sleep_for(period - elapsed);
  }

  return 0;
}
