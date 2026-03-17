// Copyright 2019 Google LLC & Contributors
// Frame sync C++ server using Boost.Asio + reliable UDP. Same protocol as TCP version.

#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"
#include "frame_sync/reliable_udp.hpp"

#include <boost/asio.hpp>
#include <chrono>
#include <cstring>
#include <iostream>
#include <memory>
#include <mutex>
#include <set>
#include <thread>
#include <vector>

namespace asio = boost::asio;
using udp = asio::ip::udp;

static const unsigned short kDefaultPort = 12346;
static const int kFrameTimeoutMs = 200;
static const int kFrameRateHz = 10;

struct ClientSessionUDP {
  udp::endpoint endpoint;
  std::unique_ptr<frame_sync::ReliableUDPChannel> channel;
  std::vector<uint16_t> assigned_slots;
  bool ready = false;
  std::vector<uint8_t> recv_buf;
  bool disconnected = false;
};

class FrameSyncServerUDP {
 public:
  FrameSyncServerUDP(asio::io_context& io, unsigned short port,
                     uint16_t left_agents, uint16_t right_agents, uint32_t seed)
      : io_(io),
        socket_(io, udp::endpoint(udp::v4(), port)),
        left_agents_(left_agents),
        right_agents_(right_agents),
        num_slots_(left_agents + right_agents),
        seed_(seed),
        frame_id_(0),
        retransmit_timer_(io) {
    for (size_t i = 0; i < num_slots_; ++i)
      current_inputs_.push_back(frame_sync::SlotInput::Default());
    do_receive();
    do_retransmit_timer();
  }

  bool all_ready() const {
    std::lock_guard<std::mutex> lock(mu_);
    int connected = 0;
    for (const auto& p : clients_) {
      if (!p.second->disconnected) ++connected;
    }
    if (connected == 0) return false;
    int ready = 0;
    for (const auto& p : clients_) {
      if (!p.second->disconnected && p.second->ready) ++ready;
    }
    return ready == connected;
  }

