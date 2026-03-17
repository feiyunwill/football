// Copyright 2019 Google LLC & Contributors
// Frame sync C++ server using Boost.Asio. Collects FrameInput, broadcasts AuthoritativeFrame.
// No engine dependency: authority is "same merged input" for deterministic clients.

#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"

#include <boost/asio.hpp>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <memory>
#include <mutex>
#include <set>
#include <thread>
#include <vector>

namespace asio = boost::asio;
using tcp = asio::ip::tcp;

static const unsigned short kDefaultPort = 12345;
static const int kFrameTimeoutMs = 200;
static const int kFrameRateHz = 10;

struct ClientSession {
  tcp::socket socket;
  std::vector<uint16_t> assigned_slots;
  bool ready = false;
  std::vector<uint8_t> recv_buf;
  bool disconnected = false;

  explicit ClientSession(asio::io_context& io) : socket(io) {}
};

class FrameSyncServer {
 public:
  FrameSyncServer(asio::io_context& io, unsigned short port,
                  uint16_t left_agents, uint16_t right_agents, uint32_t seed)
      : io_(io),
        acceptor_(io, tcp::endpoint(tcp::v4(), port)),
        left_agents_(left_agents),
        right_agents_(right_agents),
        num_slots_(left_agents + right_agents),
        seed_(seed),
        frame_id_(0) {
    for (size_t i = 0; i < num_slots_; ++i)
      current_inputs_.push_back(frame_sync::SlotInput::Default());
    do_accept();
  }

  bool all_ready() const {
    std::lock_guard<std::mutex> lock(mu_);
    int connected = 0;
    for (const auto& c : clients_) {
      if (!c->disconnected) ++connected;
    }
    if (connected == 0) return false;
    int ready = 0;
    for (const auto& c : clients_) {
      if (!c->disconnected && c->ready) ++ready;
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
        for (const auto& c : clients_) {
          if (!c->disconnected) ++connected;
        }
        if (connected == 0) break;
        if (static_cast<int>(received_from_.size()) >= connected) break;
      }
      broadcast_authoritative_frame();
      ++frame_id_;
      std::this_thread::sleep_for(
          std::chrono::milliseconds(1000 / kFrameRateHz));
    }
  }

  void stop() { running_ = false; }

 private:
  void do_accept() {
    acceptor_.async_accept([this](boost::system::error_code ec, tcp::socket socket) {
      if (ec) return;
      std::lock_guard<std::mutex> lock(mu_);
      auto client = std::make_shared<ClientSession>(io_);
      client->socket = std::move(socket);
      std::set<uint16_t> used;
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
        return;
      }
      clients_.push_back(client);
      send_session_start(client);
      send_slot_assignment(client);
      do_read(client);
      do_accept();
    });
  }

  void send_session_start(std::shared_ptr<ClientSession> client) {
    uint8_t buf[32];
    size_t n = frame_sync::PackSessionStart(seed_, left_agents_, right_agents_, buf, sizeof(buf));
    asio::write(client->socket, asio::buffer(buf, n));
  }

  void send_slot_assignment(std::shared_ptr<ClientSession> client) {
    uint8_t buf[64];
    size_t n = frame_sync::PackSlotAssignment(
        client->assigned_slots.data(), static_cast<uint16_t>(client->assigned_slots.size()),
        buf, sizeof(buf));
    asio::write(client->socket, asio::buffer(buf, n));
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

  void do_read(std::shared_ptr<ClientSession> client) {
    auto buf = std::make_shared<std::vector<uint8_t>>(4096);
    client->socket.async_read_some(
        asio::buffer(*buf),
        [this, client, buf](boost::system::error_code ec, std::size_t length) {
          if (ec) {
            client->disconnected = true;
            return;
          }
          std::lock_guard<std::mutex> lock(mu_);
          client->recv_buf.insert(client->recv_buf.end(), buf->begin(), buf->begin() + length);
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
  tcp::acceptor acceptor_;
  mutable std::mutex mu_;
  std::vector<std::shared_ptr<ClientSession>> clients_;
  uint16_t left_agents_;
  uint16_t right_agents_;
  size_t num_slots_;
  uint32_t seed_;
  frame_sync::frame_id_t frame_id_;
  std::vector<frame_sync::SlotInput> current_inputs_;
  std::set<ClientSession*> received_from_;
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
  FrameSyncServer server(io, port, left, right, seed);
  std::thread io_thread([&io]() { io.run(); });
  std::cout << "Frame sync server listening on port " << port << std::endl;
  server.run_frame_loop();
  server.stop();
  io.stop();
  if (io_thread.joinable()) io_thread.join();
  return 0;
}
