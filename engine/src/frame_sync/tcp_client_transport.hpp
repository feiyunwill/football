// Copyright 2026 Google LLC & Contributors
// 2026-09-09: one bounded TCP stream parser for native player clients.
#ifndef GFOOTBALL_FRAME_SYNC_TCP_CLIENT_TRANSPORT_HPP
#define GFOOTBALL_FRAME_SYNC_TCP_CLIENT_TRANSPORT_HPP
#include "frame_sync/bounded_tcp_writer.hpp"
#include "frame_sync/protocol_io.hpp"
#include "frame_sync/client_state.hpp"
#include <array>
#include <chrono>
#include <deque>
#include <map>
#include <optional>
#include <thread>

namespace frame_sync {
struct TCPClientLimits {
  StreamBudget send{256, 2 * 1024 * 1024};
  size_t authority_frames = 1024;
  size_t authority_bytes = 512 * 1024;
  size_t hashes = 1024;
  size_t snapshot_bytes = 1024 * 1024;
  std::chrono::milliseconds handshake_timeout{5000}, write_timeout{5000}, idle_timeout{3000};
  void Validate() const {
    StreamBudget checked(send.message_limit, send.byte_limit);
    if (!authority_frames || authority_frames > kMaxBufferedAuthorityFrames ||
        !authority_bytes || authority_bytes > kMaxBufferedInputBytes || !hashes || hashes > 1024 ||
        !snapshot_bytes || snapshot_bytes > 8 * 1024 * 1024)
      throw std::invalid_argument("Invalid TCP client capacity");
    for (auto timeout : {handshake_timeout, write_timeout, idle_timeout})
      if (timeout < std::chrono::milliseconds(1) || timeout > std::chrono::seconds(30))
        throw std::invalid_argument("Invalid TCP client timeout");
  }
};
enum class TCPClientStatus {
  Closed, AwaitSession, AwaitSlots, AwaitSnapshot, AwaitReady, Streaming,
  ResolveFailed, ConnectFailed, HandshakeTimeout, IdleTimeout, IoError,
  InvalidMessage, Capacity, InvalidInput, InvalidState, EngineFailure, HashMismatch
};
struct TCPSessionInfo {
  uint32_t seed = 0;
  uint16_t left = 0, right = 0;
  std::vector<uint16_t> slots;
  bool operator==(const TCPSessionInfo&) const = default;
};
struct TCPAuthority {
  frame_id_t frame;
  std::vector<SlotInput> inputs;
  double arrival_ms;
};
struct TCPBootstrap { frame_id_t next_frame; StateBlob state; };
struct TCPClientStats {
  size_t authority_frames = 0, authority_bytes = 0, hashes = 0, receive_capacity = 0;
  size_t snapshot_capacity = 0, send_messages = 0, send_bytes = 0, verified_hashes = 0;
};

// Single-owner API. Only this object's Poll/Connect dispatch its private IO.
// Name resolution and TCP establishment remain synchronous; handshake/read/write
// budgets below do not claim a deadline for the operating system resolver.
class TCPClientTransport {
  using tcp = boost::asio::ip::tcp;
  using Clock = std::chrono::steady_clock;
 public:
  TCPClientTransport(std::string host, unsigned short port, TCPClientLimits limits = TCPClientLimits{})
      : host_(std::move(host)), port_(port), limits_(limits) {
    limits_.Validate();
    if (host_.empty() || host_.size() > 253 || host_.find('\0') != std::string::npos || !port_)
      throw std::invalid_argument("Invalid TCP endpoint");
  }
  ~TCPClientTransport() { Close(); }
  TCPClientTransport(const TCPClientTransport&) = delete;
  TCPClientTransport& operator=(const TCPClientTransport&) = delete;
  TCPClientTransport(TCPClientTransport&&) = delete;
  TCPClientTransport& operator=(TCPClientTransport&&) = delete;

