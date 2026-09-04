// Copyright 2026 Google LLC & Contributors
// Spectator client for frame sync (ms-17.3).
// Read-only client that receives authoritative frames without sending inputs.
//
// Usage:
//   SpectatorClient spec(io, "127.0.0.1", 12345);
//   spec.connect();
//   // In frame loop:
//   spec.poll();
//   auto frames = spec.get_frames();

#ifndef GFOOTBALL_FRAME_SYNC_SPECTATOR_HPP
#define GFOOTBALL_FRAME_SYNC_SPECTATOR_HPP

#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"

#include <boost/asio.hpp>
#include <deque>
#include <functional>
#include <string>
#include <vector>

namespace frame_sync {

/// @brief Lightweight spectator client — receives authoritative frames, sends nothing
class SpectatorClient {
 public:
  using FrameCallback = std::function<void(frame_id_t, const std::vector<SlotInput>&)>;

  struct ReceivedFrame {
    frame_id_t frame_id;
    std::vector<SlotInput> inputs;
  };

  SpectatorClient(boost::asio::io_context& io,
                  const std::string& host, unsigned short port)
      : io_(io),
        socket_(io),
        resolver_(io),
        host_(host),
        port_(port) {}

  /// @brief Connect to server and send SpectatorJoin
  void connect() {
    auto endpoints = resolver_.resolve(host_, std::to_string(port_));
    boost::asio::connect(socket_, endpoints);
    connected_ = true;

    // Send SpectatorJoin message (just the type byte, no payload needed)
    uint8_t msg = static_cast<uint8_t>(MessageType::SpectatorJoin);
    boost::system::error_code ec;
    boost::asio::write(socket_, boost::asio::buffer(&msg, 1), ec);
    if (ec) {
      connected_ = false;
      return;
    }

    do_read();
  }

  /// @brief Non-blocking poll for incoming data
  void poll() {
    if (!connected_) return;
    boost::system::error_code ec;
    while (socket_.available(ec) > 0 && !ec) {
      std::vector<uint8_t> buf(4096);
      size_t n = socket_.read_some(boost::asio::buffer(buf), ec);
      if (ec || n == 0) {
        connected_ = false;
        return;
      }
      recv_buf_.insert(recv_buf_.end(), buf.begin(), buf.begin() + n);
      while (process_one_message()) {}
    }
    if (ec && ec != boost::asio::error::would_block) {
      connected_ = false;
    }
  }

  /// @brief Blocking read (runs until disconnect or stop)
  void run() {
    while (connected_) {
      poll();
      std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
  }

  /// @brief Check if connected
  [[nodiscard]] bool is_connected() const { return connected_; }

  /// @brief Get received authoritative frames
  [[nodiscard]] const std::vector<ReceivedFrame>& get_frames() const { return frames_; }

  /// @brief Pop processed frames (clears the buffer)
  void pop_frames() { frames_.clear(); }

  /// @brief Get latest frame ID received
  [[nodiscard]] frame_id_t last_frame_id() const { return last_frame_id_; }

  /// @brief Set callback for incoming authoritative frames
  void on_frame(FrameCallback cb) { frame_cb_ = std::move(cb); }

  /// @brief Statistics
  [[nodiscard]] uint64_t frames_received() const { return frames_received_; }
  [[nodiscard]] uint64_t state_hashes_received() const { return state_hashes_received_; }

  void disconnect() {
    connected_ = false;
    boost::system::error_code ec;
    socket_.close(ec);
  }

 private:
  void do_read() {
    auto buf = std::make_shared<std::vector<uint8_t>>(4096);
    socket_.async_read_some(
        boost::asio::buffer(*buf),
        [this, buf](boost::system::error_code ec, std::size_t length) {
          if (ec) {
            connected_ = false;
            return;
          }
          recv_buf_.insert(recv_buf_.end(), buf->begin(), buf->begin() + length);
          while (process_one_message()) {}
          if (connected_) do_read();
        });
  }

  bool process_one_message() {
    if (recv_buf_.empty()) return false;
    uint8_t type = recv_buf_[0];

    if (type == static_cast<uint8_t>(MessageType::AuthoritativeFrame)) {
      if (recv_buf_.size() < AUTHORITATIVE_FRAME_HEADER_BYTES) return false;
      frame_id_t fid;
      uint16_t num_slots;
      // Parse header: type(1) + frame_id(4) + num_slots(2)
      std::memcpy(&fid, recv_buf_.data() + 1, sizeof(frame_id_t));
      std::memcpy(&num_slots, recv_buf_.data() + 5, sizeof(uint16_t));
      size_t need = AUTHORITATIVE_FRAME_HEADER_BYTES + num_slots * SLOT_INPUT_BYTES;
      if (recv_buf_.size() < need) return false;

      std::vector<SlotInput> inputs(num_slots);
      for (uint16_t i = 0; i < num_slots; ++i) {
        std::memcpy(&inputs[i],
                     recv_buf_.data() + AUTHORITATIVE_FRAME_HEADER_BYTES + i * SLOT_INPUT_BYTES,
                     SLOT_INPUT_BYTES);
      }

      frames_.push_back({fid, std::move(inputs)});
      last_frame_id_ = fid;
      ++frames_received_;

      if (frame_cb_) frame_cb_(fid, frames_.back().inputs);

      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + need);
      return true;
    }

    if (type == static_cast<uint8_t>(MessageType::StateHash)) {
      if (recv_buf_.size() < STATE_HASH_PACK_BYTES) return false;
      ++state_hashes_received_;
      recv_buf_.erase(recv_buf_.begin(),
                      recv_buf_.begin() + STATE_HASH_PACK_BYTES);
      return true;
    }

    if (type == static_cast<uint8_t>(MessageType::SessionStart)) {
      if (recv_buf_.size() < 1 + SESSION_START_PARAMS_BYTES) return false;
      session_start_received_ = true;
      recv_buf_.erase(recv_buf_.begin(),
                      recv_buf_.begin() + 1 + SESSION_START_PARAMS_BYTES);
      return true;
    }

    if (type == static_cast<uint8_t>(MessageType::SlotAssignment)) {
      // Spectators get no slots; skip this message
      if (recv_buf_.size() < 3) return false;
      uint16_t count;
      std::memcpy(&count, recv_buf_.data() + 1, sizeof(uint16_t));
      size_t need = 1 + sizeof(uint16_t) + count * sizeof(uint16_t);
      if (recv_buf_.size() < need) return false;
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + need);
      return true;
    }

    if (type == static_cast<uint8_t>(MessageType::Heartbeat)) {
      if (recv_buf_.size() < HEARTBEAT_PACKET_BYTES) return false;
      recv_buf_.erase(recv_buf_.begin(),
                      recv_buf_.begin() + HEARTBEAT_PACKET_BYTES);
      return true;
    }

    // Unknown message: skip 1 byte
    recv_buf_.erase(recv_buf_.begin());
    return true;
  }

  boost::asio::io_context& io_;
  boost::asio::ip::tcp::socket socket_;
  boost::asio::ip::tcp::resolver resolver_;
  std::string host_;
  unsigned short port_;
  bool connected_ = false;
  bool session_start_received_ = false;
  std::vector<uint8_t> recv_buf_;

  frame_id_t last_frame_id_ = 0;
  std::vector<ReceivedFrame> frames_;
  FrameCallback frame_cb_;

  uint64_t frames_received_ = 0;
  uint64_t state_hashes_received_ = 0;
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_SPECTATOR_HPP
