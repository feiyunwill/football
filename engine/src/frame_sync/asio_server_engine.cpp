// Copyright 2026 Google LLC & Contributors
// Frame sync C++ server with real engine integration (headless GameEnv).
// Mirrors gfootball/frame_sync/server.py: collects FrameInputs, runs
// StepWithInput, broadcasts AuthoritativeFrame + StateHash.
//
// Build: cmake --build build_rl -j 1 --target frame_sync_server_engine
//   (or from engine root: cmake --build . -j 1 --target frame_sync_server_engine)
// Run:   GFOOTBALL_DATA_DIR=../data xvfb-run -a ./frame_sync_server_engine [port] [left] [right] [seed]
//
// This target links against the full engine (render=false, MockRenderer3D),
// so it requires SDL2/OpenGL/EGL headers at build time but runs headless.

#include "protocol.hpp"
#include "protocol_io.hpp"
#include "reliable_udp.hpp"
#include "input_codec.hpp"

// Engine headers
#include "../game_env.hpp"
#include "../gamedefines.hpp"
#include "../main.hpp"

// 2026-08-26 兼容修复（原因）：GCC 15 的 libstdc++ 不再向系统 Boost 1.75 的
// awaitable.hpp 传递提供 <utility>（std::exchange 未声明），须先于 asio 显式包含。
#include <utility>
#include <boost/asio.hpp>
#include <chrono>
#include <cstring>
#include <algorithm>
#include <flat_set>
#include <iostream>
#include <print>
#include <memory>
#include <mutex>
#include <set>
#include <sstream>
#include <thread>
#include <vector>

namespace asio = boost::asio;
using udp = asio::ip::udp;

// SHA-256 for state hash (lightweight, no OpenSSL dependency)
// Minimal standalone SHA-256 implementation for 64-bit state hash.
namespace {

struct SHA256 {
  uint32_t h[8];
  uint64_t total_len;
  uint8_t buf[64];
  size_t buf_len;

  static constexpr uint32_t k[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  };

  SHA256() {
    h[0] = 0x6a09e667; h[1] = 0xbb67ae85;
    h[2] = 0x3c6ef372; h[3] = 0xa54ff53a;
    h[4] = 0x510e527f; h[5] = 0x9b05688c;
    h[6] = 0x1f83d9ab; h[7] = 0x5be0cd19;
    total_len = 0;
    buf_len = 0;
  }

  static uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }

  void process_block(const uint8_t block[64]) {
    uint32_t w[64];
    for (int i = 0; i < 16; ++i) {
      w[i] = (uint32_t(block[i*4]) << 24) | (uint32_t(block[i*4+1]) << 16) |
             (uint32_t(block[i*4+2]) << 8) | uint32_t(block[i*4+3]);
    }
    for (int i = 16; i < 64; ++i) {
      uint32_t s0 = rotr(w[i-15], 7) ^ rotr(w[i-15], 18) ^ (w[i-15] >> 3);
      uint32_t s1 = rotr(w[i-2], 17) ^ rotr(w[i-2], 19) ^ (w[i-2] >> 10);
      w[i] = w[i-16] + s0 + w[i-7] + s1;
    }
    uint32_t a = h[0], b = h[1], c = h[2], d = h[3];
    uint32_t e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int i = 0; i < 64; ++i) {
      uint32_t S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      uint32_t ch = (e & f) ^ (~e & g);
      uint32_t temp1 = hh + S1 + ch + k[i] + w[i];
      uint32_t S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
      uint32_t temp2 = S0 + maj;
      hh = g; g = f; f = e; e = d + temp1;
      d = c; c = b; b = a; a = temp1 + temp2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d;
    h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
  }

  void update(const uint8_t* data, size_t len) {
    total_len += len;
    size_t offset = 0;
    if (buf_len > 0) {
      size_t to_copy = std::min(len, 64 - buf_len);
      memcpy(buf + buf_len, data, to_copy);
      buf_len += to_copy;
      offset += to_copy;
      if (buf_len == 64) {
        process_block(buf);
        buf_len = 0;
      }
    }
    while (offset + 64 <= len) {
      process_block(data + offset);
      offset += 64;
    }
    if (offset < len) {
      memcpy(buf, data + offset, len - offset);
      buf_len = len - offset;
    }
  }

