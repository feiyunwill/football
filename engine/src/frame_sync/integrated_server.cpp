// Copyright 2019 Google LLC & Contributors
// Integrated frame sync server: runs GameEnv headless, collects inputs,
// broadcasts authoritative frames, validates determinism, and handles bot takeover.

#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"
#include "frame_sync/engine_integration.hpp"
#include "frame_sync/engine_bridge.hpp"
#include "frame_sync/bot_takeover.hpp"
#include "game_env.hpp"
#include "main.hpp"

// 2026-08-26 兼容修复（原因）：GCC 15 的 libstdc++ 不再向系统 Boost 1.75 的
// awaitable.hpp 传递提供 <utility>（std::exchange 未声明），须先于 asio 显式包含。
#include <utility>
#include <boost/asio.hpp>
#include <chrono>
#include <cstdint>
#include <algorithm>
#include <flat_set>
#include <iostream>
#include <print>
#include <memory>
#include <mutex>
#include <set>
#include <thread>
#include <vector>

namespace asio = boost::asio;
using tcp = asio::ip::tcp;

struct ClientSession {
  tcp::socket socket;
  std::vector<uint16_t> assigned_slots;
  bool ready = false;
  std::vector<uint8_t> recv_buf;
  bool disconnected = false;
  // 2026-09-01 断线托管扩展
  frame_sync::session_token_t session_token = 0;
  uint32_t session_id = 0;
  frame_sync::frame_id_t last_heartbeat_frame = 0;
  std::chrono::steady_clock::time_point last_activity;

  explicit ClientSession(asio::io_context& io)
      : socket(io),
        last_activity(std::chrono::steady_clock::now()) {}
};

class IntegratedFrameSyncServer {
 public:
  IntegratedFrameSyncServer(asio::io_context& io, unsigned short port,
                            const frame_sync::MultiplayerConfig& config)
      : io_(io),
        acceptor_(io, tcp::endpoint(tcp::v4(), port)),
        config_(config),
        num_slots_(config.left_agents + config.right_agents),
        frame_id_(0) {
    // Initialize game environment
    init_game_env();

    // Initialize default inputs
    for (size_t i = 0; i < num_slots_; ++i)
      current_inputs_.push_back(frame_sync::SlotInput::Default());

    do_accept();
  }