  bool Connect(session_token_t resume_token = 0) {
    if (polling_) return false;
    Close(); writer_.reset(); socket_.reset();
    // Complete old cancellations before allocating another stream, so repeated
    // attempts cannot accumulate hidden Asio buffers or access a new session.
    io_.restart(); io_.run();
    resuming_ = resume_token != 0; resume_token_ = resume_token;
    if (resuming_ && !accepted_) return Fail(TCPClientStatus::InvalidState);
    session_ = TCPSessionInfo{}; verified_hashes_ = 0; bots_.fill(false);
    socket_ = std::make_shared<tcp::socket>(io_);
    boost::system::error_code ec;
    tcp::resolver resolver(io_);
    auto endpoints = resolver.resolve(host_, std::to_string(port_), ec);
    if (ec) return Fail(TCPClientStatus::ResolveFailed);
    boost::asio::connect(*socket_, endpoints, ec);
    if (ec) return Fail(TCPClientStatus::ConnectFailed);
    writer_ = std::make_unique<BoundedTCPWriter>(socket_, limits_.send, limits_.write_timeout);
    status_ = TCPClientStatus::AwaitSession;
    const auto deadline = Clock::now() + limits_.handshake_timeout;
    last_activity_ = Clock::now();
    Read();
    while (HandshakePending()) {
      Poll();
      if (HandshakePending() && Clock::now() >= deadline) return Fail(TCPClientStatus::HandshakeTimeout);
      if (HandshakePending()) std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    return status_ == TCPClientStatus::AwaitReady;
  }
  bool Ready() {
    if (status_ != TCPClientStatus::AwaitReady || bootstrap_) return Fail(TCPClientStatus::InvalidState);
    const uint8_t byte = std::to_underlying(MessageType::Ready);
    if (!Send(&byte, 1)) return false;
    status_ = TCPClientStatus::Streaming; accepted_ = session_; last_activity_ = Clock::now();
    return true;
  }
  void Close() {
    ++generation_;
    if (writer_) writer_->Close();
    else if (socket_) { boost::system::error_code ignored; socket_->close(ignored); }
    ClearPayloads(); status_ = TCPClientStatus::Closed;
  }
  bool Fail(TCPClientStatus status) { Close(); status_ = status; return false; }
  void Poll() {
    if (polling_) return;
    polling_ = true;
    struct Reset { bool& flag; ~Reset() { flag = false; } } reset{polling_};
    io_.restart();
    const auto deadline = Clock::now() + std::chrono::milliseconds(2);
    for (size_t count = 0; count < 64 && io_.poll_one(); ++count)
      if (Clock::now() >= deadline) break;
    if (Live() && writer_ && writer_->is_closed()) Fail(TCPClientStatus::IoError);
    if (status_ == TCPClientStatus::Streaming && Clock::now() - last_activity_ >= limits_.idle_timeout)
      Fail(TCPClientStatus::IdleTimeout);
  }
  bool SendInput(frame_id_t frame, const uint16_t* slots, const SlotInput* inputs, uint16_t count) {
    if (status_ != TCPClientStatus::Streaming) return false;
    if (!count || count != session_.slots.size() || !slots || !inputs)
      return Fail(TCPClientStatus::InvalidInput);
    for (size_t i = 0; i < count; ++i)
      if (slots[i] != session_.slots[i] || !IsValidSlotInput(inputs[i]))
        return Fail(TCPClientStatus::InvalidInput);
    std::array<uint8_t, 7 + 22 * (2 + SLOT_INPUT_BYTES)> bytes;
    const auto used = PackClientFrameInput(frame, slots, inputs, count, bytes.data(), bytes.size());
    return used && Send(bytes.data(), used);
  }
  bool Heartbeat(frame_id_t frame, uint32_t timestamp) {
    if (status_ != TCPClientStatus::Streaming) return false;
    std::array<uint8_t, HEARTBEAT_PACK_BYTES> bytes;
    const auto used = PackHeartbeat(frame, timestamp, bytes.data(), bytes.size());
    return used && Send(bytes.data(), used);
  }
  bool PopAuthority(TCPAuthority& output) {
    if (authority_.empty()) return false;
    authority_bytes_ -= RetainedBytes(authority_.front().inputs);
    output = std::move(authority_.front()); authority_.pop_front(); return true;
  }
  bool PopHash(frame_id_t& frame, uint64_t& hash) {
    if (hashes_.empty()) return false;
    frame = hashes_.begin()->first; hash = hashes_.begin()->second;
    hashes_.erase(hashes_.begin()); return true;
  }
  template<class Verify> bool VerifyHashes(Verify verify) {
    for (auto it = hashes_.begin(); it != hashes_.end();) {
      const auto result = verify(it->first, it->second);
      if (!result) { ++it; continue; }
      if (!*result) return Fail(TCPClientStatus::HashMismatch);
      ++verified_hashes_; it = hashes_.erase(it);
    }
    return true;
  }
  std::optional<TCPBootstrap> TakeBootstrap() { auto result = std::move(bootstrap_); bootstrap_.reset(); return result; }
  bool connected() const { return status_ == TCPClientStatus::Streaming; }
  TCPClientStatus status() const { return status_; }
  const TCPSessionInfo& session() const { return session_; }
  const std::array<bool, 22>& bots() const { return bots_; }
  TCPClientStats stats() const {
    return {authority_.size(), authority_bytes_, hashes_.size(), receive_.capacity(),
            bootstrap_ ? RetainedBytes(bootstrap_->state) : 0,
            writer_ ? writer_->queued_messages() : 0, writer_ ? writer_->queued_bytes() : 0, verified_hashes_};
  }
 private:
  bool HandshakePending() const {
    return status_ == TCPClientStatus::AwaitSession || status_ == TCPClientStatus::AwaitSlots ||
           status_ == TCPClientStatus::AwaitSnapshot;
  }
  bool Live() const { return HandshakePending() || status_ == TCPClientStatus::AwaitReady || connected(); }
  void ClearPayloads() {
    std::vector<uint8_t>().swap(receive_); std::deque<TCPAuthority>().swap(authority_);
    hashes_.clear(); bootstrap_.reset(); authority_bytes_ = 0;
  }
  bool Send(const void* bytes, size_t count) {
    if (!writer_ || !writer_->TrySend(bytes, count))
      return Fail(writer_ && writer_->status() == StreamStatus::Capacity ? TCPClientStatus::Capacity : TCPClientStatus::IoError);
    return true;
  }
  void Read() {
    if (!Live()) return;
    const auto generation = generation_;
    auto bytes = std::make_shared<std::array<uint8_t, 4096>>();
    if (!writer_->AsyncReadSome(boost::asio::buffer(*bytes),
        [this, generation, bytes](boost::system::error_code ec, size_t count) {
          if (generation != generation_ || !Live()) return;
          if (ec || !count) { Fail(TCPClientStatus::IoError); return; }
          const size_t limit = status_ == TCPClientStatus::AwaitSnapshot
              ? limits_.snapshot_bytes + STATE_SNAPSHOT_HEADER_BYTES + 4096 : 8192;
          if (!AppendBoundedBytes(receive_, bytes->data(), count, limit)) { Fail(TCPClientStatus::Capacity); return; }
          last_activity_ = Clock::now();
          while (Live() && Parse()) {}
          if (Live()) Read();
        })) Fail(TCPClientStatus::IoError);
  }
  void Consume(size_t count) { receive_.erase(receive_.begin(), receive_.begin() + count); }
  bool Invalid() { return Fail(TCPClientStatus::InvalidMessage); }
  bool Parse() {
    if (receive_.empty()) return false;
    const auto type = static_cast<MessageType>(receive_[0]);
    if (status_ == TCPClientStatus::AwaitSession) {
      if (type != MessageType::SessionStart) return Invalid();
      if (receive_.size() < 1 + SESSION_START_PARAMS_BYTES) return false;
      const auto used = UnpackSessionStart(receive_.data(), receive_.size(), &session_.seed, &session_.left, &session_.right);
      if (!used || session_.left > 11 || session_.right > 11 || session_.left + session_.right == 0) return Invalid();
      if (resuming_ && (session_.seed != accepted_->seed || session_.left != accepted_->left || session_.right != accepted_->right))
        return Invalid();
      Consume(used); status_ = TCPClientStatus::AwaitSlots;
      std::array<uint8_t, RECONNECT_REQUEST_BYTES> hello{};
      size_t length = 1;
      if (resuming_) length = PackReconnectRequest(resume_token_, hello.data(), hello.size());
      else hello[0] = std::to_underlying(MessageType::Connect);
      return Send(hello.data(), length);
    }
    if (status_ == TCPClientStatus::AwaitSlots) {
      if (type != MessageType::SlotAssignment) return Invalid();
      if (receive_.size() < 3) return false;
      uint16_t count; std::memcpy(&count, receive_.data() + 1, 2);
      if (!count || count > session_.left + session_.right) return Invalid();
      if (receive_.size() < 3 + size_t(count) * 2) return false;
      std::array<bool, 22> used{}; std::vector<uint16_t> slots; slots.reserve(count);
      for (size_t i = 0; i < count; ++i) {
        uint16_t slot; std::memcpy(&slot, receive_.data() + 3 + i * 2, 2);
        if (slot >= session_.left + session_.right || used[slot]) return Invalid();
        used[slot] = true; slots.push_back(slot);
      }
      if (resuming_ && slots != accepted_->slots) return Invalid();
      session_.slots = std::move(slots); Consume(3 + size_t(count) * 2);
      status_ = resuming_ ? TCPClientStatus::AwaitSnapshot : TCPClientStatus::AwaitReady;
      return true;
    }
    if (status_ == TCPClientStatus::AwaitSnapshot) {
      if (type != MessageType::StateSnapshot) return Invalid();
      if (receive_.size() < STATE_SNAPSHOT_HEADER_BYTES) return false;
      uint32_t count; frame_id_t frame;
      std::memcpy(&frame, receive_.data() + 1, 4); std::memcpy(&count, receive_.data() + 5, 4);
      if (!count || count > limits_.snapshot_bytes || frame > UINT32_MAX - 8) return Invalid();
      const auto need = STATE_SNAPSHOT_HEADER_BYTES + size_t(count);
      if (receive_.size() < need) return false;
      TCPBootstrap owned{frame, StateBlob(receive_.begin() + STATE_SNAPSHOT_HEADER_BYTES, receive_.begin() + need)};
      if (RetainedBytes(owned.state) > limits_.snapshot_bytes) return Fail(TCPClientStatus::Capacity);
      bootstrap_ = std::move(owned);
      // Shrink the temporary large packet buffer while preserving coalesced
      // authority/hash bytes that follow the snapshot on the same stream.
      std::vector<uint8_t> tail(receive_.begin() + need, receive_.end()); receive_.swap(tail);
      status_ = TCPClientStatus::AwaitReady; return true;
    }
    if (!connected() && !(resuming_ && status_ == TCPClientStatus::AwaitReady)) return Invalid();
    if (type == MessageType::AuthoritativeFrame) {
      if (receive_.size() < 7) return false;
      uint16_t count; std::memcpy(&count, receive_.data() + 5, 2);
      if (count != session_.left + session_.right) return Invalid();
      const auto need = 7 + size_t(count) * SLOT_INPUT_BYTES;
      if (receive_.size() < need) return false;
      TCPAuthority item{};
      const auto used = UnpackAuthoritativeFrame(receive_.data(), receive_.size(), &item.frame, &item.inputs);
      if (!used || item.frame > UINT32_MAX - 8 || !std::all_of(item.inputs.begin(), item.inputs.end(), IsValidSlotInput)) return Invalid();
      const auto bytes = RetainedBytes(item.inputs);
      if (authority_.size() >= limits_.authority_frames || bytes > limits_.authority_bytes - authority_bytes_)
        return Fail(TCPClientStatus::Capacity);
      item.arrival_ms = std::chrono::duration<double, std::milli>(Clock::now().time_since_epoch()).count();
      authority_.push_back(std::move(item)); authority_bytes_ += bytes; Consume(used); return true;
    }
    if (type == MessageType::StateHash) {
      if (receive_.size() < STATE_HASH_PACK_BYTES) return false;
      frame_id_t frame; uint64_t hash;
      if (!UnpackStateHash(receive_.data(), receive_.size(), &frame, &hash)) return Invalid();
      auto previous = hashes_.find(frame);
      if (previous != hashes_.end() && previous->second != hash) return Invalid();
      if (previous == hashes_.end() && hashes_.size() >= limits_.hashes) return Fail(TCPClientStatus::Capacity);
      hashes_.emplace(frame, hash); Consume(STATE_HASH_PACK_BYTES); return true;
    }
    if (type == MessageType::Heartbeat) {
      if (receive_.size() < HEARTBEAT_PACK_BYTES) return false;
      Consume(HEARTBEAT_PACK_BYTES); return true;
    }
    if (type == MessageType::TakeoverNotify || type == MessageType::HandbackNotify) {
      if (receive_.size() < TAKEOVER_NOTIFY_BYTES) return false;
      uint16_t slot; std::memcpy(&slot, receive_.data() + 1, 2);
      if (slot >= session_.left + session_.right) return Invalid();
      bots_[slot] = type == MessageType::TakeoverNotify; Consume(TAKEOVER_NOTIFY_BYTES); return true;
    }
    return Invalid();
  }
  boost::asio::io_context io_;  // last destroyed: pending raw-this callbacks are discarded, never run
  std::shared_ptr<tcp::socket> socket_;
  std::unique_ptr<BoundedTCPWriter> writer_;
  std::string host_;
  unsigned short port_;
  const TCPClientLimits limits_;
  TCPSessionInfo session_;
  std::optional<TCPSessionInfo> accepted_;
  std::vector<uint8_t> receive_;
  std::deque<TCPAuthority> authority_;
  std::map<frame_id_t, uint64_t> hashes_;
  std::optional<TCPBootstrap> bootstrap_;
  std::array<bool, 22> bots_{};
  size_t authority_bytes_ = 0, verified_hashes_ = 0;
  uint64_t generation_ = 0;
  session_token_t resume_token_ = 0;
  TCPClientStatus status_ = TCPClientStatus::Closed;
  Clock::time_point last_activity_{};
  bool resuming_ = false, polling_ = false;
};
}  // namespace frame_sync
#endif