  void finalize(uint8_t out32[32]) {
    uint64_t bits = total_len * 8;
    uint8_t pad = 0x80;
    update(&pad, 1);
    pad = 0x00;
    while (buf_len != 56) {
      update(&pad, 1);
    }
    uint8_t len_be[8];
    for (int i = 7; i >= 0; --i) {
      len_be[i] = static_cast<uint8_t>(bits & 0xFF);
      bits >>= 8;
    }
    update(len_be, 8);
    for (int i = 0; i < 8; ++i) {
      out32[i*4]   = static_cast<uint8_t>(h[i] >> 24);
      out32[i*4+1] = static_cast<uint8_t>(h[i] >> 16);
      out32[i*4+2] = static_cast<uint8_t>(h[i] >> 8);
      out32[i*4+3] = static_cast<uint8_t>(h[i]);
    }
  }
};

// Compute 64-bit state hash: SHA-256 of state digest, take first 8 bytes as uint64_t.
frame_sync::state_hash_t compute_state_hash_cxx(const void* data, size_t len) {
  SHA256 sha;
  sha.update(static_cast<const uint8_t*>(data), len);
  uint8_t digest[32];
  sha.finalize(digest);
  frame_sync::state_hash_t result;
  memcpy(&result, digest, sizeof(result));
  return result;
}

}  // anonymous namespace

// ===== Engine-scoped globals =====
static GameEnv* g_env = nullptr;

static const unsigned short kDefaultPort = 12346;
static const int kFrameTimeoutMs = 200;
static const int kFrameRateHz = 10;
static const int kStateHashIntervalK = frame_sync::STATE_HASH_INTERVAL_K;

// ===== ScenarioConfig builder (mirrors Python get_scenario_config) =====
static std::shared_ptr<ScenarioConfig> make_scenario_config(uint16_t left_agents,
                                           uint16_t right_agents,
                                           uint32_t seed,
                                           const std::string& /*scenario_name*/) {
  auto sc = ScenarioConfig::make();
  sc->left_agents = left_agents;
  sc->right_agents = right_agents;
  sc->game_engine_random_seed = seed;
  sc->real_time = false;
  sc->deterministic = true;
  sc->end_episode_on_score = false;
  sc->game_duration = 3000;
  sc->reverse_team_processing = bool(seed % 2);

  // Default 4-4-2 formation
  sc->left_team = {
    FormationEntry(0.0f,   0.0f,  e_PlayerRole_GK, false, true),
    FormationEntry(-0.4f, -0.3f,  e_PlayerRole_LB, false, false),
    FormationEntry(-0.15f,-0.3f,  e_PlayerRole_CB, false, false),
    FormationEntry(0.15f, -0.3f,  e_PlayerRole_CB, false, false),
    FormationEntry(0.4f,  -0.3f,  e_PlayerRole_RB, false, false),
    FormationEntry(-0.4f, 0.0f,  e_PlayerRole_LM, false, false),
    FormationEntry(-0.15f,0.0f,  e_PlayerRole_CM, false, false),
    FormationEntry(0.15f, 0.0f,  e_PlayerRole_CM, false, false),
    FormationEntry(0.4f,  0.0f,  e_PlayerRole_RM, false, false),
    FormationEntry(-0.15f,0.3f,  e_PlayerRole_CF, false, false),
    FormationEntry(0.15f, 0.3f,  e_PlayerRole_CF, false, false),
  };
  sc->right_team = {
    FormationEntry(0.0f,   0.0f,  e_PlayerRole_GK, false, false),
    FormationEntry(-0.4f, -0.3f,  e_PlayerRole_LB, false, false),
    FormationEntry(-0.15f,-0.3f,  e_PlayerRole_CB, false, false),
    FormationEntry(0.15f, -0.3f,  e_PlayerRole_CB, false, false),
    FormationEntry(0.4f,  -0.3f,  e_PlayerRole_RB, false, false),
    FormationEntry(-0.4f, 0.0f,  e_PlayerRole_LM, false, false),
    FormationEntry(-0.15f,0.0f,  e_PlayerRole_CM, false, false),
    FormationEntry(0.15f, 0.0f,  e_PlayerRole_CM, false, false),
    FormationEntry(0.4f,  0.0f,  e_PlayerRole_RM, false, false),
    FormationEntry(-0.15f,0.3f,  e_PlayerRole_CF, false, false),
    FormationEntry(0.15f, 0.3f,  e_PlayerRole_CF, false, false),
  };

  return sc;
}