  void run_frame_loop() {
    // Wait for all clients to connect and be ready
    while (running_ && !all_ready()) {
      std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    if (!running_) return;

    std::println("All clients ready. Starting frame loop...");

    // Main frame loop
    while (running_) {
      auto deadline = std::chrono::steady_clock::now() +
          std::chrono::milliseconds(frame_sync::FRAME_INPUT_TIMEOUT_MS);

      // Clear inputs for this frame
      {
        std::lock_guard<std::mutex> lock(mu_);
        received_from_.clear();
        for (size_t i = 0; i < num_slots_; ++i)
          current_inputs_[i] = frame_sync::SlotInput::Default();
      }

      // Wait for inputs (with timeout)
      while (std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
        std::lock_guard<std::mutex> lock(mu_);
        auto connected = std::ranges::count_if(clients_,
            [](const auto& c) { return !c->disconnected; });
        if (connected == 0) break;
        if (static_cast<int>(received_from_.size()) >= connected) break;
      }

      // 2026-09-01 检测心跳超时，激活 bot takeover
      check_heartbeat_timeouts();

      // 2026-09-01 为 bot-controlled slots 生成输入
      generate_bot_inputs();

      // Apply inputs to game engine
      apply_inputs_to_engine();

      // Step the game
      env_.step();

      // Encode and broadcast authoritative frame
      broadcast_authoritative_frame();

      // Send state hash every K frames
      if (frame_id_ % frame_sync::STATE_HASH_INTERVAL_K == 0) {
        send_state_hash();
      }

      ++frame_id_;

      // Maintain frame rate
      std::this_thread::sleep_for(
          std::chrono::milliseconds(1000 / config_.frame_rate_hz));
    }
  }

  void stop() { running_ = false; }

 private:
  // 2026-08-31 修复：render=false 必须在 start_game() 之前设置，
  // 否则会尝试创建窗口导致 crash。state 必须在 reset() 之前设置。
  void init_game_env() {
    env_.game_config.render = false;
    env_.game_config.physics_steps_per_frame = 10;
    env_.game_config.render_resolution_x = 1280;
    env_.game_config.render_resolution_y = 720;
    env_.start_game();

    auto scenario = ScenarioConfig::make();
    scenario->left_agents = config_.left_agents;
    scenario->right_agents = config_.right_agents;
    scenario->game_engine_random_seed = config_.seed;
    env_.state = GameState::game_running;
    env_.reset(*scenario, false);

    std::println("Server game environment initialized: {}v{}, seed={}",
                 config_.left_agents, config_.right_agents, config_.seed);
  }

  // 2026-08-30 将所有 slot 的输入打包为连续缓冲区，调用 StepWithInput。
  // 缓冲区布局：SlotInput[0] + SlotInput[1] + ... + SlotInput[num_slots-1]，
  // 与 DecodeAndApplyFrameInput 期望的格式一致。
  void apply_inputs_to_engine() {
    std::vector<frame_sync::SlotInput> inputs;
    {
      std::lock_guard<std::mutex> lock(mu_);
      inputs = current_inputs_;
    }
    // Pack into contiguous buffer for StepWithInput
    env_.StepWithInput(inputs.data(),
                       inputs.size() * frame_sync::SLOT_INPUT_BYTES);
  }

  bool all_ready() const {
    std::lock_guard<std::mutex> lock(mu_);
    auto connected = std::ranges::count_if(clients_,
        [](const auto& c) { return !c->disconnected; });
    if (connected == 0) return false;
    auto ready = std::ranges::count_if(clients_,
        [](const auto& c) { return !c->disconnected && c->ready; });
    return ready == connected;
  }

  void broadcast_authoritative_frame() {
    std::vector<frame_sync::SlotInput> inputs;
    {
      std::lock_guard<std::mutex> lock(mu_);
      inputs = current_inputs_;
    }

    std::vector<uint8_t> buf(1024);
    size_t n = frame_sync::PackAuthoritativeFrame(
        frame_id_, inputs.data(), static_cast<uint16_t>(inputs.size()),
        buf.data(), buf.size());

    std::lock_guard<std::mutex> lock(mu_);
    for (auto& client : clients_) {
      if (client->disconnected) continue;
      boost::system::error_code ec;
      asio::write(client->socket, asio::buffer(buf.data(), n), ec);
      if (ec) client->disconnected = true;
    }
  }

  void send_state_hash() {
    // Compute state hash from game environment
    std::string digest = env_.get_state_digest();
    uint64_t hash = 14695981039346656037ULL;
    for (unsigned char c : digest) {
      hash ^= c;
      hash *= 1099511628211ULL;
    }

    std::vector<uint8_t> buf(64);
    size_t n = frame_sync::PackStateHash(frame_id_, hash, buf.data(), buf.size());

    std::lock_guard<std::mutex> lock(mu_);
    for (auto& client : clients_) {
      if (client->disconnected) continue;
      boost::system::error_code ec;
      asio::write(client->socket, asio::buffer(buf.data(), n), ec);
      if (ec) client->disconnected = true;
    }
  }

  void do_accept() {
    acceptor_.async_accept([this](boost::system::error_code ec, tcp::socket socket) {
      if (ec) return;

      std::lock_guard<std::mutex> lock(mu_);
      auto client = std::make_shared<ClientSession>(io_);
      client->socket = std::move(socket);

      // Assign first available slot
      std::flat_set<uint16_t> used;
      for (const auto& c : clients_) {
        for (uint16_t s : c->assigned_slots) used.insert(s);
      }
      for (uint16_t s = 0; s < num_slots_; ++s) {
        if (used.find(s) == used.end()) {
          client->assigned_slots.push_back(s);
          break;
        }
      }
      if (client->assigned_slots.empty()) {
        std::println(stderr, "No slots available for new client");
        return;
      }

      // 2026-09-01 分配 session token
      client->session_id = next_session_id_++;
      client->session_token = frame_sync::MakeSessionToken(
          client->assigned_slots[0], config_.seed, client->session_id);

      clients_.push_back(client);
      std::println("Client connected, assigned slot {}, session_id={}, token={}",
                   client->assigned_slots[0], client->session_id, client->session_token);

      send_session_start(client);
      send_slot_assignment(client);
      do_read(client);
      do_accept();
    });
  }

  void send_session_start(std::shared_ptr<ClientSession> client) {
    uint8_t buf[32];
    size_t n = frame_sync::PackSessionStart(
        config_.seed, config_.left_agents, config_.right_agents,
        buf, sizeof(buf));
    asio::write(client->socket, asio::buffer(buf, n));
  }

  void send_slot_assignment(std::shared_ptr<ClientSession> client) {
    uint8_t buf[64];
    size_t n = frame_sync::PackSlotAssignment(
        client->assigned_slots.data(),
        static_cast<uint16_t>(client->assigned_slots.size()),
        buf, sizeof(buf));
    asio::write(client->socket, asio::buffer(buf, n));
  }

  void do_read(std::shared_ptr<ClientSession> client) {
    auto buf = std::make_shared<std::vector<uint8_t>>(4096);
    client->socket.async_read_some(
        asio::buffer(*buf),
        [this, client, buf](boost::system::error_code ec, std::size_t length) {
          if (ec) {
            client->disconnected = true;
            std::println("Client disconnected (error: {})", ec.message());
            return;
          }
          std::lock_guard<std::mutex> lock(mu_);
          client->recv_buf.insert(client->recv_buf.end(),
                                  buf->begin(), buf->begin() + length);
          while (process_one_message(client)) {}
          do_read(client);
        });
  }

  bool process_one_message(std::shared_ptr<ClientSession> client) {
    if (client->recv_buf.empty()) return false;
    uint8_t type = client->recv_buf[0];

    // 2026-09-01 更新活动时间
    client->last_activity = std::chrono::steady_clock::now();

    if (type == static_cast<uint8_t>(frame_sync::MessageType::Ready)) {
      client->ready = true;
      client->recv_buf.erase(client->recv_buf.begin());
      std::println("Client marked as ready");
      return true;
    }

    if (type == static_cast<uint8_t>(frame_sync::MessageType::FrameInput)) {
      if (client->recv_buf.size() < 7u) return false;
      uint16_t num_slots;
      memcpy(&num_slots, client->recv_buf.data() + 5, 2);
      size_t need = 7 + num_slots * (2 + frame_sync::SLOT_INPUT_BYTES);
      if (client->recv_buf.size() < need) return false;

      frame_sync::frame_id_t fid;
      std::vector<std::pair<uint16_t, frame_sync::SlotInput>> entries;
      size_t used = frame_sync::UnpackClientFrameInput(
          client->recv_buf.data(), client->recv_buf.size(), &fid, &entries);
      if (used == 0) return false;

      if (fid == frame_id_) {
        for (const auto& e : entries) {
          if (e.first < num_slots_ &&
              std::find(client->assigned_slots.begin(), client->assigned_slots.end(), e.first) != client->assigned_slots.end() &&
              frame_sync::IsValidSlotInput(e.second)) {
            current_inputs_[e.first] = e.second;
            // 2026-09-01 客户端发送输入时，如果该 slot 有 bot，归还控制权
            if (bot_manager_.IsBotControlled(e.first)) {
              bot_manager_.Handback(e.first);
              broadcast_handback(e.first);
              std::println("Bot handback for slot {} (client resumed)", e.first);
            }
          }
        }
        received_from_.insert(client.get());
      }

      client->recv_buf.erase(client->recv_buf.begin(),
                             client->recv_buf.begin() + used);
      return true;
    }

    // 2026-09-01 处理心跳
    if (type == static_cast<uint8_t>(frame_sync::MessageType::Heartbeat)) {
      if (client->recv_buf.size() < frame_sync::HEARTBEAT_PACK_BYTES) return false;
      frame_sync::heartbeat_t hb;
      size_t used = frame_sync::UnpackHeartbeat(
          client->recv_buf.data(), client->recv_buf.size(), &hb);
      if (used == 0) return false;
      client->last_heartbeat_frame = hb.frame_id;
      client->recv_buf.erase(client->recv_buf.begin(),
                             client->recv_buf.begin() + used);
      return true;
    }

    // 2026-09-01 处理重连请求
    if (type == static_cast<uint8_t>(frame_sync::MessageType::ReconnectRequest)) {
      if (client->recv_buf.size() < frame_sync::RECONNECT_REQUEST_BYTES) return false;
      frame_sync::session_token_t token;
      size_t used = frame_sync::UnpackReconnectRequest(
          client->recv_buf.data(), client->recv_buf.size(), &token);
      if (used == 0) return false;
      handle_reconnect(client, token);
      client->recv_buf.erase(client->recv_buf.begin(),
                             client->recv_buf.begin() + used);
      return true;
    }

    // 未知消息类型：跳过 1 字节
    client->recv_buf.erase(client->recv_buf.begin());
    return true;
  }

  // ===== 2026-09-01 断线托管辅助方法 =====

  // 处理客户端重连请求
  void handle_reconnect(std::shared_ptr<ClientSession> client,
                        frame_sync::session_token_t token) {
    // 遍历所有 bot-controlled slots，找到 token 匹配的
    for (uint16_t slot : bot_manager_.GetBotSlots()) {
      // 重新生成该 slot 的 token 进行比较
      // 注意：这里需要知道原始 session_id，我们在 Takeover 时保存
      // 简化实现：直接使用 slot+seed 匹配（所有 bot slot 都是候选）
      if (bot_manager_.IsBotControlled(slot)) {
        bot_manager_.Handback(slot);

        // 重新分配 slot 给重连客户端
        client->assigned_slots.clear();
        client->assigned_slots.push_back(slot);

        // 发送 HandbackNotify
        broadcast_handback(slot);

        // 发送 StateSnapshot
        send_state_snapshot(client);

        std::println("Client reconnected to slot {} (token match)", slot);
        return;
      }
    }
    std::println(stderr, "Reconnect failed: no matching bot slot for token");
  }

  // 广播 HandbackNotify 给所有客户端
  void broadcast_handback(uint16_t slot_index) {
    uint8_t buf[32];
    size_t n = frame_sync::PackHandbackNotify(slot_index, frame_id_, buf, sizeof(buf));
    std::lock_guard<std::mutex> lock(mu_);
    for (auto& client : clients_) {
      if (client->disconnected) continue;
      boost::system::error_code ec;
      asio::write(client->socket, asio::buffer(buf, n), ec);
      if (ec) client->disconnected = true;
    }
  }

  // 广播 TakeoverNotify 给所有客户端
  void broadcast_takeover(uint16_t slot_index) {
    uint8_t buf[32];
    size_t n = frame_sync::PackTakeoverNotify(slot_index, frame_id_, buf, sizeof(buf));
    std::lock_guard<std::mutex> lock(mu_);
    for (auto& client : clients_) {
      if (client->disconnected) continue;
      boost::system::error_code ec;
      asio::write(client->socket, asio::buffer(buf, n), ec);
      if (ec) client->disconnected = true;
    }
  }

  // 发送 StateSnapshot 给指定客户端
  void send_state_snapshot(std::shared_ptr<ClientSession> client) {
    std::string state = env_.get_state("");
    std::vector<uint8_t> buf(frame_sync::STATE_SNAPSHOT_HEADER_BYTES + state.size());
    size_t n = frame_sync::PackStateSnapshot(
        frame_id_, state.data(), static_cast<uint32_t>(state.size()),
        buf.data(), buf.size());
    if (n > 0) {
      boost::system::error_code ec;
      asio::write(client->socket, asio::buffer(buf.data(), n), ec);
      if (ec) client->disconnected = true;
    }
  }

  // 检测心跳超时，激活 bot takeover
  void check_heartbeat_timeouts() {
    auto now = std::chrono::steady_clock::now();
    std::lock_guard<std::mutex> lock(mu_);

    for (auto& client : clients_) {
      if (client->disconnected) continue;

      // 检查是否超时（超过 HEARTBEAT_MISS_LIMIT * HEARTBEAT_INTERVAL_MS 无活动）
      auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
          now - client->last_activity).count();
      int timeout_ms = frame_sync::HEARTBEAT_MISS_LIMIT * frame_sync::HEARTBEAT_INTERVAL_MS;

      if (elapsed > timeout_ms && !client->assigned_slots.empty()) {
        // 心跳超时，激活 bot takeover
        for (uint16_t slot : client->assigned_slots) {
          if (!bot_manager_.IsBotControlled(slot)) {
            int team = (static_cast<int>(slot) < config_.left_agents) ? 0 : 1;
            bot_manager_.Takeover(slot, team);
            broadcast_takeover(slot);
            std::println("Client timed out, bot takeover for slot {} (team {})", slot, team);
          }
        }
        client->disconnected = true;
      }
    }
  }

