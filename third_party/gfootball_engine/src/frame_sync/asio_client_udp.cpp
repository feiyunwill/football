// Copyright 2019 Google LLC & Contributors
// Frame sync C++ client over reliable UDP (Boost.Asio). Connects, sends FrameInput, receives AuthoritativeFrame.

#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"
#include "frame_sync/reliable_udp.hpp"

#include <boost/asio.hpp>
#include <chrono>
#include <cstring>
#include <iostream>
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
      std::cerr << "Resolve failed: " << (ec ? ec.message() : "no endpoints") << std::endl;
      return false;
    }
    server_endpoint_ = *endpoints.begin();
    socket_.open(udp::v4(), ec);
    if (ec) { std::cerr << "Open failed: " << ec.message() << std::endl; return false; }
    socket_.bind(udp::endpoint(udp::v4(), 0), ec);
    if (ec) { std::cerr << "Bind failed: " << ec.message() << std::endl; return false; }

    // Send Connect so server creates our session
    uint8_t connect_byte = static_cast<uint8_t>(frame_sync::MessageType::Connect);
    socket_.send_to(asio::buffer(&connect_byte, 1), server_endpoint_, 0, ec);
    if (ec) { std::cerr << "Connect send failed: " << ec.message() << std::endl; return false; }

    do_receive();
    do_tick_retransmit();

    // Wait for SessionStart + SlotAssignment and send Ready (with timeout)
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (!ready_sent_ && std::chrono::steady_clock::now() < deadline) {
      io_.run_one();
      std::lock_guard<std::mutex> lock(mu_);
      while (recv_buf_.size() >= 1u + frame_sync::SESSION_START_PARAMS_BYTES &&
             recv_buf_[0] == static_cast<uint8_t>(frame_sync::MessageType::SessionStart)) {
        frame_sync::UnpackSessionStart(recv_buf_.data(), recv_buf_.size(),
                                       &seed_, &left_agents_, &right_agents_);
        recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + static_cast<std::ptrdiff_t>(1 + frame_sync::SESSION_START_PARAMS_BYTES));
      }
      if (recv_buf_.size() >= 3u && recv_buf_[0] == static_cast<uint8_t>(frame_sync::MessageType::SlotAssignment)) {
        uint16_t num;
        memcpy(&num, recv_buf_.data() + 1, 2);
        size_t need = 3 + num * 2;
        if (recv_buf_.size() >= need) {
          my_slots_.resize(num);
          for (uint16_t i = 0; i < num; ++i)
            memcpy(&my_slots_[i], recv_buf_.data() + 3 + i * 2, 2);
          recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + static_cast<std::ptrdiff_t>(need));
          send_ready();
          ready_sent_ = true;
          break;
        }
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    if (!ready_sent_) {
      std::cerr << "Timeout waiting for SessionStart/SlotAssignment\n";
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
    std::vector<uint8_t> buf(256);
    size_t n = frame_sync::PackClientFrameInput(
        frame_id, slot_indices, inputs, num_slots, buf.data(), buf.size());
    if (n) channel_->Send(buf.data(), n);
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

 private:
  void do_receive() {
    if (!running_) return;
    auto buf = std::make_shared<std::vector<uint8_t>>(4096);
    auto sender = std::make_shared<udp::endpoint>();
    socket_.async_receive_from(
        asio::buffer(*buf), *sender,
        [this, buf, sender](boost::system::error_code ec, std::size_t length) {
          if (ec) { do_receive(); return; }
          std::lock_guard<std::mutex> lock(mu_);
          if (!channel_) {
            channel_ = std::make_unique<frame_sync::ReliableUDPChannel>(
                socket_, *sender,
                [this](const uint8_t* d, size_t n) {
                  recv_buf_.insert(recv_buf_.end(), d, d + n);
                  while (parse_one_message()) {}
                });
          }
          if (channel_) channel_->HandleReceived(buf->data(), length);
          do_receive();
        });
  }

  void do_tick_retransmit() {
    retransmit_timer_.expires_after(std::chrono::milliseconds(20));
    retransmit_timer_.async_wait([this](boost::system::error_code ec) {
      if (ec || !running_) return;
      std::lock_guard<std::mutex> lock(mu_);
      if (channel_) channel_->TickRetransmit();
      do_tick_retransmit();
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
    return false;
  }

  void send_ready() {
    if (!channel_) return;
    uint8_t buf[4];
    size_t n = frame_sync::PackReady(buf, sizeof(buf));
    channel_->Send(buf, n);
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
    std::cerr << "Usage: " << argv[0] << " <host> <port> [slot_index]\n";
    return 1;
  }
  std::string host = argv[1];
  unsigned short port = static_cast<unsigned short>(std::stoi(argv[2]));
  uint16_t my_slot = (argc >= 4) ? static_cast<uint16_t>(std::stoi(argv[3])) : 0;

  asio::io_context io;
  FrameSyncClientUDP client(io, host, port);
  if (!client.connect()) return 1;
  std::cout << "Connected (UDP). My slots: " << client.my_slots().size()
            << " seed=" << client.seed() << std::endl;

  std::thread io_thread([&io]() { io.run(); });

  frame_sync::frame_id_t next_send_frame = 0;
  std::vector<frame_sync::SlotInput> my_inputs(1, frame_sync::SlotInput::Default());
  auto period = std::chrono::milliseconds(1000 / kFrameRateHz);

  while (true) {
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
  return 0;
}