// ===== Build StepWithInput buffer from collected SlotInputs =====
static std::vector<uint8_t> build_frame_input_buffer(
    const std::vector<frame_sync::SlotInput>& slot_inputs) {
  std::vector<uint8_t> buf(slot_inputs.size() * frame_sync::SLOT_INPUT_BYTES);
  for (size_t i = 0; i < slot_inputs.size(); ++i) {
    memcpy(buf.data() + i * frame_sync::SLOT_INPUT_BYTES,
           &slot_inputs[i], frame_sync::SLOT_INPUT_BYTES);
  }
  return buf;
}

// ===== Client session (UDP) =====
struct ClientSessionUDP {
  udp::endpoint endpoint;
  std::unique_ptr<frame_sync::ReliableUDPChannel> channel;
  std::vector<uint16_t> assigned_slots;
  bool ready = false;
  bool version_negotiated = false;
  std::vector<uint8_t> recv_buf;
  bool disconnected = false;
  std::chrono::steady_clock::time_point last_heartbeat;
  int missed_heartbeats = 0;
};

// ===== Engine-integrated frame sync server =====
class EngineFrameSyncServer {
 public:
  EngineFrameSyncServer(asio::io_context& io, unsigned short port,
                        uint16_t left_agents, uint16_t right_agents, uint32_t seed,
                        int slots_per_client = 0)
      : io_(io),
        socket_(io, udp::endpoint(udp::v4(), port)),
        left_agents_(left_agents),
        right_agents_(right_agents),
        num_slots_(left_agents + right_agents),
        seed_(seed),
        frame_id_(0),
        slots_per_client_(slots_per_client),
        retransmit_timer_(io),
        heartbeat_timer_(io) {
    for (size_t i = 0; i < num_slots_; ++i)
      current_inputs_.push_back(frame_sync::SlotInput::Default());
    do_receive();
    do_retransmit_timer();
    do_heartbeat_timer();
  }

  bool all_ready() const {
    std::lock_guard<std::mutex> lock(mu_);
    auto connected = std::ranges::count_if(clients_,
        [](const auto& p) { return !p.second->disconnected; });
    if (connected == 0) return false;
    auto ready = std::ranges::count_if(clients_,
        [](const auto& p) { return !p.second->disconnected && p.second->ready; });
    return ready == connected;
  }

