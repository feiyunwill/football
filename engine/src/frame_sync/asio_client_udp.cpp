// Copyright 2019 Google LLC & Contributors
// Frame sync C++ client over reliable UDP (Boost.Asio). Connects, sends FrameInput, receives AuthoritativeFrame.

#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"
#include "frame_sync/reliable_udp.hpp"

// 2026-08-26 兼容修复（原因）：GCC 15 的 libstdc++ 不再向系统 Boost 1.75 的
// awaitable.hpp 传递提供 <utility>（std::exchange 未声明），须先于 asio 显式包含。
#include <utility>
#include <boost/asio.hpp>
#include <array>
#include <chrono>
#include <cstring>
#include <iostream>
#include <print>
#include <memory>
#include <mutex>
#include <queue>
#include <thread>
#include <vector>

namespace asio = boost::asio;
using udp = asio::ip::udp;

static const int kFrameRateHz = 10;

class FrameSyncClientUDP {
 public:
  FrameSyncClientUDP(asio::io_context& io, const std::string& host, unsigned short port)
      : io_(io), socket_(io), host_(host), port_(port) {}

  bool connect() {
    boost::system::error_code ec;
    udp::resolver resolver(io_);
    auto endpoints = resolver.resolve(udp::v4(), host_, std::to_string(port_), ec);
    if (ec || endpoints.empty()) {
      std::println(stderr, "Resolve failed: {}", ec ? ec.message() : "no endpoints");
      return false;
    }
    server_endpoint_ = *endpoints.begin();
    socket_.open(udp::v4(), ec);
    if (ec) { std::println(stderr, "Open failed: {}", ec.message()); return false; }
    socket_.bind(udp::endpoint(udp::v4(), 0), ec);
    if (ec) { std::println(stderr, "Bind failed: {}", ec.message()); return false; }

    // Send Connect so server creates our session
    uint8_t connect_byte = std::to_underlying(frame_sync::MessageType::Connect);
    socket_.send_to(asio::buffer(&connect_byte, 1), server_endpoint_, 0, ec);
    if (ec) { std::println(stderr, "Connect send failed: {}", ec.message()); return false; }

    do_receive();
    do_tick_retransmit();

    // Wait for SessionStart + SlotAssignment and send Ready (with timeout)
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // while (!ready_sent_ && std::chrono::steady_clock::now() < deadline) {
    while (running_ && !ready_sent_ && std::chrono::steady_clock::now() < deadline) {
      io_.run_one();
      std::lock_guard<std::mutex> lock(mu_);
      while (recv_buf_.size() >= 1u + frame_sync::SESSION_START_PARAMS_BYTES &&
             recv_buf_[0] == std::to_underlying(frame_sync::MessageType::SessionStart)) {
        frame_sync::UnpackSessionStart(recv_buf_.data(), recv_buf_.size(),
                                       &seed_, &left_agents_, &right_agents_);
        recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + static_cast<std::ptrdiff_t>(1 + frame_sync::SESSION_START_PARAMS_BYTES));
      }
      if (recv_buf_.size() >= 3u && recv_buf_[0] == std::to_underlying(frame_sync::MessageType::SlotAssignment)) {
        uint16_t num;
        memcpy(&num, recv_buf_.data() + 1, 2);
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // size_t need = 3 + num * 2;
        if (num == 0 || num > frame_sync::kMaxControlledSlots ||
            left_agents_ > 11 || right_agents_ > 11 || num > left_agents_ + right_agents_) {
          fail_transport_locked();
          return false;
        }
        size_t need = 3 + num * 2;
        if (recv_buf_.size() >= need) {
          my_slots_.resize(num);
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // for (uint16_t i = 0; i < num; ++i)
  // memcpy(&my_slots_[i], recv_buf_.data() + 3 + i * 2, 2);
          std::array<bool, frame_sync::kMaxControlledSlots> assigned{};
          for (uint16_t i = 0; i < num; ++i) {
            memcpy(&my_slots_[i], recv_buf_.data() + 3 + i * 2, 2);
            const auto slot = my_slots_[i];
            if (slot >= left_agents_ + right_agents_ || assigned[slot]) {
              fail_transport_locked();
              return false;
            }
            assigned[slot] = true;
          }
          recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + static_cast<std::ptrdiff_t>(need));
          send_ready();
  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // ready_sent_ = true;
          ready_sent_ = running_;
          break;
        }
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    if (!ready_sent_) {
      std::println(stderr, "Timeout waiting for SessionStart/SlotAssignment");
      return false;
    }
    return true;
  }

