// Copyright 2019 Google LLC & Contributors
// Integrated frame sync server: runs GameEnv headless, collects inputs,
// broadcasts authoritative frames, and validates determinism.

#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"
#include "frame_sync/engine_integration.hpp"
#include "frame_sync/engine_bridge.hpp"
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

  explicit ClientSession(asio::io_context& io) : socket(io) {}
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
  void init_game_env() {
    auto scenario = ScenarioConfig::make();
    scenario->left_agents = config_.left_agents;
    scenario->right_agents = config_.right_agents;
    scenario->game_engine_random_seed = config_.seed;

    env_.start_game();
    env_.reset(*scenario, false);

    std::println("Server game environment initialized: {}v{}, seed={}",
                 config_.left_agents, config_.right_agents, config_.seed);
  }

  void apply_inputs_to_engine() {
    // Convert SlotInput to game actions
    // This is a simplified version - in production, you'd use
    // DecodeAndApplyFrameInput with the engine's controllers
    std::lock_guard<std::mutex> lock(mu_);
    for (size_t i = 0; i < num_slots_; ++i) {
      const auto& input = current_inputs_[i];
      // TODO: Apply input to game controller
      // For now, just log the input
      if (input.dir_x != 0 || input.dir_y != 0 || input.buttons != 0) {
        // std::println("Slot {}: dir=({:.2f}, {:.2f}) buttons={:#06x}",
        //              i, input.dir_x, input.dir_y, input.buttons);
      }
    }
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

      clients_.push_back(client);
      std::println("Client connected, assigned slot {}", client->assigned_slots[0]);

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
          if (e.first < num_slots_) {
            current_inputs_[e.first] = e.second;
          }
        }
        received_from_.insert(client.get());
      }

      client->recv_buf.erase(client->recv_buf.begin(),
                             client->recv_buf.begin() + used);
      return true;
    }

    return false;
  }

  // Members
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