  void run_frame_loop() {
    // Wait for clients
    while (running_ && !all_ready()) {
      std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    if (!running_) return;

    std::println("All clients ready, starting frame loop at {} Hz", kFrameRateHz);

    auto wall_start = std::chrono::steady_clock::now();
    while (running_) {
      auto deadline = std::chrono::steady_clock::now() +
          std::chrono::milliseconds(kFrameTimeoutMs);
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
            [](const auto& p) { return !p.second->disconnected; });
        if (connected == 0) break;
        if (static_cast<int>(received_from_.size()) >= connected) break;
      }

      // ===== Engine integration: apply inputs and step =====
      std::vector<frame_sync::SlotInput> inputs;
      {
        std::lock_guard<std::mutex> lock(mu_);
        inputs = current_inputs_;
      }
      if (g_env) {
        auto frame_buf = build_frame_input_buffer(inputs);
        g_env->StepWithInput(frame_buf.data(), frame_buf.size());
      }

      // Broadcast authoritative frame
      broadcast_authoritative_frame();

      // State hash every K frames
      if (kStateHashIntervalK > 0 && frame_id_ % kStateHashIntervalK == 0 && g_env) {
        // 2026-08-26 使用 canonical digest：跳过不稳定区段
        std::string digest = g_env->get_state_digest();
        frame_sync::state_hash_t hash = compute_state_hash_cxx(
            digest.data(), digest.size());
        broadcast_state_hash(frame_id_, hash);
      }

      ++frame_id_;

      // Diagnostics every 100 frames
      if (frame_id_ % 100 == 0) {
        auto wall_now = std::chrono::steady_clock::now();
        float wall_sec = std::chrono::duration<float>(wall_now - wall_start).count();
        float sps = wall_sec > 0.0f ? static_cast<float>(frame_id_) / wall_sec : 0.0f;
        std::println("[frame {:6d}] SPS: {:.1f}", frame_id_, sps);
      }

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

  void do_heartbeat_timer() {
    heartbeat_timer_.expires_after(std::chrono::milliseconds(frame_sync::HEARTBEAT_INTERVAL_MS));
    heartbeat_timer_.async_wait([this](boost::system::error_code ec) {
      if (ec || !running_) return;
      broadcast_heartbeat();
      check_client_timeouts();
      do_heartbeat_timer();
    });
  }

  void broadcast_heartbeat() {
    uint8_t buf[frame_sync::HEARTBEAT_PACKET_BYTES];
    size_t n = frame_sync::PackHeartbeat(frame_id_, 
        static_cast<uint32_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count()),
        buf, sizeof(buf));
    std::lock_guard<std::mutex> lock(mu_);
    for (auto& p : clients_) {
      if (p.second->disconnected || !p.second->channel) continue;
      p.second->channel->Send(buf, n);
    }
  }