  void send_frame_input(frame_sync::frame_id_t frame_id,
                        const uint16_t* slot_indices,
                        const frame_sync::SlotInput* inputs,
                        uint16_t num_slots) {
    std::lock_guard<std::mutex> lock(mu_);
    if (!channel_) return;
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // std::vector<uint8_t> buf(256);
    std::array<uint8_t, 7 + frame_sync::kMaxControlledSlots * (2 + frame_sync::SLOT_INPUT_BYTES)> buf{};
    size_t n = frame_sync::PackClientFrameInput(
        frame_id, slot_indices, inputs, num_slots, buf.data(), buf.size());
  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // if (n) channel_->Send(buf.data(), n);
    if (!n || !channel_->Send(buf.data(), n)) fail_transport_locked();
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

  const std::vector<uint16_t>& my_slots() const { return my_slots_; }
  uint32_t seed() const { return seed_; }
  uint16_t left_agents() const { return left_agents_; }
  uint16_t right_agents() const { return right_agents_; }

  bool is_running() const { return running_.load(); }

 private:
  // The caller owns mu_. Cancellation callbacks are dispatched after returning.
  void fail_transport_locked() {
    if (!running_.exchange(false)) return;
    // 2026-09-09: expose the transport reason in bounded per-disconnect diagnostics.
    // fprintf(stderr, "UDP connection stopped: reliable delivery failed\n");
// 2026-09-09: distinguish application rejection from a ready transport.
//     fprintf(stderr, "UDP connection stopped: %s\n", channel_ ?
//         frame_sync::UDPChannelStatusName(channel_->status()) : "invalid session");
    const auto status = channel_ ? channel_->status() : frame_sync::UDPChannelStatus::Closed;
    fprintf(stderr, "UDP connection stopped: %s\n",
        status == frame_sync::UDPChannelStatus::Ready ? "invalid or overloaded stream" :
        frame_sync::UDPChannelStatusName(status));
    if (channel_) channel_->Close();
    boost::system::error_code ignored;
    // 2026-09-09: installed Boost exposes only the no-argument timer overload.
    // retransmit_timer_.cancel(ignored);
    retransmit_timer_.cancel();
    socket_.cancel(ignored);
    std::vector<uint8_t>().swap(recv_buf_);
    decltype(auth_queue_)().swap(auth_queue_);
  }
  void do_receive() {
    if (!running_) return;
    auto buf = std::make_shared<std::vector<uint8_t>>(4096);
    auto sender = std::make_shared<udp::endpoint>();
    socket_.async_receive_from(
        asio::buffer(*buf), *sender,
        [this, buf, sender](boost::system::error_code ec, std::size_t length) {
          if (ec) { do_receive(); return; }
  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // std::lock_guard<std::mutex> lock(mu_);
  // if (!channel_) {
          std::lock_guard<std::mutex> lock(mu_);
          if (*sender != server_endpoint_) { do_receive(); return; }
          if (!channel_) {
            channel_ = std::make_unique<frame_sync::ReliableUDPChannel>(
                socket_, *sender,
                [this](const uint8_t* d, size_t n) {
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // recv_buf_.insert(recv_buf_.end(), d, d + n);
                  if (!frame_sync::AppendBoundedBytes(recv_buf_, d, n, 4096)) {
                    fail_transport_locked();
                    return;
                  }
                  while (parse_one_message()) {}
                });
          }
  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // if (channel_) channel_->HandleReceived(buf->data(), length);
          if (channel_ && !channel_->HandleReceived(buf->data(), length))
            fail_transport_locked();
          do_receive();
        });
  }

  void do_tick_retransmit() {
    retransmit_timer_.expires_after(std::chrono::milliseconds(20));
    retransmit_timer_.async_wait([this](boost::system::error_code ec) {
      if (ec || !running_) return;
      std::lock_guard<std::mutex> lock(mu_);
  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // if (channel_) channel_->TickRetransmit();
      if (channel_ && !channel_->TickRetransmit()) {
        fail_transport_locked();
        return;
      }
      do_tick_retransmit();
    });
  }

  bool parse_one_message() {
    if (recv_buf_.empty()) return false;
    uint8_t type = recv_buf_[0];
    // 2026-09-09: consume complete control messages; payload bytes are not types.
    if (type == std::to_underlying(frame_sync::MessageType::Heartbeat)) {
      if (recv_buf_.size() < frame_sync::HEARTBEAT_PACKET_BYTES) return false;
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + frame_sync::HEARTBEAT_PACKET_BYTES);
      return true;
    }
    if (type == std::to_underlying(frame_sync::MessageType::StateHash)) {
      if (recv_buf_.size() < frame_sync::STATE_HASH_PACK_BYTES) return false;
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + frame_sync::STATE_HASH_PACK_BYTES);
      return true;
    }

