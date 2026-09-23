// Copyright 2026 Google LLC & Contributors
// 2026-09-09: bounded TCP session transport with engine work at frame boundaries.
#ifndef GFOOTBALL_FRAME_SYNC_ENGINE_TCP_SERVER_HPP
#define GFOOTBALL_FRAME_SYNC_ENGINE_TCP_SERVER_HPP
#include "frame_sync/bounded_tcp_writer.hpp"
#include "frame_sync/native_recovery_transfer.hpp"
#include "frame_sync/server_input_window.hpp"
#include "frame_sync/engine_integration.hpp"
#include "frame_sync/bot_takeover.hpp"
#include "frame_sync/protocol_io.hpp"
#include <array>
#include <atomic>
#include <condition_variable>
#include <set>
#include <optional>

namespace frame_sync {
struct EngineTCPServerLimits {
  size_t connections = 128;
  StreamBudget send{256, 2 * 1024 * 1024};
  size_t snapshot_bytes = 1024 * 1024;
  std::chrono::milliseconds write_timeout{5000};
  std::chrono::milliseconds ready_timeout{30000};
  // 2026-09-14: absolute resource budget; Ready and liveness retain separate bounds.
  std::chrono::milliseconds loading_timeout{kNativeInitialLoadingTimeout};
  std::chrono::milliseconds idle_timeout{3000};
  std::chrono::milliseconds recovery_grace{30000};
  std::chrono::milliseconds input_timeout{FRAME_INPUT_TIMEOUT_MS};
  int socket_send_bytes = 64 * 1024;
  void Validate(const MultiplayerConfig& config) const {
    const StreamBudget validated(send.message_limit, send.byte_limit);
    if (connections == 0 || connections > 1024 ||
        snapshot_bytes == 0 || snapshot_bytes > 64 * 1024 * 1024 ||
        write_timeout.count() < 1 || write_timeout > std::chrono::seconds(30) ||
        ready_timeout.count() < 1 || ready_timeout > std::chrono::minutes(5) ||
        loading_timeout.count() < 1 || loading_timeout > kNativeInitialLoadingTimeout ||
        idle_timeout.count() < 1 || idle_timeout > std::chrono::minutes(5) ||
        recovery_grace.count() < 1 || recovery_grace > std::chrono::minutes(5) ||
        input_timeout.count() < 1 || input_timeout > std::chrono::seconds(1) ||
        socket_send_bytes < 1024 || socket_send_bytes > 1024 * 1024 ||
        config.left_agents > 11 || config.right_agents > 11 ||
        config.left_agents + config.right_agents == 0 ||
        // 2026-09-13: reject split authority and engine cadence.
        // config.frame_rate_hz < 1 || config.frame_rate_hz > 240)
        config.frame_rate_hz < 1 || config.frame_rate_hz > 240 ||
        (config.native_product && config.frame_rate_hz != NativeMatchContract::kHz))
      throw std::invalid_argument("invalid integrated TCP server configuration or limits");
  }
};
struct EngineTCPServerStats {
  size_t connections = 0, active_connections = 0, pending_handshakes = 0;
  size_t receive_capacity = 0, queued_send_bytes = 0, queued_send_messages = 0;
  size_t rejected_connections = 0, invalid_messages = 0, overload_disconnects = 0;
  size_t write_timeouts = 0, ready_timeouts = 0, idle_timeouts = 0;
  size_t loading_timeouts = 0;
  // 2026-09-15: count successful authenticated admission releases.
  size_t loading_cancellations = 0;
  size_t snapshots_sent = 0, snapshot_rejections = 0, reconnects = 0, bot_slots = 0;
  frame_id_t next_frame = 0;
  bool accepting_inputs = false;
};
// Engine callbacks are invoked only by run_frame_loop (never by IO callbacks).
// The host keeps its engine alive until that call has returned after stop().
// 2026-09-15: private transport-policy extraction; original lines:
// class EngineTCPServer {
// Transport policy owns only connection establishment and stream options.
// Session grants, admission, snapshots, AI ownership and frame execution stay
// in one BasicEngineSessionServer implementation.
struct NativeTCPTransport {
  using Socket = boost::asio::ip::tcp::socket;
  using Acceptor = boost::asio::ip::tcp::acceptor;
  NativeTCPTransport() = delete;
  ~NativeTCPTransport() = default;
  NativeTCPTransport(const NativeTCPTransport&) = delete;
  NativeTCPTransport& operator=(const NativeTCPTransport&) = delete;
  NativeTCPTransport(NativeTCPTransport&&) = delete;
  NativeTCPTransport& operator=(NativeTCPTransport&&) = delete;
  static boost::asio::ip::tcp::endpoint BindEndpoint(unsigned short port) {
    return {boost::asio::ip::tcp::v4(),port};
  }
  // 2026-09-21: TCP writes drain into the kernel, whose close retains queued output.
  static bool OutputDrained(const Socket&) { return true; }
  static void BeginClose(Acceptor&) {}
  static void Configure(Socket& socket,bool native,int send_bytes,boost::system::error_code& error) {
    if(native) {
      socket.set_option(boost::asio::ip::tcp::no_delay(true),error);
      if(error)return;
    }
    socket.set_option(boost::asio::socket_base::send_buffer_size(send_bytes),error);
  }
};
template<class Transport>
class BasicEngineSessionServer {
 private:
// 2026-09-15: private transport-policy extraction; original lines:
//   using tcp = boost::asio::ip::tcp;
  using Socket = typename Transport::Socket;
  using Acceptor = typename Transport::Acceptor;
  // 2026-09-14: loading does not satisfy the opening barrier or accept inputs.
  // enum class Phase { Identify, AwaitReady, SnapshotPending, Streaming };
// 2026-09-15: terminal admissions must not hold the opening barrier while their receipt drains.
//   enum class Phase { Identify, Loading, AwaitReady, SnapshotPending, Streaming };
  enum class Phase { Identify, Loading, AwaitReady, SnapshotPending, Streaming, Cancelled };
  struct Session {
// 2026-09-15: private transport-policy extraction; original lines:
//     std::shared_ptr<tcp::socket> socket;
//     BoundedTCPWriter writer;
    std::shared_ptr<Socket> socket;
    BasicBoundedStreamWriter<Socket> writer;
    std::vector<uint8_t> receive;
    std::optional<uint16_t> slot;
    session_token_t token = 0;
    uint32_t session_id = 0;
    Phase phase = Phase::Identify;
    bool spectator = false, disconnected = false, read_pending = false, resume_pending = false;
    bool snapshot_sent = false;
    bool recovery = false, rejecting = false;
    std::optional<NativeRecoveryGrant> grant;
    std::optional<NativeRecoveryReady> ready_proof;
    std::optional<frame_id_t> accepted_frame;
    std::optional<std::chrono::steady_clock::time_point> reservation_until;
    std::unique_ptr<NativeRecoverySender> recovery_sender;
    const std::chrono::steady_clock::time_point connected_at = std::chrono::steady_clock::now();
    std::chrono::steady_clock::time_point last_activity = connected_at;
    std::chrono::steady_clock::time_point ready_since = connected_at;
    std::optional<std::chrono::steady_clock::time_point> loading_until;
// 2026-09-15: private transport-policy extraction; original lines:
//     Session(tcp::socket socket, const EngineTCPServerLimits& limits)
//         : socket(std::make_shared<tcp::socket>(std::move(socket))),
    Session(Socket socket, const EngineTCPServerLimits& limits)
        : socket(std::make_shared<Socket>(std::move(socket))),
          writer(this->socket, limits.send, limits.write_timeout) {}
    ~Session() = default;
    Session(const Session&) = delete;
    Session& operator=(const Session&) = delete;
    Session(Session&&) = delete;
    Session& operator=(Session&&) = delete;
  };
  struct Impl : std::enable_shared_from_this<Impl> {
    Impl(boost::asio::io_context& io, unsigned short port, MultiplayerConfig config,
         EngineCallbacks engine, std::function<BotGameSnapshot()> observe,
         EngineTCPServerLimits limits)
// 2026-09-15: private transport-policy extraction; original lines:
//         : io(io), acceptor(io, {tcp::v4(), port}), timer(io), config(std::move(config)),
        : io(io), acceptor(io, Transport::BindEndpoint(port)), timer(io), config(std::move(config)),
// 2026-09-13: fixed pending input storage covers every controlled slot.
//           engine(std::move(engine)), observe(std::move(observe)), limits(std::move(limits)) {
          engine(std::move(engine)), observe(std::move(observe)), limits(std::move(limits)),
// 2026-09-13: apply the native match cadence to disconnected-player AI.
//           pending_inputs(this->config.left_agents + this->config.right_agents) {
          pending_inputs(this->config.left_agents + this->config.right_agents),
          bots(this->config.native_product ? NativeMatchContract::kHz : 10) {
      this->limits.Validate(this->config);
      if (!this->engine.step_frame || !this->engine.save_state ||
          !this->engine.compute_hash || !this->observe)
        throw std::invalid_argument("integrated TCP server needs engine and bot observation callbacks");
      inputs.assign(this->config.left_agents + this->config.right_agents, SlotInput::Default());
      if (this->config.native_product)
        credentials = std::make_unique<NativeRecoveryCredentials>(inputs.size(), this->limits.recovery_grace);
    }
// 2026-09-15: private transport-policy extraction; original lines:
    Impl() = delete;
    ~Impl() = default;
    Impl(const Impl&) = delete;
    Impl& operator=(const Impl&) = delete;
    Impl(Impl&&) = delete;
    Impl& operator=(Impl&&) = delete;
    void Start() { Accept(); Maintain(); }
    void Stop() {
      if (!running.exchange(false)) return;
      // 2026-09-21: custom accept/read completions must be detached before callers stop IO.
      Transport::BeginClose(acceptor);
      {
        std::lock_guard lock(mutex);
        for (auto& client : clients) CloseLocked(client);
        input_cv.notify_all();
      }
// 2026-09-15: private transport-policy extraction; original lines:
//       boost::asio::post(io, [self = shared_from_this(), this] {
      boost::asio::post(io, [self = this->shared_from_this(), this] {
        std::lock_guard lock(mutex);
        boost::system::error_code ec; acceptor.close(ec); timer.cancel(); CleanupLocked();
      });
    }
    void CloseLocked(const std::shared_ptr<Session>& client) {
      if (client->disconnected) return;
      client->disconnected = true;
      if (client->writer.status() == StreamStatus::WriteTimeout) ++counters.write_timeouts;
      client->writer.Close();
// 2026-09-13: disconnect removes all uncommitted inputs, including future frames.
//       if (client->slot) received.erase(*client->slot);
// 2026-09-14: late callbacks from superseded transports cannot erase the new owner input or credential.
//       if (client->slot) pending_inputs.RemoveSlot(*client->slot);
      const auto now = std::chrono::steady_clock::now();
      if (client->slot && (!client->recovery || OwnsRecoveryLocked(client, now))) {
        pending_inputs.RemoveSlot(*client->slot);
        if (client->recovery) {
          if (!client->reservation_until) client->reservation_until = now + limits.recovery_grace;
          credentials->detach(*client->slot, client->grant->generation, now);
        }
      }
      client->recovery_sender.reset();
      input_cv.notify_all();
    }
    bool SendLocked(const std::shared_ptr<Session>& client, const uint8_t* data, size_t length) {
      if (client->disconnected) return false;
      if (client->writer.TrySend(data, length)) return true;
      if (client->writer.status() == StreamStatus::Capacity) ++counters.overload_disconnects;
      CloseLocked(client); return false;
    }
    void CleanupLocked() {
      const auto now = std::chrono::steady_clock::now();
      for (auto& client : clients) {
        // 2026-09-14: elapsed loading budgets cannot gain extra reservation grace.
        if (!started && client->disconnected && client->loading_until &&
            now >= *client->loading_until && client->grant) {
          credentials->release_admission(client->grant->slot,client->grant->generation,now);
          client->slot.reset();client->grant.reset();
        }
        if (!started && client->disconnected && client->recovery && client->grant &&
            client->reservation_until && now >= *client->reservation_until) {
          credentials->release_admission(client->grant->slot, client->grant->generation, now);
          client->slot.reset();
          client->grant.reset();
        }
      }
      for (auto& client : clients)
        if (client->disconnected) std::vector<uint8_t>().swap(client->receive);
      std::erase_if(clients, [this](const auto& client) {
        // Keep <=22 slot reservations during a live match; the transport data
        // is freed independently. Pending/spectator/handed-over records expire.
// 2026-09-14: retain pregame recovery reservations for their original bounded grace period.
//         return client->disconnected && (!started || !client->slot) &&
        return client->disconnected &&
               ((!started && !client->recovery) || !client->slot) &&
               !client->read_pending && client->writer.queued_messages() == 0;
      });
    }
    bool InvalidLocked(const std::shared_ptr<Session>& client) {
// 2026-09-14: invalid ownership revokes recovery and removes its pending inputs before detaching.
//       ++counters.invalid_messages; CloseLocked(client); return false;
      ++counters.invalid_messages;
      if (client->recovery && client->grant) {
        const auto now = std::chrono::steady_clock::now();
        if (OwnsRecoveryLocked(client, now)) pending_inputs.RemoveSlot(*client->slot);
        credentials->revoke(client->grant->slot, client->grant->generation, now);
        if (!started) {
          credentials->release_admission(client->grant->slot, client->grant->generation, now);
          if (client->slot) pending_inputs.RemoveSlot(*client->slot);
          client->slot.reset();
        }
      }
      CloseLocked(client); return false;
    }
    void Accept() {
// 2026-09-15: private transport-policy extraction; original lines:
//       acceptor.async_accept([self = shared_from_this(), this](boost::system::error_code ec, tcp::socket socket) {
      acceptor.async_accept([self = this->shared_from_this(), this](boost::system::error_code ec, Socket socket) {
        std::lock_guard lock(mutex);
        if (ec || !running) return;
        CleanupLocked();
        if (clients.size() >= limits.connections) {
          ++counters.rejected_connections; socket.close(ec); Accept(); return;
        }
// 2026-09-13: send product authority/hash packets promptly instead of delaying the peer frame clock.
//         socket.set_option(boost::asio::socket_base::send_buffer_size(limits.socket_send_bytes), ec);
// 2026-09-15: private transport-policy extraction; original lines:
//         if (config.native_product) {
//           socket.set_option(tcp::no_delay(true),ec);
//           if (ec) { ++counters.rejected_connections; socket.close(ec); Accept(); return; }
//         }
//         socket.set_option(boost::asio::socket_base::send_buffer_size(limits.socket_send_bytes), ec);
        Transport::Configure(socket,config.native_product,limits.socket_send_bytes,ec);
        if (ec) { ++counters.rejected_connections; socket.close(ec); Accept(); return; }
        auto client = std::make_shared<Session>(std::move(socket), limits);
        clients.push_back(client);  // Includes peers that have not sent a byte.
        std::array<uint8_t, 9> bytes;
        const auto length = PackSessionStart(config.seed, config.left_agents, config.right_agents,
                                              bytes.data(), bytes.size());
        // 2026-09-13: product servers wait for Hello before revealing or assigning a session.
        // if (SendLocked(client, bytes.data(), length)) Read(client);
        if (config.native_product || SendLocked(client, bytes.data(), length)) Read(client);
        Accept();
      });
    }
    void Maintain() {
      timer.expires_after(std::chrono::milliseconds(25));
// 2026-09-15: private transport-policy extraction; original lines:
//       timer.async_wait([self = shared_from_this(), this](boost::system::error_code ec) {
      timer.async_wait([self = this->shared_from_this(), this](boost::system::error_code ec) {
        std::lock_guard lock(mutex);
        if (ec || !running) return;
        const auto now = std::chrono::steady_clock::now();
        for (auto& client : clients) {
          if (client->disconnected) continue;
// 2026-09-14: expire the recovery lease and drain explicit rejections.
//           if (client->writer.is_closed()) CloseLocked(client);
// 2026-09-21: reliable UDP must retain terminal data until its transport ACK arrives.
//           if (client->rejecting && client->writer.queued_messages() == 0) CloseLocked(client);
          if (client->rejecting && client->writer.queued_messages() == 0 &&
              Transport::OutputDrained(*client->socket)) CloseLocked(client);
          else if (client->writer.is_closed()) CloseLocked(client);
          else if (client->recovery && client->grant && !OwnsRecoveryLocked(client, now)) CloseLocked(client);
          // 2026-09-14: use independent absolute loading and Ready deadlines.
          // else if (client->phase != Phase::Streaming && now - client->connected_at >= limits.ready_timeout) {
          else if (client->loading_until && now >= *client->loading_until) {
            ++counters.loading_timeouts; CloseLocked(client);
          } else if (client->phase == Phase::Loading && now-client->last_activity >= limits.idle_timeout) {
            ++counters.idle_timeouts; CloseLocked(client);
          } else if (client->phase != Phase::Streaming && client->phase != Phase::Loading &&
                     now - client->ready_since >= limits.ready_timeout) {
            ++counters.ready_timeouts; CloseLocked(client);
          } else if (client->phase == Phase::Streaming && !client->spectator &&
                     now - client->last_activity >= limits.idle_timeout) {
            ++counters.idle_timeouts; CloseLocked(client);
          }
        }
        CleanupLocked(); Maintain();
      });
    }
    void Read(const std::shared_ptr<Session>& client) {
      auto bytes = std::make_shared<std::array<uint8_t, 4096>>();
      client->read_pending = true;
      if (!client->writer.AsyncReadSome(boost::asio::buffer(*bytes),
// 2026-09-15: private transport-policy extraction; original lines:
//           [self = shared_from_this(), this, client, bytes](boost::system::error_code ec, size_t length) {
          [self = this->shared_from_this(), this, client, bytes](boost::system::error_code ec, size_t length) {
            std::lock_guard lock(mutex);
            client->read_pending = false;
            if (ec || !running || client->disconnected) { CloseLocked(client); CleanupLocked(); return; }
            if (!AppendBoundedBytes(client->receive, bytes->data(), length, kReceiveLimit)) {
              InvalidLocked(client); CleanupLocked(); return;
            }
            while (!client->disconnected && ProcessLocked(client)) {}
            CleanupLocked();
// 2026-09-14: a rejected peer drains one explicit rejection and cannot continue parsing.
//             if (!client->disconnected) Read(client);
            if (!client->disconnected && !client->rejecting) Read(client);
          })) {
        client->read_pending = false; CloseLocked(client);
      }
    }
    void AssignLocked(const std::shared_ptr<Session>& client) {
      std::array<bool, 22> used{};
      for (const auto& owner : clients) if (owner->slot) used[*owner->slot] = true;
      size_t slot = 0;
      while (slot < inputs.size() && used[slot]) ++slot;
      if (slot == inputs.size() || started || next_session == 0) { CloseLocked(client); return; }
      client->slot = static_cast<uint16_t>(slot);
      client->session_id = next_session++;
      // Preserve the existing token convention here; secure token issuance and
      // protocol capability negotiation remain a separate network contract.
      client->token = MakeSessionToken(*client->slot, config.seed, client->session_id);
      client->phase = Phase::AwaitReady;
      SendAssignmentLocked(client);
    }
    void SendAssignmentLocked(const std::shared_ptr<Session>& client) {
      std::array<uint8_t, 5> bytes;
      const auto length = PackSlotAssignment(&*client->slot, 1, bytes.data(), bytes.size());
      SendLocked(client, bytes.data(), length);
    }
    bool ReconnectLocked(const std::shared_ptr<Session>& client, session_token_t token) {
      if (token == 0 || client->slot || client->spectator) return InvalidLocked(client);
      std::shared_ptr<Session> owner;
      for (const auto& candidate : clients)
        if (candidate != client && candidate->slot && candidate->disconnected && candidate->token == token) {
          owner = candidate; break;
        }
      if (!owner) return InvalidLocked(client);
      client->slot = owner->slot; owner->slot.reset();
      client->token = std::exchange(owner->token, 0);
      client->session_id = owner->session_id;
      client->resume_pending = true;
      client->phase = Phase::SnapshotPending;
      SendAssignmentLocked(client);
      ++counters.reconnects;
      input_cv.notify_all();
      return !client->disconnected;
    }
    bool ProcessLocked(const std::shared_ptr<Session>& client) {
      auto& bytes = client->receive;
      if (bytes.empty() || client->rejecting) return false;
      // 2026-09-14: route fixed initial-loading records.
      // if (config.native_product && bytes[0] >= 80 && bytes[0] <= 87)
// 2026-09-15: route bounded cancellation controls through the authenticated recovery parser.
//       if (config.native_product && bytes[0] >= 80 && bytes[0] <= 90)
      if (config.native_product && bytes[0] >= 80 && bytes[0] <= 92)
        return ProcessRecoveryLocked(client);
      if (client->recovery && (client->phase == Phase::Identify ||
          bytes[0] == NativeMatchContract::kReady || bytes[0] == static_cast<uint8_t>(MessageType::Ready)))
        return InvalidLocked(client);
      const auto type = static_cast<MessageType>(bytes[0]);
      // 2026-09-13: product families and complete ready descriptors cannot fall through to legacy admission.
      // if (client->phase == Phase::Identify) {
      if(config.native_product && client->phase==Phase::Identify) {
        if(bytes[0]!=NativeMatchContract::kHello)return InvalidLocked(client);
        if(bytes.size()<NativeMatchContract::kHelloBytes)return false;
        if(!NativeMatchContract::IsHello({bytes.data(),NativeMatchContract::kHelloBytes}))return InvalidLocked(client);
        bytes.erase(bytes.begin(),bytes.begin()+NativeMatchContract::kHelloBytes);
        const auto descriptor=NativeMatchContract(config.seed,config.left_agents,config.right_agents).Packet();
        if(!SendLocked(client,descriptor.data(),descriptor.size()))return false;
        AssignLocked(client);return !client->disconnected;
      }
      if(config.native_product && bytes[0]==NativeMatchContract::kReady) {
        if(client->phase!=Phase::AwaitReady)return InvalidLocked(client);
        if(bytes.size()<NativeMatchContract::kSessionBytes)return false;
        NativeMatchContract contract;
        if(!NativeMatchContract::Decode({bytes.data(),32},NativeMatchContract::kReady,contract) ||
           contract!=NativeMatchContract(config.seed,config.left_agents,config.right_agents))return InvalidLocked(client);
        client->phase=Phase::Streaming;client->last_activity=std::chrono::steady_clock::now();
        bytes.erase(bytes.begin(),bytes.begin()+32);input_cv.notify_all();return true;
      }
      if(config.native_product && type==MessageType::Ready)return InvalidLocked(client);
      if (client->phase == Phase::Identify) {
        if (type == MessageType::Connect) {
          bytes.erase(bytes.begin()); AssignLocked(client); return !client->disconnected;
        }
        if (type == MessageType::SpectatorJoin) {
          client->spectator = true; client->phase = Phase::SnapshotPending;
          bytes.erase(bytes.begin()); input_cv.notify_all(); return true;
        }
        if (type == MessageType::ReconnectRequest) {
          if (bytes.size() < RECONNECT_REQUEST_BYTES) return false;
          session_token_t token;
          UnpackReconnectRequest(bytes.data(), bytes.size(), &token);
          bytes.erase(bytes.begin(), bytes.begin() + RECONNECT_REQUEST_BYTES);
          return ReconnectLocked(client, token);
        }
        return InvalidLocked(client);
      }
      if (type == MessageType::Ready) {
        if (client->phase != Phase::AwaitReady && client->phase != Phase::Streaming) return InvalidLocked(client);
        client->phase = Phase::Streaming; client->last_activity = std::chrono::steady_clock::now();
        bytes.erase(bytes.begin()); input_cv.notify_all(); return true;
      }
      if (type == MessageType::Heartbeat) {
        if (bytes.size() < HEARTBEAT_PACK_BYTES) return false;
        client->last_activity = std::chrono::steady_clock::now();
        SendLocked(client, bytes.data(), HEARTBEAT_PACK_BYTES);
        bytes.erase(bytes.begin(), bytes.begin() + HEARTBEAT_PACK_BYTES); return true;
      }
      if (type != MessageType::FrameInput || client->spectator ||
          client->phase != Phase::Streaming || !client->slot) return InvalidLocked(client);
      if (bytes.size() < 7) return false;
      uint16_t count; std::memcpy(&count, bytes.data() + 5, 2);
      if (count != 1) return InvalidLocked(client);
      const auto need = 7 + 2 + SLOT_INPUT_BYTES;
      if (bytes.size() < need) return false;
      frame_id_t fid; std::vector<std::pair<uint16_t, SlotInput>> entries;
      const auto consumed = UnpackClientFrameInput(bytes.data(), bytes.size(), &fid, &entries);
      if (!consumed || entries[0].first != *client->slot || !IsValidSlotInput(entries[0].second))
        return InvalidLocked(client);
      client->last_activity = std::chrono::steady_clock::now();
      if (client->recovery && !OwnsRecoveryLocked(client, client->last_activity))
        return InvalidLocked(client);
// 2026-09-13: retain valid once-published inputs during pacing and before future frame boundaries.
//       if (fid == frame && accepting_inputs) {
//         inputs[*client->slot] = entries[0].second; received.insert(*client->slot); input_cv.notify_all();
//       }
      const auto admission = pending_inputs.Receive(fid, entries);
      if (admission == InputAdmission::Invalid || admission == InputAdmission::Conflict)
        return InvalidLocked(client);
      if (admission == InputAdmission::Accepted) input_cv.notify_all();
      bytes.erase(bytes.begin(), bytes.begin() + consumed); return true;
    }