  void check_client_timeouts() {
    auto now = std::chrono::steady_clock::now();
    for (auto& p : clients_) {
      if (p.second->disconnected) continue;
      auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
          now - p.second->last_heartbeat).count();
      if (elapsed > frame_sync::HEARTBEAT_MISS_LIMIT * frame_sync::HEARTBEAT_INTERVAL_MS / 1000) {
        std::println("Client {}:{} timed out (no heartbeat for {}s)",
                     p.first.address().to_string(), p.first.port(), elapsed);
        p.second->disconnected = true;
      }
    }
  }

  std::shared_ptr<ClientSessionUDP> get_or_create_client(const udp::endpoint& sender) {
    std::lock_guard<std::mutex> lock(mu_);
    auto it = clients_.find(sender);
    if (it != clients_.end()) {
      it->second->last_heartbeat = std::chrono::steady_clock::now();
      it->second->missed_heartbeats = 0;
      return it->second;
    }
    auto client = std::make_shared<ClientSessionUDP>();
    client->endpoint = sender;
    client->last_heartbeat = std::chrono::steady_clock::now();
    
    // Multi-slot assignment: find available slots, respecting slots_per_client limit
    std::flat_set<uint16_t> used;
    for (const auto& p : clients_) {
      for (uint16_t s : p.second->assigned_slots) used.insert(s);
    }
    int max_slots = (slots_per_client_ > 0) ? slots_per_client_ : num_slots_;
    for (uint16_t s = 0; s < num_slots_ && static_cast<int>(client->assigned_slots.size()) < max_slots; ++s) {
      if (used.find(s) == used.end()) {
        client->assigned_slots.push_back(s);
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
    std::ostringstream slots_ss;
    for (size_t i = 0; i < client->assigned_slots.size(); ++i) {
      if (i > 0) slots_ss << ",";
      slots_ss << client->assigned_slots[i];
    }
    std::println("Client connected: {}:{} → slots [{}]",
                 sender.address().to_string(), sender.port(),
                 slots_ss.str());
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
        client->assigned_slots.data(),
        static_cast<uint16_t>(client->assigned_slots.size()), buf, sizeof(buf));
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
    
    // Handle VersionNegotiate
    if (type == static_cast<uint8_t>(frame_sync::MessageType::VersionNegotiate)) {
      if (client->recv_buf.size() < frame_sync::VERSION_NEGOTIATE_BYTES) return false;
      frame_sync::version_negotiate_t ver;
      size_t used = frame_sync::UnpackVersionNegotiate(
          client->recv_buf.data(), client->recv_buf.size(), &ver);
      if (used == 0) return false;
      std::println("Client version: {} (min: {})", ver.version, ver.min_version);
      client->version_negotiated = true;
      client->recv_buf.erase(client->recv_buf.begin(),
                             client->recv_buf.begin() + used);
      return true;
    }
    
    // Handle Heartbeat
    if (type == static_cast<uint8_t>(frame_sync::MessageType::Heartbeat)) {
      if (client->recv_buf.size() < frame_sync::HEARTBEAT_PACKET_BYTES) return false;
      frame_sync::heartbeat_t hb;
      size_t used = frame_sync::UnpackHeartbeat(
          client->recv_buf.data(), client->recv_buf.size(), &hb);
      if (used == 0) return false;
      client->last_heartbeat = std::chrono::steady_clock::now();
      client->missed_heartbeats = 0;
      client->recv_buf.erase(client->recv_buf.begin(),
                             client->recv_buf.begin() + used);
      return true;
    }
    
    // Handle Ready
    if (type == static_cast<uint8_t>(frame_sync::MessageType::Ready)) {
      client->ready = true;
      std::ostringstream slots_ss;
      for (size_t i = 0; i < client->assigned_slots.size(); ++i) {
        if (i > 0) slots_ss << ",";
        slots_ss << client->assigned_slots[i];
      }
      std::println("Client slots [{}] ready", slots_ss.str());
      client->recv_buf.erase(client->recv_buf.begin());
      return true;
    }
    
    // Handle FrameInput
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

  asio::io_context& io_;
  udp::socket socket_;
  asio::steady_timer retransmit_timer_;
  asio::steady_timer heartbeat_timer_;
  mutable std::mutex mu_;
  std::map<udp::endpoint, std::shared_ptr<ClientSessionUDP>> clients_;
  uint16_t left_agents_;
  uint16_t right_agents_;
  size_t num_slots_;
  uint32_t seed_;
  frame_sync::frame_id_t frame_id_;
  int slots_per_client_;
  std::vector<frame_sync::SlotInput> current_inputs_;
  std::set<ClientSessionUDP*> received_from_;
  std::atomic<bool> running_{true};
};

int main(int argc, char* argv[]) {
  unsigned short port = kDefaultPort;
  uint16_t left = 1, right = 1;
  uint32_t seed = 42;
  int slots_per_client = 0;  // 0 = all available slots
  if (argc >= 2) port = static_cast<unsigned short>(std::stoi(argv[1]));
  if (argc >= 4) {
    left = static_cast<uint16_t>(std::stoi(argv[2]));
    right = static_cast<uint16_t>(std::stoi(argv[3]));
  }
  if (argc >= 5) seed = static_cast<uint32_t>(std::stoul(argv[4]));
  if (argc >= 6) slots_per_client = std::stoi(argv[5]);

  try {
    // Initialize engine (headless, before server so IO context isn't blocking)
    {
      std::println("Initializing GameEnv (headless, {}v{}, seed={}, slots_per_client={})...",
                   left, right, seed, slots_per_client);
      g_env = new GameEnv();
      g_env->game_config.render = false;
      g_env->game_config.physics_steps_per_frame = 10;
      g_env->game_config.render_resolution_x = 1280;
      g_env->game_config.render_resolution_y = 720;
      g_env->start_game();
      auto sc = make_scenario_config(left, right, seed, "");
      g_env->state = GameState::game_running;
      g_env->reset(*sc, false);
      std::println("GameEnv ready.");
    }

    asio::io_context ioc;
    EngineFrameSyncServer server(ioc, port, left, right, seed, slots_per_client);
    std::thread io_thread([&ioc]() { ioc.run(); });
    std::println("Engine frame sync server (reliable UDP) on port {}", port);
    server.run_frame_loop();
    server.stop();
    ioc.stop();
    if (io_thread.joinable()) io_thread.join();

    // Cleanup
    if (g_env) {
      delete g_env;
      g_env = nullptr;
    }
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "Error: " << e.what() << std::endl;
    if (g_env) { delete g_env; g_env = nullptr; }
    return 1;
  }
}
