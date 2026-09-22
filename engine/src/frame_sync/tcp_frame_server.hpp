// Copyright 2026 Google LLC & Contributors
// 2026-09-09: bounded production TCP authority server, independent of GameEnv.
#ifndef GFOOTBALL_FRAME_SYNC_TCP_FRAME_SERVER_HPP
#define GFOOTBALL_FRAME_SYNC_TCP_FRAME_SERVER_HPP
#include "frame_sync/bounded_tcp_writer.hpp"
#include "frame_sync/protocol_io.hpp"
#include <array>
#include <atomic>
#include <condition_variable>
#include <set>

namespace frame_sync {
struct TCPFrameServerOptions {
  StreamBudget send{256, 2 * 1024 * 1024};
  std::chrono::milliseconds write_timeout{5000};
  std::chrono::milliseconds ready_timeout{30000};
  std::chrono::milliseconds input_timeout{200};
  std::chrono::milliseconds frame_period{100};
  int socket_send_bytes = 64 * 1024;
  void Validate() const {
    const StreamBudget validated(send.message_limit, send.byte_limit);
    if (write_timeout.count() < 1 || write_timeout > std::chrono::seconds(30) ||
        ready_timeout.count() < 1 || ready_timeout > std::chrono::minutes(5) ||
        input_timeout.count() < 1 || input_timeout > std::chrono::seconds(1) ||
        frame_period.count() < 1 || frame_period > std::chrono::seconds(1) ||
        socket_send_bytes < 1024 || socket_send_bytes > 1024 * 1024)
      throw std::invalid_argument("invalid TCP frame server limits");
  }
};
struct TCPFrameServerStats {
  size_t connections = 0;
  size_t active_connections = 0;
  size_t receive_capacity = 0;
  size_t queued_send_bytes = 0;
  size_t queued_send_messages = 0;
  size_t rejected_connections = 0;
  size_t invalid_messages = 0;
  size_t overloaded_connections = 0;
  size_t write_timeouts = 0;
  frame_id_t next_frame = 0;
  bool accepting_inputs = false;
};
class FrameSyncServer {
 private:
  using tcp = boost::asio::ip::tcp;
  struct Session {
    std::shared_ptr<tcp::socket> socket;
    BoundedTCPWriter writer;
    const uint16_t slot;
    bool ready = false;
    bool disconnected = false;
    bool read_pending = false;
    std::vector<uint8_t> receive;
    const std::chrono::steady_clock::time_point connected_at = std::chrono::steady_clock::now();
    Session(tcp::socket socket, uint16_t slot, const TCPFrameServerOptions& options)
        : socket(std::make_shared<tcp::socket>(std::move(socket))),
          writer(this->socket, options.send, options.write_timeout), slot(slot) {}
    ~Session() = default;
    Session(const Session&) = delete;
    Session& operator=(const Session&) = delete;
    Session(Session&&) = delete;
    Session& operator=(Session&&) = delete;
  };
  struct Impl : std::enable_shared_from_this<Impl> {
    Impl(boost::asio::io_context& io, unsigned short port, uint16_t left, uint16_t right,
         uint32_t seed, const TCPFrameServerOptions& options)
        : io(io), acceptor(io, {tcp::v4(), port}), timer(io), options(options),
          left(left), right(right), seed(seed), slots(size_t(left) + right) {
      options.Validate();
      if (left > 11 || right > 11 || slots == 0)
        throw std::invalid_argument("TCP server needs 1..22 slots and at most 11 per team");
      inputs.assign(slots, SlotInput::Default());
    }
    void Start() { Accept(); Maintain(); }
    void Stop() {
      if (!running.exchange(false)) return;
      {
        std::lock_guard lock(mutex);
        for (auto& client : clients) CloseLocked(client);
        input_cv.notify_all();
      }
      boost::asio::post(io, [self = shared_from_this(), this] {
        std::lock_guard lock(mutex);
        boost::system::error_code ec;
        acceptor.close(ec); timer.cancel(); CleanupLocked();
      });
    }
    bool ReadyLocked() const {
      bool connected = false;
      for (const auto& client : clients) {
        if (client->disconnected) continue;
        connected = true;
        if (!client->ready) return false;
      }
      return connected;
    }
    bool AllReady() const { std::lock_guard lock(mutex); return ReadyLocked(); }
    void Run() {
      bool expected = false;
      if (!loop_running.compare_exchange_strong(expected, true))
        throw std::logic_error("TCP frame loop is already running");
      struct Reset { std::atomic<bool>& value; ~Reset() { value = false; } } reset{loop_running};
      std::unique_lock lock(mutex);
      input_cv.wait(lock, [this] { return !running || ReadyLocked(); });
      if (!running) return;
      started = true;
      while (running) {
        inputs.assign(slots, SlotInput::Default()); received.clear(); accepting_inputs = true;
        input_cv.wait_for(lock, options.input_timeout, [this] {
          if (!running) return true;
          for (const auto& client : clients)
            if (!client->disconnected && !received.contains(client->slot)) return false;
          return true;
        });
        accepting_inputs = false;
        if (!running) break;
        std::array<uint8_t, 7 + 22 * SLOT_INPUT_BYTES> bytes;
        // The shipped clients do not negotiate delta decoding. Keep full frames.
        const auto length = PackAuthoritativeFrame(frame, inputs.data(),
            static_cast<uint16_t>(slots), bytes.data(), bytes.size());
        for (auto& client : clients)
          if (!client->disconnected && client->ready) SendLocked(client, bytes.data(), length);
        ++frame;
        CleanupLocked();
        input_cv.wait_for(lock, options.frame_period, [this] { return !running; });
      }
    }
    void CloseLocked(const std::shared_ptr<Session>& client) {
      if (client->disconnected) return;
      client->disconnected = true;
      if (client->writer.status() == StreamStatus::WriteTimeout) ++write_timeouts;
      client->writer.Close();
      received.erase(client->slot);
      input_cv.notify_all();
    }
    void CleanupLocked() {
      for (auto& client : clients)
        if (client->disconnected) std::vector<uint8_t>().swap(client->receive);
      // During a match, slots stay reserved: a fresh initial-state client cannot
      // safely join without a negotiated state bootstrap. Closed records <=22.
      if (!started) std::erase_if(clients, [](const auto& client) {
        return client->disconnected && !client->read_pending && client->writer.queued_messages() == 0;
      });
    }
    void SendLocked(const std::shared_ptr<Session>& client, const uint8_t* bytes, size_t length) {
      if (!client->disconnected && !client->writer.TrySend(bytes, length)) {
        if (client->writer.status() == StreamStatus::Capacity) ++overloaded_connections;
        CloseLocked(client);
      }
    }
    void Accept() {
      acceptor.async_accept([self = shared_from_this(), this](boost::system::error_code ec, tcp::socket socket) {
        std::lock_guard lock(mutex);
        if (ec || !running) return;
        CleanupLocked();
        if (started || clients.size() >= slots) {
          ++rejected_connections; socket.close(ec); Accept(); return;
        }
        std::array<bool, 22> used{};
        for (const auto& client : clients) used[client->slot] = true;
        uint16_t slot = 0;
        while (slot < slots && used[slot]) ++slot;
        socket.set_option(boost::asio::socket_base::send_buffer_size(options.socket_send_bytes), ec);
        if (ec) { ++rejected_connections; socket.close(ec); Accept(); return; }
        auto client = std::make_shared<Session>(std::move(socket), slot, options);
        clients.push_back(client);
        std::array<uint8_t, 32> bytes;
        auto length = PackSessionStart(seed, left, right, bytes.data(), bytes.size());
        SendLocked(client, bytes.data(), length);
        length = PackSlotAssignment(&client->slot, 1, bytes.data(), bytes.size());
        SendLocked(client, bytes.data(), length);
        if (!client->disconnected) Read(client);
        Accept();
      });
    }
    void Maintain() {
      timer.expires_after(std::chrono::milliseconds(25));
      timer.async_wait([self = shared_from_this(), this](boost::system::error_code ec) {
        std::lock_guard lock(mutex);
        if (ec || !running) return;
        const auto now = std::chrono::steady_clock::now();
        for (auto& client : clients) {
          if (client->disconnected) continue;
          if (client->writer.is_closed() ||
              (!client->ready && now - client->connected_at >= options.ready_timeout)) CloseLocked(client);
        }
        CleanupLocked(); Maintain();
      });
    }
    void Read(const std::shared_ptr<Session>& client) {
      auto bytes = std::make_shared<std::array<uint8_t, 4096>>();
      client->read_pending = true;
      if (!client->writer.AsyncReadSome(boost::asio::buffer(*bytes),
          [self = shared_from_this(), this, client, bytes](boost::system::error_code ec, size_t length) {
            std::lock_guard lock(mutex);
            client->read_pending = false;
            if (ec || !running || client->disconnected) { CloseLocked(client); CleanupLocked(); return; }
            if (!AppendBoundedBytes(client->receive, bytes->data(), length, kReceiveLimit)) {
              ++invalid_messages; CloseLocked(client); CleanupLocked(); return;
            }
            while (!client->disconnected && ProcessLocked(client)) {}
            CleanupLocked();
            if (!client->disconnected) Read(client);
          })) {
        client->read_pending = false; CloseLocked(client);
      }
    }
    bool InvalidLocked(const std::shared_ptr<Session>& client) {
      ++invalid_messages; CloseLocked(client); return false;
    }
    bool ProcessLocked(const std::shared_ptr<Session>& client) {
      auto& bytes = client->receive;
      if (bytes.empty()) return false;
      const auto type = static_cast<MessageType>(bytes[0]);
      if (type == MessageType::Ready || type == MessageType::Connect) {
        if (type == MessageType::Ready) { client->ready = true; input_cv.notify_all(); }
        bytes.erase(bytes.begin()); return true;
      }
      if (type == MessageType::Heartbeat) {
        if (bytes.size() < HEARTBEAT_PACK_BYTES) return false;
        bytes.erase(bytes.begin(), bytes.begin() + HEARTBEAT_PACK_BYTES); return true;
      }
      if (type != MessageType::FrameInput) return InvalidLocked(client);
      if (bytes.size() < 7) return false;
      uint16_t count; std::memcpy(&count, bytes.data() + 5, 2);
      if (count != 1 || !client->ready) return InvalidLocked(client);
      const auto need = 7 + count * (2 + SLOT_INPUT_BYTES);
      if (bytes.size() < need) return false;
      frame_id_t fid;
      std::vector<std::pair<uint16_t, SlotInput>> entries;
      const auto consumed = UnpackClientFrameInput(bytes.data(), bytes.size(), &fid, &entries);
      if (!consumed || entries[0].first != client->slot || !IsValidSlotInput(entries[0].second))
        return InvalidLocked(client);
      if (fid == frame && accepting_inputs) {
        inputs[client->slot] = entries[0].second; received.insert(client->slot); input_cv.notify_all();
      }
      bytes.erase(bytes.begin(), bytes.begin() + consumed); return true;
    }
    TCPFrameServerStats Stats() const {
      std::lock_guard lock(mutex);
      TCPFrameServerStats result;
      result.connections = clients.size();
      for (const auto& client : clients) {
        result.active_connections += !client->disconnected;
        result.receive_capacity += client->receive.capacity();
        result.queued_send_bytes += client->writer.queued_bytes();
        result.queued_send_messages += client->writer.queued_messages();
      }
      result.rejected_connections = rejected_connections;
      result.invalid_messages = invalid_messages;
      result.overloaded_connections = overloaded_connections;
      result.write_timeouts = write_timeouts;
      result.next_frame = frame; result.accepting_inputs = accepting_inputs;
      return result;
    }
    boost::asio::io_context& io;
    tcp::acceptor acceptor;
    boost::asio::steady_timer timer;
    const TCPFrameServerOptions options;
    const uint16_t left, right;
    const uint32_t seed;
    const size_t slots;
    mutable std::mutex mutex;
    std::condition_variable input_cv;
    std::vector<std::shared_ptr<Session>> clients;
    std::vector<SlotInput> inputs;
    std::set<uint16_t> received;
    frame_id_t frame = 0;
    bool accepting_inputs = false;
    bool started = false;
    std::atomic<bool> running{true}, loop_running{false};
    size_t rejected_connections = 0, invalid_messages = 0, overloaded_connections = 0, write_timeouts = 0;
  };
 public:
  static constexpr size_t kReceiveLimit = 8192;
  FrameSyncServer(boost::asio::io_context& io, unsigned short port, uint16_t left,
                  uint16_t right, uint32_t seed, TCPFrameServerOptions options = {})
      : impl_(std::make_shared<Impl>(io, port, left, right, seed, options)) { impl_->Start(); }
  ~FrameSyncServer() { stop(); }
  FrameSyncServer(const FrameSyncServer&) = delete;
  FrameSyncServer& operator=(const FrameSyncServer&) = delete;
  FrameSyncServer(FrameSyncServer&&) = delete;
  FrameSyncServer& operator=(FrameSyncServer&&) = delete;
  bool all_ready() const { return impl_->AllReady(); }
  void run_frame_loop() { auto lifetime = impl_; lifetime->Run(); }
  void stop() { impl_->Stop(); }
  unsigned short port() const { return impl_->acceptor.local_endpoint().port(); }
  TCPFrameServerStats stats() const { return impl_->Stats(); }
 private:
  std::shared_ptr<Impl> impl_;
};
}  // namespace frame_sync
#endif
