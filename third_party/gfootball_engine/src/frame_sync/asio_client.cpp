// Copyright 2019 Google LLC & Contributors
// Frame sync C++ client using Boost.Asio. Connects, sends FrameInput, receives AuthoritativeFrame.

#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"

#include <boost/asio.hpp>
#include <chrono>
#include <cstring>
#include <deque>
#include <iostream>
#include <memory>
#include <mutex>
#include <queue>
#include <string>
#include <thread>
#include <vector>

namespace asio = boost::asio;
using tcp = asio::ip::tcp;

static const int kFrameRateHz = 10;

class FrameSyncClient {
 public:
  FrameSyncClient(asio::io_context& io, const std::string& host, unsigned short port)
      : io_(io), socket_(io), host_(host), port_(port) {}

  bool connect() {
    boost::system::error_code ec;
    tcp::resolver resolver(io_);
    auto endpoints = resolver.resolve(host_, std::to_string(port_), ec);
    if (ec) {
      std::cerr << "Resolve failed: " << ec.message() << std::endl;
      return false;
    }
    asio::connect(socket_, endpoints, ec);
    if (ec) {
      std::cerr << "Connect failed: " << ec.message() << std::endl;
      return false;
    }
    recv_buf_.clear();
    if (!receive_session_start()) return false;
    if (!receive_slot_assignment()) return false;
    send_ready();
    do_read();
    return true;
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

  const std::vector<uint16_t>& my_slots() const { return my_slots_; }
  uint32_t seed() const { return seed_; }
  uint16_t left_agents() const { return left_agents_; }
  uint16_t right_agents() const { return right_agents_; }

 private:
  bool receive_session_start() {
    uint8_t buf[32];
    size_t n = read_exact(buf, 1 + frame_sync::SESSION_START_PARAMS_BYTES);
    if (n == 0) return false;
    return frame_sync::UnpackSessionStart(buf, n, &seed_, &left_agents_, &right_agents_) != 0;
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
    return false;
  }

  asio::io_context& io_;
  tcp::socket socket_;
  std::string host_;
  unsigned short port_;
  std::mutex mu_;
  std::vector<uint8_t> recv_buf_;
  std::queue<std::pair<frame_sync::frame_id_t, std::vector<frame_sync::SlotInput>>> auth_queue_;
  std::vector<uint16_t> my_slots_;
  uint32_t seed_ = 0;
  uint16_t left_agents_ = 0, right_agents_ = 0;
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
  FrameSyncClient client(io, host, port);
  if (!client.connect()) return 1;
  std::cout << "Connected. My slots: " << client.my_slots().size()
            << " seed=" << client.seed() << std::endl;

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
      // Application would apply auth_inputs and step local engine here.
    }

    auto elapsed = std::chrono::steady_clock::now() - t0;
    if (elapsed < period)
      std::this_thread::sleep_for(period - elapsed);
  }
  return 0;
}
