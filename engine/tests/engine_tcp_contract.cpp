// 2026-09-09: actual GameEnv + production TCP transport, checked over real sockets.
#include "frame_sync/engine_tcp_bridge.hpp"
#include <iostream>
#include <thread>
#include <map>

namespace {
namespace asio = boost::asio;
using tcp = asio::ip::tcp;
using namespace frame_sync;
using namespace std::chrono_literals;
size_t assertions = 0, confirmed = 0, hashes_checked = 0, snapshot_bytes = 0;
void Require(bool value, const char* message) {
  ++assertions;
  if (!value) throw std::runtime_error(message);
}
template<class Predicate> void Until(Predicate predicate, const char* message) {
  const auto deadline = std::chrono::steady_clock::now() + 5s;
  while (std::chrono::steady_clock::now() < deadline) {
    if (predicate()) return;
    std::this_thread::sleep_for(1ms);
  }
  Require(false, message);
}
struct Peer {
  tcp::socket socket;
  std::vector<uint8_t> receive;
  explicit Peer(asio::io_context& io, unsigned short port, int receive_bytes = 65536) : socket(io) {
    socket.open(tcp::v4());
    socket.set_option(asio::socket_base::receive_buffer_size(receive_bytes));
    socket.connect({asio::ip::address_v4::loopback(), port});
    socket.non_blocking(true);
  }
  void Send(const std::vector<uint8_t>& bytes) {
    // Tiny protocol packets: use a finite deadline, never wait indefinitely.
    size_t sent = 0;
    Until([&] {
      boost::system::error_code ec;
      sent += socket.write_some(asio::buffer(bytes.data() + sent, bytes.size() - sent), ec);
      if (ec && ec != asio::error::would_block && ec != asio::error::try_again)
        throw std::runtime_error("peer write failed: " + ec.message());
      return sent == bytes.size();
    }, "peer write deadline");
  }
  bool ReadAvailable() {
    std::array<uint8_t, 4096> bytes;
    boost::system::error_code ec;
    const auto length = socket.read_some(asio::buffer(bytes), ec);
    if (ec == asio::error::eof || ec == asio::error::connection_reset) return false;
    if (ec && ec != asio::error::would_block && ec != asio::error::try_again)
      throw std::runtime_error("peer read failed: " + ec.message());
    Require(AppendBoundedBytes(receive, bytes.data(), length, 1024 * 1024 + 8192), "probe receive limit");
    return true;
  }
  std::vector<uint8_t> Packet() {
    size_t need = 0;
    Until([&] {
      Require(ReadAvailable(), "unexpected peer EOF");
      if (receive.empty()) return false;
      switch (static_cast<MessageType>(receive[0])) {
        case MessageType::SessionStart: need = 9; break;
        case MessageType::SlotAssignment: {
          if (receive.size() < 3) return false;
          uint16_t count; std::memcpy(&count, receive.data() + 1, 2);
          Require(count == 1, "unexpected assigned slot count"); need = 5; break;
        }
        case MessageType::AuthoritativeFrame: {
          if (receive.size() < 7) return false;
          uint16_t count; std::memcpy(&count, receive.data() + 5, 2);
          Require(count == 2, "unexpected authority slots"); need = 7 + count * SLOT_INPUT_BYTES; break;
        }
        case MessageType::StateHash: need = STATE_HASH_PACK_BYTES; break;
        case MessageType::Heartbeat: need = HEARTBEAT_PACK_BYTES; break;
        case MessageType::TakeoverNotify: case MessageType::HandbackNotify: need = 7; break;
        case MessageType::StateSnapshot: {
          if (receive.size() < 9) return false;
          uint32_t size; std::memcpy(&size, receive.data() + 5, 4);
          Require(size <= 1024 * 1024, "wire snapshot limit"); need = 9 + size; break;
        }
        default: throw std::runtime_error("unknown server packet");
      }
      return receive.size() >= need;
    }, "server packet deadline");
    std::vector<uint8_t> packet(receive.begin(), receive.begin() + need);
    receive.erase(receive.begin(), receive.begin() + need);
    return packet;
  }
  void SessionStart() {
    const auto packet = Packet(); uint32_t seed; uint16_t left, right;
    Require(UnpackSessionStart(packet.data(), packet.size(), &seed, &left, &right) == 9,
            "session header invalid");
    Require(seed == 42 && left == 1 && right == 1, "session parameters differ");
  }
  void Assignment(uint16_t expected) {
    const auto packet = Packet(); std::vector<uint16_t> slots;
    Require(UnpackSlotAssignment(packet.data(), packet.size(), &slots) == 5, "slot header invalid");
    Require(slots.size() == 1 && slots[0] == expected, "slot ownership differs");
  }
  void Input(frame_id_t frame, uint16_t slot, SlotInput input) {
    std::vector<uint8_t> bytes(9 + SLOT_INPUT_BYTES);
    Require(PackClientFrameInput(frame, &slot, &input, 1, bytes.data(), bytes.size()) == bytes.size(), "pack failed");
    Send(bytes);
  }
  void ExpectClosed() {
    Until([&] { return !ReadAvailable(); }, "peer was not disconnected");
  }
};
struct RunningServer {
  asio::io_context io;
  EngineTCPServer server;
  std::exception_ptr io_error, frame_error;
  std::atomic<bool> failed{false};
  std::thread network, frames;
  RunningServer(GameEnv& env, const MultiplayerConfig& config, EngineTCPServerLimits limits)
      : server(io, 0, config, MakeGameEnvCallbacks(&env),
               MakeGameEnvBotObserver(&env, config.left_agents, config.right_agents), limits),
        network([this] { try { io.run(); } catch (...) { io_error = std::current_exception(); failed = true; server.stop(); } }),
        frames([this] { try { server.run_frame_loop(); } catch (...) { frame_error = std::current_exception(); failed = true; server.stop(); } }) {}
  ~RunningServer() { Stop(); }
  void Stop() { server.stop(); if (frames.joinable()) frames.join(); if (network.joinable()) network.join(); }
  void Check() { Stop(); if (io_error) std::rethrow_exception(io_error); if (frame_error) std::rethrow_exception(frame_error); }
};
struct Oracle {
  GameEnv& env;
  EngineCallbacks engine;
  frame_id_t next = 0;
  std::map<frame_id_t, uint64_t> hashes;
  size_t takeovers = 0, handbacks = 0;
  explicit Oracle(GameEnv& env) : env(env), engine(MakeGameEnvCallbacks(&env)) {}
  void CheckSide(const std::vector<uint8_t>& packet) {
    const auto type = static_cast<MessageType>(packet[0]);
    if (type == MessageType::StateHash) {
      frame_id_t frame; uint64_t hash;
      Require(UnpackStateHash(packet.data(), packet.size(), &frame, &hash) == packet.size(), "hash packet invalid");
      Require(hashes.contains(frame) && hashes.at(frame) == hash, "actual GameEnv TCP state hash differs");
      ++hashes_checked;
    } else if (type == MessageType::TakeoverNotify) ++takeovers;
    else if (type == MessageType::HandbackNotify) ++handbacks;
    else Require(type == MessageType::Heartbeat, "unexpected side packet");
  }
  std::vector<uint8_t> Authority(Peer& peer, bool apply) {
    for (;;) {
      auto packet = peer.Packet();
      if (packet[0] != std::to_underlying(MessageType::AuthoritativeFrame)) { CheckSide(packet); continue; }
      frame_id_t frame; std::vector<SlotInput> inputs;
      Require(UnpackAuthoritativeFrame(packet.data(), packet.size(), &frame, &inputs) == packet.size(), "authority packet invalid");
      Require(frame == (apply ? next : next - 1), "authority order has a gap");
      if (apply) {
        engine.step_frame(inputs); hashes[frame] = engine.compute_hash(); ++next; ++confirmed;
      }
      return packet;
    }
  }
};
void Scenario() {
  MultiplayerConfig config; config.left_agents = 1; config.right_agents = 1;
  config.seed = 42; config.frame_rate_hz = 60; config.render = false;
  EngineTCPServerLimits limits; limits.connections = 4; limits.input_timeout = 500ms;
  limits.ready_timeout = 1000ms; limits.write_timeout = 200ms; limits.socket_send_bytes = 1024;
  GameEnv authority, reference;
  StartTCPGame(authority, config, limits); StartTCPGame(reference, config, limits);
  RunningServer running(authority, config, limits);
  asio::io_context peers;
  const auto port = running.server.port();
  // Pending handshakes count immediately and release capacity without a slot.
  {
    std::vector<std::unique_ptr<Peer>> held;
    for (unsigned i = 0; i < 4; ++i) { held.push_back(std::make_unique<Peer>(peers, port)); held.back()->SessionStart(); }
    Require(running.server.stats().pending_handshakes == 4, "unregistered pending handshakes");
    Peer rejected(peers, port); rejected.ExpectClosed();
    Require(running.server.stats().rejected_connections == 1, "connection overflow not counted");
  }
  Until([&] { return running.server.stats().connections == 0; }, "pending connections not released");
  {
    Peer malformed(peers, port); malformed.SessionStart(); malformed.Send({254}); malformed.ExpectClosed();
  }
  Until([&] { return running.server.stats().connections == 0; }, "invalid peer not released");
  {
    Peer expired(peers, port); expired.SessionStart(); expired.ExpectClosed();
    Require(running.server.stats().ready_timeouts == 1, "anonymous reservation did not expire");
  }
  Until([&] { return running.server.stats().connections == 0; }, "expired peer not released");
  Peer left(peers, port), right(peers, port);
  left.SessionStart(); right.SessionStart();
  left.Send({0}); left.Assignment(0); right.Send({0}); right.Assignment(1);
  left.Send({6}); right.Send({6});
  Oracle oracle(reference);
  auto await_input = [&](frame_id_t frame) {
    Until([&] {
      if (running.failed) throw std::runtime_error("engine frame thread failed");
      const auto stats = running.server.stats();
      Require(stats.next_frame <= frame, "driver missed server input window");
      return stats.next_frame == frame && stats.accepting_inputs;
    }, "server stopped collecting inputs");
  };
  auto direction = [](frame_id_t frame, bool second) {
    auto input = SlotInput::Default(); input.dir_x = second ? -0.5f : 0.5f;
    input.dir_y = frame % 2 ? 0.25f : -0.25f; return input;
  };
  for (frame_id_t frame = 0; frame < 12; ++frame) {
    await_input(frame); left.Input(frame, 0, direction(frame, false)); right.Input(frame, 1, direction(frame, true));
    const auto first = oracle.Authority(left, true), second = oracle.Authority(right, false);
    Require(first == second, "peers received different frozen inputs");
    frame_id_t decoded_frame; std::vector<SlotInput> decoded;
    UnpackAuthoritativeFrame(first.data(), first.size(), &decoded_frame, &decoded);
    Require(decoded[0] == direction(frame, false) && decoded[1] == direction(frame, true),
            "submitted input was not applied to its owned slot");
  }
  // Disconnect at a frame boundary; the next authority is generated from real
  // observed player/ball positions. The remaining player continues advancing.
  left.socket.close();
  Until([&] { return running.server.stats().active_connections == 1; }, "disconnect not recognized");
  for (frame_id_t frame = 12; frame < 15; ++frame) {
    await_input(frame); right.Input(frame, 1, direction(frame, true)); oracle.Authority(right, true);
  }
  Require(running.server.stats().bot_slots == 1, "disconnected slot not taken over");
  Require(oracle.takeovers == 1, "missing or duplicate takeover notification");
  // A wrong token cannot take the disconnected player's slot.
  {
    Peer invalid(peers, port); invalid.SessionStart(); std::vector<uint8_t> bytes(RECONNECT_REQUEST_BYTES);
    PackReconnectRequest(0, bytes.data(), bytes.size()); invalid.Send(bytes); invalid.ExpectClosed();
  }
  Peer resumed(peers, port); resumed.SessionStart();
  std::vector<uint8_t> reconnect(RECONNECT_REQUEST_BYTES);
  PackReconnectRequest(MakeSessionToken(0, 42, 1), reconnect.data(), reconnect.size());
  resumed.Send(reconnect); resumed.Assignment(0);
  // The request may arrive while frame15 is collecting. Submit that frame so
  // the server can service the snapshot at the following safe boundary.
  const auto before15 = reference.get_state_digest();
  await_input(15); right.Input(15, 1, direction(15, true));
  const auto frame15 = oracle.Authority(right, true);
  const auto after15 = reference.get_state_digest();
  const auto latest_state = reference.get_state("");
  const auto snapshot = resumed.Packet();
  frame_id_t next_frame; const void* state; uint32_t length;
  Require(UnpackStateSnapshot(snapshot.data(), snapshot.size(), &next_frame, &state, &length) == snapshot.size(), "reconnect snapshot invalid");
  Require(next_frame == 15 || next_frame == 16, "snapshot labels a different simulation boundary");
  snapshot_bytes = length;
  reference.set_state(std::string(static_cast<const char*>(state), length));
  Require(reference.get_state_digest() == (next_frame == 15 ? before15 : after15),
          "restored real snapshot differs at its claimed frame");
  reference.set_state(latest_state);
  resumed.Send({6});
  if (next_frame == 15) Require(oracle.Authority(resumed, false) == frame15, "authority lost while awaiting reconnect Ready");
  for (frame_id_t frame = 16; frame < 24; ++frame) {
    await_input(frame); right.Input(frame, 1, direction(frame, true)); resumed.Input(frame, 0, direction(frame, false));
    const auto second = oracle.Authority(right, true), first = oracle.Authority(resumed, false);
    Require(first == second, "reconnected authority stream has a gap or different payload");
  }
  Require(running.server.stats().bot_slots == 0, "ready reconnected player did not regain control");
  Require(oracle.handbacks >= 1, "handback was not broadcast");
  Require(running.server.stats().reconnects == 1 && running.server.stats().snapshots_sent == 1,
          "invalid reconnect affected state or snapshot was not sent exactly once");
  // A real 87KB-class GameEnv snapshot blocks this spectator's tiny receive
  // window; both active players keep receiving and verifying subsequent frames.
  Peer slow(peers, port, 1024); slow.SessionStart(); slow.Send({std::to_underlying(MessageType::SpectatorJoin)});
  for (frame_id_t frame = 24; frame < 40; ++frame) {
    await_input(frame); right.Input(frame, 1, direction(frame, true)); resumed.Input(frame, 0, direction(frame, false));
    const auto second = oracle.Authority(right, true), first = oracle.Authority(resumed, false);
    Require(first == second, "slow spectator interfered with healthy authority");
  }
  Until([&] { return running.server.stats().active_connections == 2; }, "slow spectator not disconnected");
  Require(running.server.stats().write_timeouts == 1, "slow snapshot did not hit write deadline");
  Require(running.server.stats().snapshots_sent == 2, "slow spectator snapshot was not queued");
  Require(hashes_checked >= 8, "not enough real engine hashes checked");
  const auto stats = running.server.stats();
  Require(stats.connections <= limits.connections && stats.receive_capacity <= limits.connections * EngineTCPServer::kReceiveLimit,
          "actual TCP receive/connection budget exceeded");
  Require(stats.queued_send_bytes <= limits.connections * limits.send.byte_limit, "actual TCP send budget exceeded");
  running.Check();
}
}  // namespace
int main(int, char**) {
  try {
    Scenario();
    std::cout << "{\"passed\":true,\"assertions\":" << assertions << ",\"skipped\":0,\"confirmed_frames\":" << confirmed
              << ",\"hashes_checked\":" << hashes_checked << ",\"reconnect_snapshot_bytes\":" << snapshot_bytes << "}\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "engine_tcp_contract: " << error.what() << '\n'; return 1;
  }
}