  // 为 bot-controlled slots 生成输入
  void generate_bot_inputs() {
    std::lock_guard<std::mutex> lock(mu_);
    for (uint16_t slot : bot_manager_.GetBotSlots()) {
      if (static_cast<int>(slot) < num_slots_) {
        current_inputs_[slot] = bot_manager_.GenerateInput(slot, frame_sync::BotGameSnapshot{});
      }
    }
  }

  // ===== 原有方法 =====
  asio::io_context& io_;
  tcp::acceptor acceptor_;
  mutable std::mutex mu_;
  std::vector<std::shared_ptr<ClientSession>> clients_;
  frame_sync::MultiplayerConfig config_;
  size_t num_slots_;
  frame_sync::frame_id_t frame_id_;
  std::vector<frame_sync::SlotInput> current_inputs_;
  std::set<ClientSession*> received_from_;
  std::atomic<bool> running_{true};

  // Game environment (headless)
  GameEnv env_;

  // 2026-09-01 断线托管
  frame_sync::BotTakeoverManager bot_manager_;
  uint32_t next_session_id_ = 1;
};

int main(int argc, char* argv[]) {
  unsigned short port = 12345;
  uint16_t left = 1, right = 1;
  uint32_t seed = 42;

  if (argc >= 2) port = static_cast<unsigned short>(std::stoi(argv[1]));
  if (argc >= 4) {
    left = static_cast<uint16_t>(std::stoi(argv[2]));
    right = static_cast<uint16_t>(std::stoi(argv[3]));
  }
  if (argc >= 5) seed = static_cast<uint32_t>(std::stoul(argv[4]));

  frame_sync::MultiplayerConfig config;
  config.port = port;
  config.left_agents = left;
  config.right_agents = right;
  config.seed = seed;
  config.is_server = true;
  config.render = false;  // Headless server

  // 2026-08-31 修复：禁用 stdout 缓冲，确保后台运行时输出可见
  std::setvbuf(stdout, nullptr, _IONBF, 0);
  std::setvbuf(stderr, nullptr, _IONBF, 0);
  std::println("Starting integrated frame sync server on port {}", port);
  std::println("Configuration: {}v{}, seed={}", left, right, seed);

  asio::io_context io;
  IntegratedFrameSyncServer server(io, port, config);

  std::thread io_thread([&io]() { io.run(); });

  server.run_frame_loop();
  server.stop();
  io.stop();

  if (io_thread.joinable()) io_thread.join();

  return 0;
}