    bool StreamsLocked(const std::shared_ptr<Session>& client) const {
// 2026-09-14: exclude rejected recovery records while their final packet drains.
//       return !client->disconnected && (client->phase == Phase::Streaming || client->snapshot_sent);
      return !client->disconnected && !client->rejecting &&
             (client->phase == Phase::Streaming || client->snapshot_sent);
    }
    void BroadcastLocked(const uint8_t* bytes, size_t length) {
      for (auto& client : clients) if (StreamsLocked(client)) SendLocked(client, bytes, length);
    }
    void ReconcileBotsLocked() {
      for (auto& client : clients) {
        if (!client->slot) continue;
        const auto slot = *client->slot;
// 2026-09-14: rejected recovered sessions lose control on the same frame boundary.
//         const bool unavailable = client->disconnected || client->phase != Phase::Streaming;
        const bool unavailable = client->disconnected || client->rejecting || client->phase != Phase::Streaming;
        std::array<uint8_t, TAKEOVER_NOTIFY_BYTES> bytes;
        size_t length = 0;
        if (unavailable && !bots.IsBotControlled(slot)) {
          bots.Takeover(slot, slot < config.left_agents ? 0 : 1);
          length = PackTakeoverNotify(slot, frame, bytes.data(), bytes.size());
        } else if (!unavailable && bots.IsBotControlled(slot)) {
          bots.Handback(slot);
          length = PackHandbackNotify(slot, frame, bytes.data(), bytes.size());
          client->resume_pending = false;
        }
        if (length) BroadcastLocked(bytes.data(), length);
      }
    }
    bool HasSnapshotsLocked() const {
      return std::any_of(clients.begin(), clients.end(), [](const auto& client) {
        return !client->disconnected && client->phase == Phase::SnapshotPending;
      });
    }
    bool InitialReadyLocked() const {
      bool player = false;
      for (const auto& client : clients) {
        // 2026-09-14: offline loaders keep only their bounded opening reservation.
        if (client->disconnected && client->slot && client->loading_until &&
            std::chrono::steady_clock::now() < *client->loading_until &&
            (!client->reservation_until || std::chrono::steady_clock::now() < *client->reservation_until))
          return false;
// 2026-09-15: a released admission is no longer a participant in the opening barrier.
//         if (client->disconnected || client->spectator) continue;
        if (client->disconnected || client->spectator || client->phase == Phase::Cancelled) continue;
        if (!client->slot || client->phase != Phase::Streaming) return false;
        player = true;
      }
      return player;
    }
    void Snapshots(std::unique_lock<std::mutex>& lock) {
      std::vector<std::shared_ptr<Session>> pending;
      for (auto& client : clients)
// 2026-09-14: FNRC snapshots use bounded chunks; legacy snapshot encoding stays unchanged.
//         if (!client->disconnected && client->phase == Phase::SnapshotPending) pending.push_back(client);
        if (!client->recovery && !client->disconnected && client->phase == Phase::SnapshotPending) pending.push_back(client);
      if (pending.empty()) return;
      const auto next_frame = frame;
      lock.unlock();
      auto state = engine.save_state();
      const bool fits = RetainedBytes(state) <= limits.snapshot_bytes && !state.empty();
      std::vector<uint8_t> bytes;
      if (fits) {
        bytes.resize(STATE_SNAPSHOT_HEADER_BYTES + state.size());
        PackStateSnapshot(next_frame, state.data(), static_cast<uint32_t>(state.size()),
                          bytes.data(), bytes.size());
      }
      lock.lock();
      for (auto& client : pending) {
        if (client->disconnected || client->phase != Phase::SnapshotPending) continue;
        if (!fits) { ++counters.snapshot_rejections; CloseLocked(client); continue; }
        if (SendLocked(client, bytes.data(), bytes.size())) {
          client->phase = Phase::AwaitReady;
          client->snapshot_sent = true;
          ++counters.snapshots_sent;
        }
      }
      // Snapshot denotes state BEFORE next_frame. Subsequent authority is sent
      // even while awaiting Ready, keeping the stream contiguous during restore.
    }
    // 2026-09-14: FNRC admission/ownership lives under mutex; no GameEnv IO callback.
    bool OwnsRecoveryLocked(const std::shared_ptr<Session>& client,
                            NativeRecoveryCredentials::Time now) {
      return credentials && client->grant && client->slot &&
          *client->slot == client->grant->slot &&
          credentials->owns(*client->slot, client->grant->generation, now);
    }
    bool SendRecoveryLocked(const std::shared_ptr<Session>& client,
                            const NativeRecoveryPacket& packet) {
      const auto bytes = packet.view();
      return SendLocked(client, bytes.data(), bytes.size());
    }
    bool RejectRecoveryLocked(const std::shared_ptr<Session>& client,
                              NativeRecoveryReject reason, bool invalidate = false) {
      ++counters.invalid_messages;
      const auto now = std::chrono::steady_clock::now();
      if (invalidate && OwnsRecoveryLocked(client, now)) {
        pending_inputs.RemoveSlot(*client->slot);
        credentials->revoke(*client->slot, client->grant->generation, now);
        if (!started) {
          credentials->release_admission(*client->slot, client->grant->generation, now);
          client->slot.reset();
        }
      }
      SendRecoveryLocked(client, pack_recovery_rejected(reason));
      client->rejecting = true;
      client->recovery_sender.reset();
      input_cv.notify_all();
      return false;
    }
    bool SendRecoverySessionLocked(const std::shared_ptr<Session>& client, bool restoring) {
      NativeRecoverySession session;
      session.match = NativeMatchContract(config.seed, config.left_agents, config.right_agents);
      session.grant = *client->grant;
      session.restoring = restoring;
      session.loading = client->phase == Phase::Loading;
      return SendRecoveryLocked(client, pack_recovery_session(session));
    }
    // 2026-09-14: only the new hello requests resource-loading admission.
    // bool AssignRecoveryLocked(const std::shared_ptr<Session>& client) {
    bool AssignRecoveryLocked(const std::shared_ptr<Session>& client, bool loading = false) {
      if (started) return RejectRecoveryLocked(client, NativeRecoveryReject::Busy);
      std::array<bool, 22> used{};
      for (const auto& owner : clients) if (owner->slot) used[*owner->slot] = true;
      size_t slot = 0;
      while (slot < inputs.size() && used[slot]) ++slot;
      if (slot == inputs.size()) return RejectRecoveryLocked(client, NativeRecoveryReject::Busy);
      const auto grant = credentials->issue(static_cast<uint16_t>(slot), std::chrono::steady_clock::now());
      if (!grant) return RejectRecoveryLocked(client, NativeRecoveryReject::SnapshotUnavailable);
      client->recovery = true;
      client->grant = grant;
      client->slot = grant->slot;
      // 2026-09-14: LoadComplete is required before Ready.
      // client->phase = Phase::AwaitReady;
      client->phase = loading ? Phase::Loading : Phase::AwaitReady;
      if (loading) client->loading_until = std::chrono::steady_clock::now()+limits.loading_timeout;
      return SendRecoverySessionLocked(client, false);
    }
    bool ResumeRecoveryLocked(const std::shared_ptr<Session>& client, const NativeRecoveryGrant& request) {
      std::shared_ptr<Session> owner;
      for (const auto& candidate : clients)
        if (candidate != client && candidate->recovery && candidate->slot &&
            candidate->grant && *candidate->slot == request.slot) {
          owner = candidate;
          break;
        }
      if (!owner) return RejectRecoveryLocked(client, NativeRecoveryReject::Unauthorized);
      const auto now = std::chrono::steady_clock::now();
      const bool loading = !started && owner->loading_until && now < *owner->loading_until;
      if (!started && owner->loading_until && !loading)
        return RejectRecoveryLocked(client, NativeRecoveryReject::Unauthorized);
      const auto loading_until = owner->loading_until;
      const auto grant = credentials->begin(request.slot, request.match, request.secret, now);
      if (!grant) return RejectRecoveryLocked(client, NativeRecoveryReject::Unauthorized);
      // begin installs a fresh generation before an old socket can complete its close.
      CloseLocked(owner);
      pending_inputs.RemoveSlot(request.slot);
      client->recovery = true;
      client->grant = grant;
      client->slot = grant->slot;
      client->reservation_until = owner->reservation_until.value_or(now + limits.recovery_grace);
      owner->slot.reset();
      owner->grant.reset();
      // 2026-09-14: an unstarted loader resumes the original lease without a match snapshot.
      // client->resume_pending = true;
      // client->phase = Phase::SnapshotPending;
      client->resume_pending = !loading;
      client->loading_until = loading ? loading_until : std::nullopt;
      client->phase = loading ? Phase::Loading : Phase::SnapshotPending;
      ++counters.reconnects;
      input_cv.notify_all();
      // 2026-09-14: receipt of a rotated loading capability is distinct from Ready.
      // return SendRecoverySessionLocked(client, true);
      return SendRecoverySessionLocked(client, !loading);
    }
    static bool SameRecoveryReady(const NativeRecoveryReady& a, const NativeRecoveryReady& b) {
      return a.grant.slot == b.grant.slot && a.grant.generation == b.grant.generation &&
          native_secret_equal(a.grant.match, b.grant.match) &&
          native_secret_equal(a.grant.secret, b.grant.secret) &&
          a.next_frame == b.next_frame && a.state_hash == b.state_hash;
    }
    // 2026-09-15: release only the current authenticated pregame owner.
    // The receipt may fail to drain; release still stands, without a fresh grace lease.
    bool CancelLoadingLocked(const std::shared_ptr<Session>& client,
                             std::span<const uint8_t> packet) {
      const auto proof = decode_recovery_load_control(packet, NativeRecoveryKind::LoadCancel);
      const auto now = std::chrono::steady_clock::now();
      if (!proof || !OwnsRecoveryLocked(client, now) ||
          proof->slot != client->grant->slot ||
          proof->generation != client->grant->generation ||
          !native_secret_equal(proof->match, client->grant->match) ||
          !native_secret_equal(proof->secret, client->grant->secret))
        return RejectRecoveryLocked(client, NativeRecoveryReject::Unauthorized);
      if (started || !credentials->release_admission(proof->slot, proof->generation, now))
        return RejectRecoveryLocked(client, NativeRecoveryReject::InvalidState);
      const auto receipt = pack_recovery_load_control(NativeRecoveryKind::LoadCancelled, *proof);
      pending_inputs.RemoveSlot(proof->slot);
      client->slot.reset();
      client->grant.reset();
      client->ready_proof.reset();
      client->accepted_frame.reset();
      client->reservation_until.reset();
      client->loading_until.reset();
      client->recovery_sender.reset();
      client->resume_pending = false;
      client->phase = Phase::Cancelled;
      // Existing terminal-drain flag also prevents parsing coalesced late Ready packets.
      client->rejecting = true;
      ++counters.loading_cancellations;
      SendRecoveryLocked(client, receipt);
      input_cv.notify_all();
      return false;
    }
    bool ProcessRecoveryLocked(const std::shared_ptr<Session>& client) {
      const int count = native_recovery_wire::record_size(client->receive);
      if (count < 0) return InvalidLocked(client);
      if (!count) return false;
      const std::span<const uint8_t> packet(client->receive.data(), static_cast<size_t>(count));
      const auto kind = static_cast<NativeRecoveryKind>(packet[0]);
      bool accepted = false;

// 2026-09-15: handle release before other admission transitions, under the same server mutex.
//       if (client->phase == Phase::Identify && kind == NativeRecoveryKind::LoadHello) {
      if (kind == NativeRecoveryKind::LoadCancel)
        return CancelLoadingLocked(client, packet);
      if (client->phase == Phase::Identify && kind == NativeRecoveryKind::LoadHello) {
        if (!is_recovery_load_hello(packet))
          return RejectRecoveryLocked(client, NativeRecoveryReject::Incompatible);
        accepted = AssignRecoveryLocked(client,true);
      } else if (client->recovery &&
                 (kind == NativeRecoveryKind::LoadReceipt || kind == NativeRecoveryKind::LoadComplete)) {
        const auto proof=decode_recovery_load_control(packet,kind);
        const auto now=std::chrono::steady_clock::now();
        if (!proof || client->phase != Phase::Loading || !client->loading_until ||
            now >= *client->loading_until || !OwnsRecoveryLocked(client,now) ||
            proof->slot != client->grant->slot || proof->generation != client->grant->generation ||
            !native_secret_equal(proof->match,client->grant->match) ||
            !native_secret_equal(proof->secret,client->grant->secret) ||
            !credentials->commit(proof->slot,proof->generation,proof->secret,now))
          return RejectRecoveryLocked(client,NativeRecoveryReject::Unauthorized,true);
        // Receipt restores connectivity, never renews the absolute resource deadline.
        client->reservation_until.reset();client->last_activity=now;
        if (kind == NativeRecoveryKind::LoadComplete) {
          client->phase=Phase::AwaitReady;client->ready_since=now;
          client->loading_until.reset();
        }
        accepted=true;
      } else if (client->phase == Phase::Identify && kind == NativeRecoveryKind::Hello) {
        if (!is_recovery_hello(packet))
          return RejectRecoveryLocked(client, NativeRecoveryReject::Incompatible);
        accepted = AssignRecoveryLocked(client);
      } else if (client->phase == Phase::Identify && kind == NativeRecoveryKind::Resume) {
        const auto request = decode_recovery_resume(packet);
        if (!request) return RejectRecoveryLocked(client, NativeRecoveryReject::Unauthorized);
        accepted = ResumeRecoveryLocked(client, *request);
      } else if (client->recovery && kind == NativeRecoveryKind::Ready) {
        const auto proof = decode_recovery_ready(packet);
        const auto now = std::chrono::steady_clock::now();
        if (!proof || !OwnsRecoveryLocked(client, now) ||
            proof->grant.slot != client->grant->slot ||
            proof->grant.generation != client->grant->generation ||
            !native_secret_equal(proof->grant.match, client->grant->match) ||
            !native_secret_equal(proof->grant.secret, client->grant->secret))
          return RejectRecoveryLocked(client, NativeRecoveryReject::Unauthorized, true);
        if (client->accepted_frame) {
          if (!client->ready_proof || !SameRecoveryReady(*proof, *client->ready_proof))
            return RejectRecoveryLocked(client, NativeRecoveryReject::InvalidState, true);
          accepted = SendRecoveryLocked(client,
              pack_recovery_accepted(client->grant->generation, *client->accepted_frame));
        } else {
          if (client->phase != Phase::AwaitReady ||
              (client->ready_proof && !SameRecoveryReady(*proof, *client->ready_proof)))
            return RejectRecoveryLocked(client, NativeRecoveryReject::InvalidState, true);
          // Only queue the proof. The frame owner validates the actual state and commits.
          client->ready_proof = proof;
          client->last_activity = now;
          accepted = true;
          input_cv.notify_all();
        }
      } else return InvalidLocked(client);
      if (accepted) client->receive.erase(client->receive.begin(), client->receive.begin() + count);
      return accepted && !client->disconnected;
    }
    bool HasRecoveryReadyLocked() const {
      return std::any_of(clients.begin(), clients.end(), [](const auto& client) {
        return !client->disconnected && !client->rejecting && client->recovery &&
            client->ready_proof && !client->accepted_frame;
      });
    }
    void CommitRecoveryReadyLocked() {
      for (auto& client : clients) {
        if (client->disconnected || client->rejecting || !client->recovery ||
            !client->ready_proof || client->accepted_frame) continue;
        const auto& proof = *client->ready_proof;
        const auto now = std::chrono::steady_clock::now();
        bool matches = false;
        if (client->resume_pending) {
          matches = client->recovery_sender && client->recovery_sender->done() &&
              proof.next_frame == client->recovery_sender->metadata().next_frame &&
              proof.state_hash == client->recovery_sender->metadata().state_hash;
        } else {
          matches = !started && initial_hash && proof.next_frame == 0 &&
              proof.state_hash == *initial_hash;
        }
        if (!matches || frame == UINT32_MAX || !OwnsRecoveryLocked(client, now) ||
            !credentials->commit(proof.grant.slot, proof.grant.generation, proof.grant.secret, now)) {
          RejectRecoveryLocked(client, NativeRecoveryReject::InvalidState, true);
          continue;
        }
        client->phase = Phase::Streaming;
        client->loading_until.reset();
        client->accepted_frame = frame;
        client->reservation_until.reset();
        client->last_activity = now;
        SendRecoveryLocked(client, pack_recovery_accepted(proof.grant.generation, frame));
        // ReconcileBotsLocked follows this commit at this same frame boundary.
      }
    }

