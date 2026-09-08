// Copyright 2019 Google LLC & Contributors
// Reconnecting frame sync client: wraps FrameSyncClient with auto-reconnect.
// When connection drops, attempts to reconnect with exponential backoff.
// Preserves slot assignment and game state across reconnections.

#ifndef GFOOTBALL_FRAME_SYNC_RECONNECTING_CLIENT_HPP
#define GFOOTBALL_FRAME_SYNC_RECONNECTING_CLIENT_HPP

#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"
#include "frame_sync/client_state.hpp"
#include "frame_sync/engine_integration.hpp"

#include <utility>
#include <boost/asio.hpp>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <functional>
#include <iostream>
#include <print>
#include <mutex>
#include <queue>
#include <string>
#include <thread>
#include <vector>

namespace asio = boost::asio;
using tcp = asio::ip::tcp;

namespace frame_sync {

// Reconnection state
enum class ReconnectState : std::uint8_t {
  kConnected,
  kDisconnected,
  kReconnecting,
  kFailed,  // max retries exceeded
};

class ReconnectingClient {
 public:
  // Callbacks for reconnection events
  struct Callbacks {
    std::move_only_function<void()> on_disconnect;
    std::move_only_function<void(int attempt)> on_reconnect_attempt;
    std::move_only_function<void()> on_reconnect_success;
    std::move_only_function<void()> on_reconnect_failed;
  };

  ReconnectingClient(asio::io_context& io, const std::string& host,
                     unsigned short port, const MultiplayerConfig& config,
                     Callbacks cb = {})
      : io_(io), socket_(io), host_(host), port_(port), config_(config),
        callbacks_(std::move(cb)),
        client_state_(MAX_PREDICT_AHEAD_FRAMES + 4) {}

  // Connect to server (initial or reconnection)
  bool connect() {
    boost::system::error_code ec;
    tcp::resolver resolver(io_);
    auto endpoints = resolver.resolve(host_, std::to_string(port_), ec);
    if (ec) {
      std::println(stderr, "Resolve failed: {}", ec.message());
      return false;
    }

    socket_ = tcp::socket(io_);
    asio::connect(socket_, endpoints, ec);
    if (ec) {
      std::println(stderr, "Connect failed: {}", ec.message());
      return false;
    }

    recv_buf_.clear();
    if (!receive_session_start()) return false;
    if (!receive_slot_assignment()) return false;
    send_ready();
    do_read();

    state_ = ReconnectState::kConnected;
    consecutive_failures_ = 0;
    return true;
  }

  // Reset state for reconnection
  void reset_for_reconnect() {
    std::lock_guard<std::mutex> lock(mu_);
    if (socket_.is_open()) {
      boost::system::error_code ec;
      socket_.close(ec);
    }
    recv_buf_.clear();
    while (!auth_queue_.empty()) auth_queue_.pop();
    seed_ = 0;
    left_agents_ = 0;
    right_agents_ = 0;
    my_slots_.clear();
    my_slot_index_ = 0;
    // Keep prediction state for seamless resume
  }

  // Auto-reconnect with exponential backoff
  bool auto_reconnect(int max_attempts = 10) {
    reset_for_reconnect();
    state_ = ReconnectState::kReconnecting;

    for (int attempt = 1; attempt <= max_attempts; ++attempt) {
      if (callbacks_.on_reconnect_attempt) {
        callbacks_.on_reconnect_attempt(attempt);
      }

      std::println("Reconnect attempt {}/{}", attempt, max_attempts);

      if (connect()) {
        if (callbacks_.on_reconnect_success) {
          callbacks_.on_reconnect_success();
        }
        std::println("Reconnected successfully!");
        return true;
      }

      // Exponential backoff: 100ms, 200ms, 400ms, 800ms, ... max 5s
      int delay_ms = std::min(100 * (1 << (attempt - 1)), 5000);
      std::this_thread::sleep_for(std::chrono::milliseconds(delay_ms));
    }

    state_ = ReconnectState::kFailed;
    if (callbacks_.on_reconnect_failed) {
      callbacks_.on_reconnect_failed();
    }
    std::println(stderr, "Reconnection failed after {} attempts", max_attempts);
    return false;
  }

  // Check if connection is alive
  bool is_connected() const { return state_ == ReconnectState::kConnected; }
  bool is_disconnected() const { return state_ == ReconnectState::kDisconnected; }
  ReconnectState state() const { return state_; }