    if (type == std::to_underlying(frame_sync::MessageType::AuthoritativeFrame)) {
      if (recv_buf_.size() < 7u) return false;
      uint16_t num_slots;
      memcpy(&num_slots, recv_buf_.data() + 5, 2);
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // size_t need = 7 + num_slots * frame_sync::SLOT_INPUT_BYTES;
      if (num_slots == 0 || num_slots != left_agents_ + right_agents_ ||
          num_slots > frame_sync::kMaxControlledSlots) {
        fail_transport_locked();
        return false;
      }
      size_t need = 7 + num_slots * frame_sync::SLOT_INPUT_BYTES;
      if (recv_buf_.size() < need) return false;
      frame_sync::frame_id_t fid;
      std::vector<frame_sync::SlotInput> inputs;
      size_t used = frame_sync::UnpackAuthoritativeFrame(
          recv_buf_.data(), recv_buf_.size(), &fid, &inputs);
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // if (used == 0) return false;
      if (used == 0) { fail_transport_locked(); return false; }
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // auth_queue_.emplace(fid, std::move(inputs));
      if (auth_queue_.size() >= frame_sync::kMaxBufferedAuthorityFrames ||
          !std::all_of(inputs.begin(), inputs.end(), frame_sync::IsValidSlotInput)) {
        fail_transport_locked();
        return false;
      }
      auth_queue_.emplace(fid, std::move(inputs));
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + used);
      return true;
    }
    return false;
  }

  void send_ready() {
    if (!channel_) return;
    uint8_t buf[4];
    size_t n = frame_sync::PackReady(buf, sizeof(buf));
  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // channel_->Send(buf, n);
    if (!n || !channel_->Send(buf, n)) fail_transport_locked();
  }

  asio::io_context& io_;
  udp::socket socket_;
  asio::steady_timer retransmit_timer_{io_};
  udp::endpoint server_endpoint_;
  std::string host_;
  unsigned short port_;
  std::mutex mu_;
  std::unique_ptr<frame_sync::ReliableUDPChannel> channel_;
  std::vector<uint8_t> recv_buf_;
  std::queue<std::pair<frame_sync::frame_id_t, std::vector<frame_sync::SlotInput>>> auth_queue_;
  std::vector<uint16_t> my_slots_;
  uint32_t seed_ = 0;
  uint16_t left_agents_ = 0, right_agents_ = 0;
  bool ready_sent_ = false;
  std::atomic<bool> running_{true};
};

int main(int argc, char* argv[]) {
  if (argc < 3) {
    std::println(stderr, "Usage: {} <host> <port> [slot_index]", argv[0]);
    return 1;
  }
  std::string host = argv[1];
  unsigned short port = static_cast<unsigned short>(std::stoi(argv[2]));
  uint16_t my_slot = (argc >= 4) ? static_cast<uint16_t>(std::stoi(argv[3])) : 0;

  asio::io_context io;
  FrameSyncClientUDP client(io, host, port);
  if (!client.connect()) return 1;
  std::println("Connected (UDP). My slots: {} seed={}", client.my_slots().size(), client.seed());

  std::thread io_thread([&io]() { io.run(); });

  frame_sync::frame_id_t next_send_frame = 0;
  std::vector<frame_sync::SlotInput> my_inputs(1, frame_sync::SlotInput::Default());
  auto period = std::chrono::milliseconds(1000 / kFrameRateHz);

  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // while (true) {
  while (client.is_running()) {
    auto t0 = std::chrono::steady_clock::now();
    client.send_frame_input(next_send_frame, &my_slot, my_inputs.data(), 1);
    ++next_send_frame;

    frame_sync::frame_id_t auth_fid;
    std::vector<frame_sync::SlotInput> auth_inputs;
    while (client.pop_authoritative_frame(&auth_fid, &auth_inputs)) {
      (void)auth_fid;
      (void)auth_inputs;
    }

    auto elapsed = std::chrono::steady_clock::now() - t0;
    if (elapsed < period)
      std::this_thread::sleep_for(period - elapsed);
  }
  io.stop();
  if (io_thread.joinable()) io_thread.join();
  // 2026-09-09: distinguish lost transport from a normal user exit.
  // return 0;
  return client.is_running() ? 0 : 1;
}