    void RecoverySnapshots(std::unique_lock<std::mutex>& lock) {
      std::vector<std::shared_ptr<Session>> pending;
      for (const auto& client : clients)
        if (client->recovery && !client->disconnected && !client->rejecting &&
            client->phase == Phase::SnapshotPending) pending.push_back(client);
      if (pending.empty()) return;
      const auto next_frame = frame;
      lock.unlock();
      const auto state = engine.save_state();
      const auto hash = engine.compute_hash();
      lock.lock();
      const bool fits = !state.empty() && RetainedBytes(state) <= limits.snapshot_bytes &&
          RetainedBytes(state) <= kNativeRecoverySnapshotBytes && next_frame != UINT32_MAX;
      for (auto& client : pending) {
        if (client->disconnected || client->rejecting || client->phase != Phase::SnapshotPending ||
            !OwnsRecoveryLocked(client, std::chrono::steady_clock::now())) continue;
        if (!fits) {
          ++counters.snapshot_rejections;
          RejectRecoveryLocked(client, NativeRecoveryReject::SnapshotUnavailable);
          continue;
        }
        try {
          client->recovery_sender = std::make_unique<NativeRecoverySender>(
              client->grant->generation, next_frame, hash, state);
          client->phase = Phase::AwaitReady;
        } catch (const std::exception&) {
          ++counters.snapshot_rejections;
          RejectRecoveryLocked(client, NativeRecoveryReject::SnapshotUnavailable);
        }
      }
    }
    void PumpRecoveryLocked() {
      for (auto& client : clients) {
        if (client->disconnected || client->rejecting || !client->recovery_sender) continue;
        const auto& metadata = client->recovery_sender->metadata();
        if (client->phase != Phase::Streaming &&
            (frame < metadata.next_frame || frame - metadata.next_frame >= kMaxBufferedAuthorityFrames)) {
          ++counters.snapshot_rejections;
          RejectRecoveryLocked(client, NativeRecoveryReject::SnapshotUnavailable);
          continue;
        }
        auto sender = std::move(client->recovery_sender);
        sender->pump([&](std::span<const uint8_t> packet) {
          // The bounded writer can drain concurrently, but only this locked owner enqueues.
          // Reserve room for all bot notices plus authority/hash/heartbeat.
          const size_t reserve_messages = inputs.size() + 4;
          constexpr size_t kReserveBytes = 4096;
          const auto messages = client->writer.queued_messages();
          const auto bytes = client->writer.queued_bytes();
          if (limits.send.message_limit <= reserve_messages ||
              messages >= limits.send.message_limit - reserve_messages ||
              limits.send.byte_limit <= kReserveBytes ||
              packet.size() > limits.send.byte_limit - kReserveBytes ||
              bytes > limits.send.byte_limit - kReserveBytes - packet.size()) return false;
          if (!client->writer.TrySend(packet.data(), packet.size())) {
            if (client->writer.status() != StreamStatus::Capacity) CloseLocked(client);
            return false;
          }
          if (packet[0] == static_cast<uint8_t>(NativeRecoveryKind::Snapshot)) {
            client->snapshot_sent = true;
            ++counters.snapshots_sent;
            for (auto slot : bots.GetBotSlots()) {
              std::array<uint8_t, TAKEOVER_NOTIFY_BYTES> notice{};
              const auto length = PackTakeoverNotify(slot, metadata.next_frame, notice.data(), notice.size());
              if (!SendLocked(client, notice.data(), length)) return false;
            }
          }
          return true;
        });
        if (!client->disconnected && !client->rejecting) client->recovery_sender = std::move(sender);
      }
    }