  // Accessors
  const std::vector<uint16_t>& my_slots() const { return my_slots_; }
  uint32_t seed() const { return seed_; }
  uint16_t left_agents() const { return left_agents_; }
  uint16_t right_agents() const { return right_agents_; }
  frame_id_t current_frame_id() const { return current_frame_id_; }
  frame_id_t last_confirmed_frame() const { return last_confirmed_frame_; }
  int frames_without_packet() const { return frames_without_packet_; }
  int rollback_count() const { return client_state_.rollback_count(); }

  // Send frame input
  void send_frame_input(frame_id_t frame_id, const uint16_t* slot_indices,
                        const SlotInput* inputs, uint16_t num_slots) {
    if (state_ != ReconnectState::kConnected) return;
    std::vector<uint8_t> buf(256);
    size_t n = PackClientFrameInput(frame_id, slot_indices, inputs,
                                     num_slots, buf.data(), buf.size());
    if (n == 0) return;
    boost::system::error_code ec;
    asio::write(socket_, asio::buffer(buf.data(), n), ec);
    if (ec) {
      state_ = ReconnectState::kDisconnected;
      if (callbacks_.on_disconnect) callbacks_.on_disconnect();
    }
  }

  // Pop authoritative frame
  bool pop_authoritative_frame(frame_id_t* frame_id,
                               std::vector<SlotInput>* inputs) {
    std::lock_guard<std::mutex> lock(mu_);
    if (auth_queue_.empty()) return false;
    *frame_id = auth_queue_.front().first;
    *inputs = auth_queue_.front().second;
    auth_queue_.pop();
    return true;
  }

  // Client state access
  ClientState& client_state() { return client_state_; }
  const ClientState& client_state() const { return client_state_; }

 private:
  bool receive_session_start() {
    uint8_t buf[32];
    size_t n = read_exact(buf, 1 + SESSION_START_PARAMS_BYTES);
    if (n == 0) return false;
    return UnpackSessionStart(buf, n, &seed_, &left_agents_, &right_agents_) != 0;
  }

  bool receive_slot_assignment() {
    uint8_t buf[64];
    size_t n = read_exact(buf, 1 + 2);
    if (n < 3) return false;
    if (buf[0] != std::to_underlying(MessageType::SlotAssignment))
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
    size_t n = PackReady(buf, sizeof(buf));
    asio::write(socket_, asio::buffer(buf, n));
  }

  void do_read() {
    auto buf = std::make_shared<std::vector<uint8_t>>(4096);
    socket_.async_read_some(
        asio::buffer(*buf),
        [this, buf](boost::system::error_code ec, std::size_t length) {
          if (ec) {
            state_ = ReconnectState::kDisconnected;
            if (callbacks_.on_disconnect) callbacks_.on_disconnect();
            return;
          }
          std::lock_guard<std::mutex> lock(mu_);
          recv_buf_.insert(recv_buf_.end(), buf->begin(), buf->begin() + length);
          while (parse_one_message()) {}
          do_read();
        });
  }

  bool parse_one_message() {
    if (recv_buf_.empty()) return false;
    uint8_t type = recv_buf_[0];

    if (type == std::to_underlying(MessageType::AuthoritativeFrame)) {
      if (recv_buf_.size() < 7u) return false;
      uint16_t num_slots;
      memcpy(&num_slots, recv_buf_.data() + 5, 2);
      size_t need = 7 + num_slots * SLOT_INPUT_BYTES;
      if (recv_buf_.size() < need) return false;
      frame_id_t fid;
      std::vector<SlotInput> inputs;
      size_t used = UnpackAuthoritativeFrame(
          recv_buf_.data(), recv_buf_.size(), &fid, &inputs);
      if (used == 0) return false;
      auth_queue_.emplace(fid, std::move(inputs));
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + used);
      return true;
    }

    if (type == std::to_underlying(MessageType::StateHash)) {
      if (recv_buf_.size() < STATE_HASH_PACK_BYTES) return false;
      frame_id_t fid;
      uint64_t hash;
      size_t used = UnpackStateHash(
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
  MultiplayerConfig config_;
  Callbacks callbacks_;
  std::mutex mu_;
  std::vector<uint8_t> recv_buf_;
  std::queue<std::pair<frame_id_t, std::vector<SlotInput>>> auth_queue_;
  std::vector<uint16_t> my_slots_;
  uint16_t my_slot_index_ = 0;
  uint32_t seed_ = 0;
  uint16_t left_agents_ = 0, right_agents_ = 0;

  // Prediction state
  frame_id_t current_frame_id_ = 0;
  frame_id_t last_confirmed_frame_ = 0;
  int frames_without_packet_ = 0;

  // Reconnection state
  ReconnectState state_ = ReconnectState::kDisconnected;
  int consecutive_failures_ = 0;

  // Client state ring buffer
  ClientState client_state_;
};

}  // namespace frame_sync

#endif