  void run_frame_loop() {
    while (running_ && !all_ready()) {
      std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    while (running_) {
      auto deadline = std::chrono::steady_clock::now() +
          std::chrono::milliseconds(kFrameTimeoutMs);
      {
        std::lock_guard<std::mutex> lock(mu_);
        received_from_.clear();
        for (size_t i = 0; i < num_slots_; ++i)
          current_inputs_[i] = frame_sync::SlotInput::Default();
      }
      while (std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
        std::lock_guard<std::mutex> lock(mu_);
        int connected = 0;
        for (const auto& p : clients_)
          if (!p.second->disconnected) ++connected;
        if (connected == 0) break;
        if (static_cast<int>(received_from_.size()) >= connected) break;
      }
      // When engine is integrated: call StepWithInput(current_inputs_) here (same as Python server).
      broadcast_authoritative_frame();
      if (frame_id_ % frame_sync::STATE_HASH_INTERVAL_K == 0)
        broadcast_state_hash(frame_id_, 0);  // 0 = no engine; when integrated use get_state hash
      ++frame_id_;
      std::this_thread::sleep_for(
          std::chrono::milliseconds(1000 / kFrameRateHz));
    }
  }

  void stop() { running_ = false; }

 private:
  void do_receive() {
    if (!running_) return;
    auto buf = std::make_shared<std::vector<uint8_t>>(4096);
    auto sender = std::make_shared<udp::endpoint>();
    socket_.async_receive_from(
        asio::buffer(*buf), *sender,
        [this, buf, sender](boost::system::error_code ec, std::size_t length) {
          if (ec) { do_receive(); return; }
          std::shared_ptr<ClientSessionUDP> client = get_or_create_client(*sender);
          if (client && client->channel)
            client->channel->HandleReceived(buf->data(), length);
          do_receive();
        });
  }

  void do_retransmit_timer() {
    retransmit_timer_.expires_after(std::chrono::milliseconds(20));
    retransmit_timer_.async_wait([this](boost::system::error_code ec) {
      if (ec || !running_) return;
      std::lock_guard<std::mutex> lock(mu_);
      for (auto& p : clients_)
        if (p.second->channel)
          p.second->channel->TickRetransmit();
      do_retransmit_timer();
    });
  }

  std::shared_ptr<ClientSessionUDP> get_or_create_client(const udp::endpoint& sender) {
    std::lock_guard<std::mutex> lock(mu_);
    auto it = clients_.find(sender);
    if (it != clients_.end()) return it->second;
    auto client = std::make_shared<ClientSessionUDP>();
    client->endpoint = sender;
    std::set<uint16_t> used;
    for (const auto& p : clients_) {
      for (uint16_t s : p.second->assigned_slots) used.insert(s);
    }
    for (uint16_t s = 0; s < num_slots_; ++s) {
      if (used.find(s) == used.end()) {
        client->assigned_slots.push_back(s);
        break;
      }
    }
    if (client->assigned_slots.empty()) return nullptr;
    std::weak_ptr<ClientSessionUDP> w = client;
    client->channel = std::make_unique<frame_sync::ReliableUDPChannel>(
        socket_, sender,
        [this, w](const uint8_t* d, size_t n) {
          auto c = w.lock();
          if (!c) return;
          std::lock_guard<std::mutex> lock(mu_);
          c->recv_buf.insert(c->recv_buf.end(), d, d + n);
          while (process_one_message(c)) {}
        });
    clients_[sender] = client;
    send_session_start(client.get());
    send_slot_assignment(client.get());
    return client;
  }

  void send_session_start(ClientSessionUDP* client) {
    uint8_t buf[32];
    size_t n = frame_sync::PackSessionStart(seed_, left_agents_, right_agents_, buf, sizeof(buf));
    client->channel->Send(buf, n);
  }

  void send_slot_assignment(ClientSessionUDP* client) {
    uint8_t buf[64];
    size_t n = frame_sync::PackSlotAssignment(
        client->assigned_slots.data(), static_cast<uint16_t>(client->assigned_slots.size()),
        buf, sizeof(buf));
    client->channel->Send(buf, n);
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
    for (auto& p : clients_) {
      if (p.second->disconnected || !p.second->channel) continue;
      p.second->channel->Send(buf.data(), n);
    }
  }

  void broadcast_state_hash(frame_sync::frame_id_t fid, frame_sync::state_hash_t hash) {
    uint8_t buf[frame_sync::STATE_HASH_PACK_BYTES];
    size_t n = frame_sync::PackStateHash(fid, hash, buf, sizeof(buf));
    std::lock_guard<std::mutex> lock(mu_);
    for (auto& p : clients_) {
      if (p.second->disconnected || !p.second->channel) continue;
      p.second->channel->Send(buf, n);
    }
  }

  bool process_one_message(std::shared_ptr<ClientSessionUDP> client) {
    if (client->recv_buf.empty()) return false;
    uint8_t type = client->recv_buf[0];
    if (type == static_cast<uint8_t>(frame_sync::MessageType::Ready)) {
      client->ready = true;
      client->recv_buf.erase(client->recv_buf.begin());
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
      client->recv_buf.erase(client->recv_buf.begin(), client->recv_buf.begin() + used);
      return true;
    }
    return false;
  }

  asio::io_context& io_;
  udp::socket socket_;
  asio::steady_timer retransmit_timer_;
  mutable std::mutex mu_;
  std::map<udp::endpoint, std::shared_ptr<ClientSessionUDP>> clients_;
  uint16_t left_agents_;
  uint16_t right_agents_;
  size_t num_slots_;
  uint32_t seed_;
  frame_sync::frame_id_t frame_id_;
  std::vector<frame_sync::SlotInput> current_inputs_;
  std::set<ClientSessionUDP*> received_from_;
  std::atomic<bool> running_{true};
};

int main(int argc, char* argv[]) {
  unsigned short port = kDefaultPort;
  uint16_t left = 1, right = 1;
  uint32_t seed = 42;
  if (argc >= 2) port = static_cast<unsigned short>(std::stoi(argv[1]));
  if (argc >= 4) {
    left = static_cast<uint16_t>(std::stoi(argv[2]));
    right = static_cast<uint16_t>(std::stoi(argv[3]));
  }
  if (argc >= 5) seed = static_cast<uint32_t>(std::stoul(argv[4]));

  asio::io_context io;
  FrameSyncServerUDP server(io, port, left, right, seed);
  std::thread io_thread([&io]() { io.run(); });
  std::cout << "Frame sync server (reliable UDP) on port " << port << std::endl;
  server.run_frame_loop();
  server.stop();
  io.stop();
  if (io_thread.joinable()) io_thread.join();
  return 0;
}