    void Run() {
      bool expected = false;
      if (!loop_running.compare_exchange_strong(expected, true))
        throw std::logic_error("integrated TCP frame loop already runs");
      struct Reset { std::atomic<bool>& value; ~Reset() { value = false; } } reset{loop_running};
// 2026-09-14: only the frame owner computes initial proof and commits admission; pregame chunks make bounded progress.
//       std::unique_lock lock(mutex);
//       while (running && !started) {
//         Snapshots(lock);
//         if (InitialReadyLocked()) { started = true; break; }
//         input_cv.wait(lock, [this] { return !running || HasSnapshotsLocked() || InitialReadyLocked(); });
//       }
      std::unique_lock lock(mutex);
      if (credentials) {
        lock.unlock();
        const auto hash = engine.compute_hash();
        lock.lock();
        initial_hash = hash;
      }
      while (running && !started) {
        RecoverySnapshots(lock);
        PumpRecoveryLocked();
        CommitRecoveryReadyLocked();
        Snapshots(lock);
        if (InitialReadyLocked()) {
          started = true;
          if (credentials) credentials->seal_admissions();
          break;
        }
        input_cv.wait_for(lock, std::chrono::milliseconds(25), [this] {
          return !running || HasSnapshotsLocked() || HasRecoveryReadyLocked() || InitialReadyLocked();
        });
      }
      // 2026-09-13: one absolute authority grid starts after the Ready barrier.
      // while (running) {
      //   Snapshots(lock);
      NativeFrameDeadline product_deadline(std::chrono::steady_clock::now());
// 2026-09-14: restore proofs hand control back at the next frame boundary.
//       while (running) {
//         Snapshots(lock);
      while (running) {
        RecoverySnapshots(lock);
        PumpRecoveryLocked();
        CommitRecoveryReadyLocked();
        Snapshots(lock);
        if (!running) break;
        ReconcileBotsLocked();
        const auto bot_slots = bots.GetBotSlots();
        BotGameSnapshot observation;
        if (!bot_slots.empty()) {
          lock.unlock();
          observation = observe();
          if (observation.num_slots != static_cast<int>(inputs.size()) ||
              observation.player_positions.size() != inputs.size() * 2 ||
              (observation.unavailable_slots >> inputs.size()) != 0 ||
              !std::isfinite(observation.ball_x) || !std::isfinite(observation.ball_y) ||
              !std::all_of(observation.player_positions.begin(), observation.player_positions.end(),
                           [](float value) { return std::isfinite(value); }))
            throw std::runtime_error("invalid bot observation at TCP frame boundary");
          lock.lock();
        }
// 2026-09-13: future admissions survive the start of their frame.
//         inputs.assign(inputs.size(), SlotInput::Default()); received.clear(); accepting_inputs = true;
        accepting_inputs = true;
        // 2026-09-13: seal product frames on fixed deadlines, without adding input wait to sleep.
        // input_cv.wait_for(lock, limits.input_timeout, [this] {
        if(config.native_product)
          input_cv.wait_until(lock,product_deadline.deadline(),[this]{return !running;});
        else input_cv.wait_for(lock, limits.input_timeout, [this] {
          if (!running) return true;
          for (const auto& client : clients)
            if (!client->disconnected && client->slot && client->phase == Phase::Streaming &&
                !bots.IsBotControlled(*client->slot) && !pending_inputs.Has(*client->slot)) return false;
          return true;
        });
        accepting_inputs = false;
        if (!running) break;
// 2026-09-13: seal the authority frame before engine stepping; absent slots remain neutral.
//         for (auto slot : bot_slots) inputs[slot] = bots.GenerateInput(slot, observation);
        pending_inputs.Consume(inputs);
        for (auto slot : bot_slots) inputs[slot] = bots.GenerateInput(slot, observation);
        auto frozen = inputs;
        const auto current_frame = frame;
        lock.unlock();
        engine.step_frame(frozen);
        const bool hash_due = current_frame % STATE_HASH_INTERVAL_K == 0;
        const auto hash = hash_due ? engine.compute_hash() : 0;
        lock.lock();
        std::array<uint8_t, 7 + 22 * SLOT_INPUT_BYTES> bytes;
        auto length = PackAuthoritativeFrame(current_frame, frozen.data(),
            static_cast<uint16_t>(frozen.size()), bytes.data(), bytes.size());
        BroadcastLocked(bytes.data(), length);
        if (hash_due) {
          length = PackStateHash(current_frame, hash, bytes.data(), bytes.size());
          BroadcastLocked(bytes.data(), length);
        }
        ++frame;
        CleanupLocked();
        // 2026-09-13: slow work skips wall opportunities, never frame IDs or already admitted input.
        // input_cv.wait_for(lock, std::chrono::milliseconds(1000 / config.frame_rate_hz),
        //                   [this] { return !running; });
        if(config.native_product)product_deadline.Advance(std::chrono::steady_clock::now());
        else input_cv.wait_for(lock, std::chrono::milliseconds(1000 / config.frame_rate_hz),
                              [this] { return !running; });
      }
    }
    EngineTCPServerStats Stats() const {
      std::lock_guard lock(mutex);
      auto result = counters;
      result.connections = clients.size();
      for (const auto& client : clients) {
        result.active_connections += !client->disconnected;
        result.pending_handshakes += !client->disconnected && client->phase != Phase::Streaming;
        result.receive_capacity += client->receive.capacity();
        result.queued_send_bytes += client->writer.queued_bytes();
        result.queued_send_messages += client->writer.queued_messages();
      }
      result.next_frame = frame; result.accepting_inputs = accepting_inputs;
      result.bot_slots = bots.bot_count();
      return result;
    }
    boost::asio::io_context& io;
// 2026-09-15: private transport-policy extraction; original lines:
//     tcp::acceptor acceptor;
    Acceptor acceptor;
    boost::asio::steady_timer timer;
    const MultiplayerConfig config;
    const EngineCallbacks engine;
    const std::function<BotGameSnapshot()> observe;
    const EngineTCPServerLimits limits;
    mutable std::mutex mutex;
    std::condition_variable input_cv;
    std::vector<std::shared_ptr<Session>> clients;
    std::vector<SlotInput> inputs;
// 2026-09-13: bounded frame-indexed readiness replaces a per-frame receipt set.
//     std::set<uint16_t> received;
    ServerInputWindow pending_inputs;
    BotTakeoverManager bots;
    uint32_t next_session = 1;
    frame_id_t frame = 0;
    bool started = false, accepting_inputs = false;
    std::atomic<bool> running{true}, loop_running{false};
    EngineTCPServerStats counters;
    std::unique_ptr<NativeRecoveryCredentials> credentials;
    std::optional<uint64_t> initial_hash;
  };
 public:
// 2026-09-15: private transport-policy extraction; original lines:
  BasicEngineSessionServer() = delete;
  static constexpr size_t kReceiveLimit = 8192;
// 2026-09-15: private transport-policy extraction; original lines:
//   EngineTCPServer(boost::asio::io_context& io, unsigned short port, MultiplayerConfig config,
  BasicEngineSessionServer(boost::asio::io_context& io, unsigned short port, MultiplayerConfig config,
                  EngineCallbacks engine, std::function<BotGameSnapshot()> observe,
                  EngineTCPServerLimits limits = {})
      : impl_(std::make_shared<Impl>(io, port, std::move(config), std::move(engine),
                                     std::move(observe), std::move(limits))) { impl_->Start(); }
// 2026-09-15: private transport-policy extraction; original lines:
//   ~EngineTCPServer() { stop(); }
//   EngineTCPServer(const EngineTCPServer&) = delete;
//   EngineTCPServer& operator=(const EngineTCPServer&) = delete;
//   EngineTCPServer(EngineTCPServer&&) = delete;
//   EngineTCPServer& operator=(EngineTCPServer&&) = delete;
  ~BasicEngineSessionServer() { stop(); }
  BasicEngineSessionServer(const BasicEngineSessionServer&) = delete;
  BasicEngineSessionServer& operator=(const BasicEngineSessionServer&) = delete;
  BasicEngineSessionServer(BasicEngineSessionServer&&) = delete;
  BasicEngineSessionServer& operator=(BasicEngineSessionServer&&) = delete;
  void stop() { impl_->Stop(); }
  void run_frame_loop() {
    auto lifetime = impl_;
    try { lifetime->Run(); }
    catch (...) { lifetime->Stop(); throw; }
  }
  unsigned short port() const { return impl_->acceptor.local_endpoint().port(); }
  EngineTCPServerStats stats() const { return impl_->Stats(); }
 private:
  std::shared_ptr<Impl> impl_;
};
// 2026-09-15: private transport-policy extraction; original lines:
using EngineTCPServer = BasicEngineSessionServer<NativeTCPTransport>;
}  // namespace frame_sync
#endif
