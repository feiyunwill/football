// Copyright 2019 Google LLC & Contributors
// Minimal reliable UDP over ASIO: seq, ack, retransmit. One channel per peer.
// 2026-08-30 Performance optimizations: reduced allocations, lock contention, branch prediction.
// 2026-08-30 Network optimizations: congestion control, bandwidth estimation, RTT tracking.

#ifndef GFOOTBALL_FRAME_SYNC_RELIABLE_UDP_HPP
#define GFOOTBALL_FRAME_SYNC_RELIABLE_UDP_HPP

// 2026-08-26 兼容修复（原因）：GCC 15 的 libstdc++ 不再向系统 Boost 1.75 的
// awaitable.hpp 传递提供 <utility>（std::exchange 未声明），须先于 asio 显式包含。
#include "frame_sync/memory_budget.hpp"
#include <algorithm>
#include <array>
#include <optional>
#include <map>
#include <mutex>
#include <utility>
#include <boost/asio.hpp>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <functional>
#include <flat_map>
#include <vector>
#include <deque>

namespace frame_sync {

namespace asio = boost::asio;
using udp = asio::ip::udp;

constexpr uint8_t kReliableUDP_Data = 0x00;
constexpr uint8_t kReliableUDP_Ack  = 0xFF;
constexpr size_t kReliableUDP_HeaderSize = 1 + 4 + 2;  // type, seq, len
constexpr size_t kReliableUDP_AckSize = 1 + 4;         // type, seq
constexpr int kReliableUDP_RetransmitMs = 50;
constexpr int kReliableUDP_MaxRetries = 5;

// RTT tracker for congestion control
class RTTTracker {
 public:
  static constexpr size_t kWindowSize = 32;  // Sliding window size
  
  void RecordSample(std::chrono::milliseconds rtt) {
    // 2026-09-09: bound counters before summation and ignore clock reversal.
    // samples_[write_index_] = rtt;
    if (rtt.count() < 0) return;
    samples_[write_index_] = std::min(rtt, std::chrono::milliseconds(60000));
    write_index_ = (write_index_ + 1) % kWindowSize;
    if (sample_count_ < kWindowSize) sample_count_++;
  }
  
  std::chrono::milliseconds GetSmoothedRTT() const {
    if (sample_count_ == 0) return std::chrono::milliseconds(100);  // Default
    
    std::chrono::milliseconds sum(0);
    for (size_t i = 0; i < sample_count_; ++i) {
      sum += samples_[i];
    }
    return sum / sample_count_;
  }
  
  std::chrono::milliseconds GetRTTVar() const {
    if (sample_count_ < 2) return std::chrono::milliseconds(10);
    
    auto mean = GetSmoothedRTT();
    std::chrono::milliseconds variance(0);
    for (size_t i = 0; i < sample_count_; ++i) {
      auto diff = samples_[i] - mean;
      // 2026-09-09: RTO needs deviation in ms, not squared milliseconds.
      // variance += std::chrono::milliseconds(diff.count() * diff.count());
      variance += std::chrono::milliseconds(diff.count() < 0 ? -diff.count() : diff.count());
    }
    return variance / sample_count_;
  }
  
  void Reset() {
    write_index_ = 0;
    sample_count_ = 0;
  }

 private:
  std::chrono::milliseconds samples_[kWindowSize] = {};
  size_t write_index_ = 0;
  size_t sample_count_ = 0;
};

// Bandwidth estimator
class BandwidthEstimator {
 public:
  void RecordBytesSent(size_t bytes, std::chrono::steady_clock::time_point now) {
    total_bytes_ += bytes;
    bytes_in_window_ += bytes;
    
    auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - window_start_).count();
    if (elapsed >= kWindowMs) {
      bandwidth_bps_ = (bytes_in_window_ * 8 * 1000) / elapsed;
      bytes_in_window_ = 0;
      window_start_ = now;
    }
  }
  
  size_t GetBandwidthBPS() const {
    return bandwidth_bps_;
  }
  
  size_t GetTotalBytes() const {
    return total_bytes_;
  }
  
  void Reset() {
    total_bytes_ = 0;
    bytes_in_window_ = 0;
    bandwidth_bps_ = 0;
    window_start_ = std::chrono::steady_clock::now();
  }

 private:
  static constexpr int kWindowMs = 1000;  // 1 second window
  
  size_t total_bytes_ = 0;
  size_t bytes_in_window_ = 0;
  size_t bandwidth_bps_ = 0;
  std::chrono::steady_clock::time_point window_start_ = std::chrono::steady_clock::now();
};

// 2026-09-09: replace unbounded retained packets and throwing transport with
// count/byte budgets and observable failure; original implementation follows.
//
// class ReliableUDPChannel {
//  public:
//   using OnDataFn = std::move_only_function<void(const uint8_t* data, size_t len)>;
//
//   ReliableUDPChannel(udp::socket& socket, const udp::endpoint& remote, OnDataFn on_data)
//       : socket_(socket), remote_(remote), on_data_(std::move(on_data)) {}
//
//   // Optimized: pre-allocate buffer pool, reduce lock scope
//   void Send(const void* data, size_t len) {
//     uint32_t seq;
//     auto send_time = std::chrono::steady_clock::now();
//
//     {
//       std::lock_guard<std::mutex> lock(mu_);
//       seq = next_send_seq_++;
//     }
//
//     // Use stack buffer for small packets (most common)
//     constexpr size_t kMaxStackPacket = 256;
//     alignas(alignof(uint64_t)) uint8_t stack_buf[kMaxStackPacket];
//     std::vector<uint8_t> heap_buf;
//     uint8_t* packet;
//
//     size_t packet_size = kReliableUDP_HeaderSize + len;
//     if (packet_size <= kMaxStackPacket) {
//       packet = stack_buf;
//     } else {
//       heap_buf.resize(packet_size);
//       packet = heap_buf.data();
//     }
//
//     // Pack header
//     packet[0] = kReliableUDP_Data;
//     packet[1] = (seq >> 0) & 0xFF;
//     packet[2] = (seq >> 8) & 0xFF;
//     packet[3] = (seq >> 16) & 0xFF;
//     packet[4] = (seq >> 24) & 0xFF;
//     uint16_t ulen = static_cast<uint16_t>(len);
//     packet[5] = ulen & 0xFF;
//     packet[6] = (ulen >> 8) & 0xFF;
//
//     // Copy payload
//     if (len) {
//       std::memcpy(packet + kReliableUDP_HeaderSize, data, len);
//     }
//
//     // Store pending packet
//     {
//       std::lock_guard<std::mutex> lock(mu_);
//       pending_[seq] = { std::vector<uint8_t>(packet, packet + packet_size),
//                         send_time, 0 };
//     }
//
//     // Update bandwidth estimation
//     bandwidth_estimator_.RecordBytesSent(packet_size, send_time);
//
//     // Send packet (outside lock)
//     socket_.send_to(asio::buffer(packet, packet_size), remote_);
//   }
//
//   void HandleReceived(const uint8_t* buf, size_t len) {
//     // Fast path check (branch prediction hint)
//     if (__builtin_expect(len < 1u, 0)) return;
//
//     if (buf[0] == kReliableUDP_Ack) {
//       if (__builtin_expect(len < kReliableUDP_AckSize, 0)) return;
//       uint32_t seq = buf[1] | (buf[2]<<8) | (buf[3]<<16) | (buf[4]<<24);
//
//       auto now = std::chrono::steady_clock::now();
//       std::lock_guard<std::mutex> lock(mu_);
//       auto it = pending_.find(seq);
//       if (it != pending_.end()) {
//         // Record RTT sample
//         auto rtt = std::chrono::duration_cast<std::chrono::milliseconds>(now - it->second.sent_at);
//         rtt_tracker_.RecordSample(rtt);
//         pending_.erase(it);
//       }
//       return;
//     }
//
//     if (buf[0] == kReliableUDP_Data) {
//       if (__builtin_expect(len < kReliableUDP_HeaderSize, 0)) return;
//       uint32_t seq = buf[1] | (buf[2]<<8) | (buf[3]<<16) | (buf[4]<<24);
//       uint16_t plen = buf[5] | (buf[6]<<8);
//       if (__builtin_expect(len < kReliableUDP_HeaderSize + plen, 0)) return;
//
//       // Send ACK (immediate, no lock)
//       uint8_t ack_buf[kReliableUDP_AckSize];
//       ack_buf[0] = kReliableUDP_Ack;
//       ack_buf[1] = (seq >> 0) & 0xFF;
//       ack_buf[2] = (seq >> 8) & 0xFF;
//       ack_buf[3] = (seq >> 16) & 0xFF;
//       ack_buf[4] = (seq >> 24) & 0xFF;
//       socket_.send_to(asio::buffer(ack_buf), remote_);
//
//       // Deliver data (callback outside lock)
//       if (on_data_) {
//         on_data_(buf + kReliableUDP_HeaderSize, plen);
//       }
//     }
//   }
//
//   // Optimized: batch retransmit, reduce time calls
//   void TickRetransmit() {
//     const auto now = std::chrono::steady_clock::now();
//
//     // Dynamic retransmit timeout based on RTT
//     auto smoothed_rtt = rtt_tracker_.GetSmoothedRTT();
//     auto rtt_var = rtt_tracker_.GetRTTVar();
//     auto timeout_ms = std::max(
//       std::chrono::milliseconds(kReliableUDP_RetransmitMs),
//       smoothed_rtt + rtt_var * 4
//     );
//
//     std::lock_guard<std::mutex> lock(mu_);
//     for (auto it = pending_.begin(); it != pending_.end(); ) {
//       auto elapsed = now - it->second.sent_at;
//       if (elapsed >= timeout_ms) {
//         if (it->second.retries >= kReliableUDP_MaxRetries) {
//           it = pending_.erase(it);
//           continue;
//         }
//
//         // Retransmit (move outside inner scope)
//         socket_.send_to(asio::buffer(it->second.packet), remote_);
//         it->second.sent_at = now;
//         it->second.retries++;
//       }
//       ++it;
//     }
//   }
//
//   // Get current statistics
//   size_t pending_count() const {
//     std::lock_guard<std::mutex> lock(mu_);
//     return pending_.size();
//   }
//
//   std::chrono::milliseconds GetSmoothedRTT() const {
//     return rtt_tracker_.GetSmoothedRTT();
//   }
//
//   size_t GetBandwidthBPS() const {
//     return bandwidth_estimator_.GetBandwidthBPS();
//   }
//
//   udp::endpoint remote() const { return remote_; }
//
//  private:
//   udp::socket& socket_;
//   udp::endpoint remote_;
//   OnDataFn on_data_;
//   mutable std::mutex mu_;  // mutable for const methods
//   uint32_t next_send_seq_ = 0;
//   RTTTracker rtt_tracker_;
//   BandwidthEstimator bandwidth_estimator_;
//
//   struct Pending {
//     std::vector<uint8_t> packet;
//     std::chrono::steady_clock::time_point sent_at;
//     int retries = 0;
//   };
//   std::flat_map<uint32_t, Pending> pending_;
// };

// 2026-09-09: the receive buffer size was not a safe outbound packet budget.
// Real local-path probes delivered <=1472 bytes but dropped >=2048 bytes.
// inline constexpr size_t kReliableUDP_MaxPacketSize = 4096;
// Current full 22-slot messages fit in 1200 bytes; larger protocols need fragments.
inline constexpr size_t kReliableUDP_MaxPacketSize = 1200;
inline constexpr size_t kReliableUDP_MaxPayload =
    kReliableUDP_MaxPacketSize - kReliableUDP_HeaderSize;

enum class UDPChannelStatus {
  Ready, InvalidPayload, Capacity, SocketError, RetriesExhausted, Closed
};

inline const char* UDPChannelStatusName(UDPChannelStatus status) {
  switch (status) {
    case UDPChannelStatus::Ready: return "ready";
    case UDPChannelStatus::InvalidPayload: return "invalid payload";
    case UDPChannelStatus::Capacity: return "packet capacity exhausted";
    case UDPChannelStatus::SocketError: return "socket error";
    case UDPChannelStatus::RetriesExhausted: return "retries exhausted";
    case UDPChannelStatus::Closed: return "closed";
  }
  return "unknown";
}

// 2026-09-15: distinct physical connections bind both data and ACKs before
// reliability state is touched. The endpoint owner negotiates a fresh nonzero
// identity and authenticates the application grant; this public identity is not
// an authentication token. Legacy channels retain their exact wire format.
using ReliableUDPConnection = std::array<uint8_t, 16>;
inline constexpr uint8_t kReliableUDP_SessionData = 0x01;
inline constexpr uint8_t kReliableUDP_SessionAck = 0xFE;
inline constexpr size_t kReliableUDP_ConnectionBytes = 16;
inline constexpr size_t kReliableUDP_SessionHeaderSize =
    kReliableUDP_HeaderSize + kReliableUDP_ConnectionBytes;
inline constexpr size_t kReliableUDP_SessionAckSize =
    kReliableUDP_AckSize + kReliableUDP_ConnectionBytes;

class ReliableUDPChannel {
 public:
  using OnDataFn = std::move_only_function<void(const uint8_t*, size_t)>;
  using Clock = std::chrono::steady_clock;
  using NowFn = std::function<Clock::time_point()>;

  ReliableUDPChannel(udp::socket& socket, const udp::endpoint& remote,
                     OnDataFn on_data, DatagramBudget budget = DatagramBudget{},
// 2026-09-15: bind reliable state to the immutable physical connection.
//                      NowFn now = Clock::now)
//       : socket_(socket), remote_(remote), on_data_(std::move(on_data)),
//         budget_(budget.packet_limit, budget.byte_limit), now_(std::move(now)) {
//     if (!now_) throw std::invalid_argument("UDP clock callback is required");
//   }
                     NowFn now = Clock::now,
                     std::optional<ReliableUDPConnection> connection = std::nullopt)
      : socket_(socket), remote_(remote), on_data_(std::move(on_data)),
        budget_(budget.packet_limit, budget.byte_limit), now_(std::move(now)),
        connection_(std::move(connection)) {
    if (!now_) throw std::invalid_argument("UDP clock callback is required");
    if (connection_ && std::all_of(connection_->begin(), connection_->end(),
                                  [](uint8_t b) { return b == 0; }))
      throw std::invalid_argument("UDP connection identity must be nonzero");
  }
  ~ReliableUDPChannel() = default;
  ReliableUDPChannel(const ReliableUDPChannel&) = delete;
  ReliableUDPChannel& operator=(const ReliableUDPChannel&) = delete;
  ReliableUDPChannel(ReliableUDPChannel&&) = delete;
  ReliableUDPChannel& operator=(ReliableUDPChannel&&) = delete;

  // Capacity is recoverable after ACKs; callers must retry or end the session,
  // never silently skip a reliable message. Hard I/O failures close the channel.
  [[nodiscard]] bool Send(const void* data, size_t len) {
    std::lock_guard<std::mutex> lock(mu_);
    if (closed_) return false;
// 2026-09-15: bind reliable state to the immutable physical connection.
//     if ((len && !data) || len > kReliableUDP_MaxPayload) {
    if ((len && !data) || len > max_payload_size()) {
      status_ = UDPChannelStatus::InvalidPayload;
      return false;
    }
// 2026-09-15: bind reliable state to the immutable physical connection.
//     const size_t bytes = kReliableUDP_HeaderSize + len;
    const size_t bytes = HeaderSize() + len;
    // 2026-09-15: selective ACKs free packet storage but cannot move the peer's
    // receive window past its missing earliest sequence. Preserve that window.
    // if (pending_.size() >= budget_.packet_limit ||
    if (static_cast<uint32_t>(next_send_seq_ - send_window_base_) >= budget_.packet_limit ||
        pending_.size() >= budget_.packet_limit ||
        bytes > budget_.byte_limit - pending_bytes_ ||
        pending_.contains(next_send_seq_)) {
      status_ = UDPChannelStatus::Capacity;
      return false;
    }
    const auto now = now_();
    std::vector<uint8_t> packet(bytes);
    if (RetainedBytes(packet) > budget_.byte_limit - pending_bytes_) {
      status_ = UDPChannelStatus::Capacity;
      return false;
    }
// 2026-09-15: bind reliable state to the immutable physical connection.
//     packet[0] = kReliableUDP_Data;
//     WriteSequence(packet.data() + 1, next_send_seq_);
//     packet[5] = static_cast<uint8_t>(len);
//     packet[6] = static_cast<uint8_t>(len >> 8);
//     if (len) std::memcpy(packet.data() + kReliableUDP_HeaderSize, data, len);
    FillPrefix(packet.data(), false);
    const auto at = SequenceOffset();
    WriteSequence(packet.data() + at, next_send_seq_);
    packet[at + 4] = static_cast<uint8_t>(len);
    packet[at + 5] = static_cast<uint8_t>(len >> 8);
    if (len) std::memcpy(packet.data() + HeaderSize(), data, len);
    // Allocate before sending: failure cannot leave an untracked wire packet.
    auto [it, inserted] = pending_.emplace(
        next_send_seq_, Pending{std::move(packet), now, 0});
    pending_bytes_ += RetainedBytes(it->second.packet);
    boost::system::error_code ec;
    const auto sent = socket_.send_to(asio::buffer(it->second.packet), remote_, 0, ec);
    if (ec || sent != bytes) {
      CloseLocked(UDPChannelStatus::SocketError);
      return false;
    }
    ++next_send_seq_;
    bandwidth_estimator_.RecordBytesSent(bytes, now);
    status_ = UDPChannelStatus::Ready;
    return true;
  }

  // Invalid datagrams are ignored without allocating; a false result means a
  // terminal transport failure, which the owning session must handle.
// 2026-09-13: deliver reliable UDP application bytes exactly once and in order within independent receive budgets.
//   [[nodiscard]] bool HandleReceived(const uint8_t* buf, size_t len) {
//     {
//       std::lock_guard<std::mutex> lock(mu_);
//       if (closed_) return false;
//       if (!buf || len == 0 || len > kReliableUDP_MaxPacketSize) return true;
//       if (buf[0] == kReliableUDP_Ack) {
//         if (len != kReliableUDP_AckSize) return true;
//         auto it = pending_.find(ReadSequence(buf + 1));
//         if (it != pending_.end()) {
//           // Retransmitted ACKs cannot identify which attempt supplied the RTT.
//           if (it->second.retries == 0)
//             rtt_tracker_.RecordSample(std::chrono::duration_cast<std::chrono::milliseconds>(
//                 now_() - it->second.sent_at));
//           pending_bytes_ -= RetainedBytes(it->second.packet);
//           pending_.erase(it);
//         }
//         return true;
//       }
//       if (buf[0] != kReliableUDP_Data || len < kReliableUDP_HeaderSize) return true;
//       const size_t payload = static_cast<size_t>(buf[5]) |
//                              (static_cast<size_t>(buf[6]) << 8);
//       if (len != kReliableUDP_HeaderSize + payload) return true;
//       uint8_t ack[kReliableUDP_AckSize] = {kReliableUDP_Ack};
//       WriteSequence(ack + 1, ReadSequence(buf + 1));
//       boost::system::error_code ec;
//       const auto sent = socket_.send_to(asio::buffer(ack), remote_, 0, ec);
//       if (ec || sent != sizeof(ack)) {
//         CloseLocked(UDPChannelStatus::SocketError);
//         return false;
//       }
//     }
//     // The callback may Close() or Send(); never invoke it under the channel lock.
//     if (on_data_) on_data_(buf + kReliableUDP_HeaderSize, len - kReliableUDP_HeaderSize);
//     return true;
//   }
// 2026-09-15: prior unscoped receiver retained for review.
//   [[nodiscard]] bool HandleReceived(const uint8_t* buf, size_t len) {
//     {
//       std::lock_guard<std::mutex> lock(mu_);
//       if (closed_) return false;
//       if (!buf || len == 0 || len > kReliableUDP_MaxPacketSize) return true;
//       if (buf[0] == kReliableUDP_Ack) {
//         if (len != kReliableUDP_AckSize) return true;
//         auto it = pending_.find(ReadSequence(buf + 1));
//         if (it != pending_.end()) {
//           if (it->second.retries == 0)
//             rtt_tracker_.RecordSample(std::chrono::duration_cast<std::chrono::milliseconds>(
//                 now_() - it->second.sent_at));
//           pending_bytes_ -= RetainedBytes(it->second.packet);
//           pending_.erase(it);
//         }
//         return true;
//       }
//       if (buf[0] != kReliableUDP_Data || len < kReliableUDP_HeaderSize) return true;
//       const size_t payload = static_cast<size_t>(buf[5]) | (static_cast<size_t>(buf[6]) << 8);
//       if (len != kReliableUDP_HeaderSize + payload) return true;
//       const auto sequence = ReadSequence(buf + 1);
//       const uint32_t distance = sequence - next_receive_seq_;
//       // Serial arithmetic distinguishes old duplicates across the uint32 wrap.
//       if (distance < (uint32_t{1} << 31)) {
//         if (distance >= budget_.packet_limit) {
//           CloseLocked(UDPChannelStatus::InvalidPayload);
//           return false;
//         }
//         auto existing = received_.find(sequence);
//         if (existing != received_.end()) {
//           if (existing->second.size() != len ||
//               !std::equal(existing->second.begin(), existing->second.end(), buf)) {
//             CloseLocked(UDPChannelStatus::InvalidPayload);
//             return false;
//           }
//         } else {
//           const auto used = received_bytes_ + delivering_bytes_;
//           if (received_.size() + (delivering_bytes_ != 0) >= budget_.packet_limit ||
//               len > budget_.byte_limit - used) {
//             CloseLocked(UDPChannelStatus::Capacity);
//             return false;
//           }
//           std::vector<uint8_t> owned(buf, buf + len);
//           const auto retained = RetainedBytes(owned);
//           if (retained > budget_.byte_limit - used) {
//             CloseLocked(UDPChannelStatus::Capacity);
//             return false;
//           }
//           received_.emplace(sequence, std::move(owned));
//           received_bytes_ += retained;
//         }
//       }
//       // ACK only data that is retained or already delivered. Repeated ACKs do
//       // not deliver the same application bytes twice.
//       uint8_t ack[kReliableUDP_AckSize] = {kReliableUDP_Ack};
//       WriteSequence(ack + 1, sequence);
//       boost::system::error_code ec;
//       const auto sent = socket_.send_to(asio::buffer(ack), remote_, 0, ec);
//       if (ec || sent != sizeof(ack)) {
//         CloseLocked(UDPChannelStatus::SocketError);
//         return false;
//       }
//       if (delivering_) return true;
//       delivering_ = true;
//     }
//     // One drainer serializes callbacks while permitting reentrant Send/Close
//     // and Receive. The in-flight packet remains charged to the receive budget.
//     for (;;) {
//       std::vector<uint8_t> packet;
//       {
//         std::lock_guard<std::mutex> lock(mu_);
//         auto next = received_.find(next_receive_seq_);
//         if (closed_ || next == received_.end()) {
//           delivering_ = false;
//           return true;
//         }
//         packet = std::move(next->second);
//         delivering_bytes_ = RetainedBytes(packet);
//         received_bytes_ -= delivering_bytes_;
//         received_.erase(next);
//         ++next_receive_seq_;
//       }
//       try {
//         if (on_data_) on_data_(packet.data() + kReliableUDP_HeaderSize,
//                                packet.size() - kReliableUDP_HeaderSize);
//       } catch (...) {
//         std::lock_guard<std::mutex> lock(mu_);
// // 2026-09-13: release callback storage before returning its receive budget.
// //         delivering_bytes_ = 0;
// //         delivering_ = false;
//         std::vector<uint8_t>().swap(packet);
//         delivering_bytes_ = 0;
//         delivering_ = false;
//         CloseLocked(UDPChannelStatus::InvalidPayload);
//         throw;
//       }
//       {
//         std::lock_guard<std::mutex> lock(mu_);
// // 2026-09-13: include the live callback allocation until it is freed under the receive lock.
// //         delivering_bytes_ = 0;
// //       }
// //     }
// //   }
//         std::vector<uint8_t>().swap(packet);
//         delivering_bytes_ = 0;
//       }
//     }
//   }
//
  [[nodiscard]] bool HandleReceived(const uint8_t* buf, size_t len) {
    {
      std::lock_guard<std::mutex> lock(mu_);
      if (closed_) return false;
      if (!buf || len == 0 || len > kReliableUDP_MaxPacketSize) return true;
      if (!AcceptsPrefix(buf, len)) return true;
      const auto at = SequenceOffset();
      if (buf[0] == AckType()) {
        if (len != AckSize()) return true;
        auto it = pending_.find(ReadSequence(buf + at));
        if (it != pending_.end()) {
          if (it->second.retries == 0)
            rtt_tracker_.RecordSample(std::chrono::duration_cast<std::chrono::milliseconds>(
                now_() - it->second.sent_at));
          pending_bytes_ -= RetainedBytes(it->second.packet);
          pending_.erase(it);
          // 2026-09-15: advance across confirmed holes only; at most one bounded
          // send window is scanned, with unsigned sequence wrap preserved.
          while (send_window_base_ != next_send_seq_ &&
                 !pending_.contains(send_window_base_))
            ++send_window_base_;
        }
        return true;
      }
      if (buf[0] != DataType() || len < HeaderSize()) return true;
      const size_t payload = static_cast<size_t>(buf[at + 4]) |
                             (static_cast<size_t>(buf[at + 5]) << 8);
      if (len != HeaderSize() + payload) return true;
      const auto sequence = ReadSequence(buf + at);
      const uint32_t distance = sequence - next_receive_seq_;
      // Serial arithmetic distinguishes old duplicates across the uint32 wrap.
      if (distance < (uint32_t{1} << 31)) {
        if (distance >= budget_.packet_limit) {
          CloseLocked(UDPChannelStatus::InvalidPayload);
          return false;
        }
        auto existing = received_.find(sequence);
        if (existing != received_.end()) {
          if (existing->second.size() != len ||
              !std::equal(existing->second.begin(), existing->second.end(), buf)) {
            CloseLocked(UDPChannelStatus::InvalidPayload);
            return false;
          }
        } else {
          const auto used = received_bytes_ + delivering_bytes_;
          if (received_.size() + (delivering_bytes_ != 0) >= budget_.packet_limit ||
              len > budget_.byte_limit - used) {
            CloseLocked(UDPChannelStatus::Capacity);
            return false;
          }
          std::vector<uint8_t> owned(buf, buf + len);
          const auto retained = RetainedBytes(owned);
          if (retained > budget_.byte_limit - used) {
            CloseLocked(UDPChannelStatus::Capacity);
            return false;
          }
          received_.emplace(sequence, std::move(owned));
          received_bytes_ += retained;
        }
      }
      // ACK only data that is retained or already delivered. Repeated ACKs do
      // not deliver the same application bytes twice.
      std::array<uint8_t, kReliableUDP_SessionAckSize> ack{};
      FillPrefix(ack.data(), true);
      WriteSequence(ack.data() + at, sequence);
      boost::system::error_code ec;
      const auto sent = socket_.send_to(
          asio::buffer(ack.data(), AckSize()), remote_, 0, ec);
      if (ec || sent != AckSize()) {
        CloseLocked(UDPChannelStatus::SocketError);
        return false;
      }
      if (delivering_) return true;
      delivering_ = true;
    }
    // One drainer serializes callbacks while permitting reentrant Send/Close
    // and Receive. The in-flight packet remains charged to the receive budget.
    for (;;) {
      std::vector<uint8_t> packet;
      {
        std::lock_guard<std::mutex> lock(mu_);
        auto next = received_.find(next_receive_seq_);
        if (closed_ || next == received_.end()) {
          delivering_ = false;
          return true;
        }
        packet = std::move(next->second);
        delivering_bytes_ = RetainedBytes(packet);
        received_bytes_ -= delivering_bytes_;
        received_.erase(next);
        ++next_receive_seq_;
      }
      try {
        if (on_data_) on_data_(packet.data() + HeaderSize(),
                               packet.size() - HeaderSize());
      } catch (...) {
        std::lock_guard<std::mutex> lock(mu_);
// 2026-09-13: release callback storage before returning its receive budget.
//         delivering_bytes_ = 0;
//         delivering_ = false;
        std::vector<uint8_t>().swap(packet);
        delivering_bytes_ = 0;
        delivering_ = false;
        CloseLocked(UDPChannelStatus::InvalidPayload);
        throw;
      }
      {
        std::lock_guard<std::mutex> lock(mu_);
// 2026-09-13: include the live callback allocation until it is freed under the receive lock.
//         delivering_bytes_ = 0;
//       }
//     }
//   }
        std::vector<uint8_t>().swap(packet);
        delivering_bytes_ = 0;
      }
    }
  }

  [[nodiscard]] bool TickRetransmit() {
    std::lock_guard<std::mutex> lock(mu_);
    if (closed_) return false;
    const auto now = now_();
    const auto timeout = std::clamp(
        rtt_tracker_.GetSmoothedRTT() + rtt_tracker_.GetRTTVar() * 4,
        std::chrono::milliseconds(kReliableUDP_RetransmitMs),
        std::chrono::milliseconds(1000));
    for (auto& [seq, pending] : pending_) {
      if (now - pending.sent_at < timeout) continue;
      if (pending.retries >= kReliableUDP_MaxRetries) {
        // Losing one reliable message invalidates the stream; release all of it.
        CloseLocked(UDPChannelStatus::RetriesExhausted);
        return false;
      }
      boost::system::error_code ec;
      const auto sent = socket_.send_to(asio::buffer(pending.packet), remote_, 0, ec);
      if (ec || sent != pending.packet.size()) {
        CloseLocked(UDPChannelStatus::SocketError);
        return false;
      }
      pending.sent_at = now;
      ++pending.retries;
      bandwidth_estimator_.RecordBytesSent(sent, now);
    }
    return true;
  }

  void Close() {
    std::lock_guard<std::mutex> lock(mu_);
    if (!closed_) CloseLocked(UDPChannelStatus::Closed);
  }
  size_t pending_count() const {
    std::lock_guard<std::mutex> lock(mu_);
    return pending_.size();
  }
  size_t pending_bytes() const {
    std::lock_guard<std::mutex> lock(mu_);
    return pending_bytes_;
  }
// 2026-09-13: expose bounded queued and in-flight receive storage for verification.
//   UDPChannelStatus status() const {
  size_t received_count() const {
    std::lock_guard<std::mutex> lock(mu_);
    return received_.size() + (delivering_bytes_ != 0);
  }
  size_t received_bytes() const {
    std::lock_guard<std::mutex> lock(mu_);
    return received_bytes_ + delivering_bytes_;
  }
  UDPChannelStatus status() const {
    std::lock_guard<std::mutex> lock(mu_);
    return status_;
  }
  std::chrono::milliseconds GetSmoothedRTT() const {
    std::lock_guard<std::mutex> lock(mu_);
    return rtt_tracker_.GetSmoothedRTT();
  }
  size_t GetBandwidthBPS() const {
    std::lock_guard<std::mutex> lock(mu_);
    return bandwidth_estimator_.GetBandwidthBPS();
  }
  udp::endpoint remote() const { return remote_; }
  size_t max_payload_size() const {
    return kReliableUDP_MaxPacketSize - HeaderSize();
  }

 private:
  size_t SequenceOffset() const {
    return 1 + (connection_ ? kReliableUDP_ConnectionBytes : 0);
  }
  size_t HeaderSize() const { return SequenceOffset() + 6; }
  size_t AckSize() const { return SequenceOffset() + 4; }
  uint8_t DataType() const {
    return connection_ ? kReliableUDP_SessionData : kReliableUDP_Data;
  }
  uint8_t AckType() const {
    return connection_ ? kReliableUDP_SessionAck : kReliableUDP_Ack;
  }
  bool AcceptsPrefix(const uint8_t* bytes, size_t count) const {
    if (count < SequenceOffset()) return false;
    if (bytes[0] != DataType() && bytes[0] != AckType()) return false;
    return !connection_ || std::equal(connection_->begin(), connection_->end(), bytes + 1);
  }
  void FillPrefix(uint8_t* bytes, bool ack) const {
    bytes[0] = ack ? AckType() : DataType();
    if (connection_) std::copy(connection_->begin(), connection_->end(), bytes + 1);
  }

  static void WriteSequence(uint8_t* output, uint32_t seq) {
    for (unsigned i = 0; i < 4; ++i) output[i] = static_cast<uint8_t>(seq >> (i * 8));
  }
  static uint32_t ReadSequence(const uint8_t* input) {
    uint32_t seq = 0;
    for (unsigned i = 0; i < 4; ++i) seq |= static_cast<uint32_t>(input[i]) << (i * 8);
    return seq;
  }
  void CloseLocked(UDPChannelStatus reason) {
    pending_.clear();
// 2026-09-13: a terminal reliable channel releases retained reordered input too.
//     pending_bytes_ = 0;
//     closed_ = true;
    pending_bytes_ = 0;
    received_.clear();
    received_bytes_ = 0;
    closed_ = true;
    status_ = reason;
    // socket_ is shared by server peers: only its owner may close it.
  }
  udp::socket& socket_;
  const udp::endpoint remote_;
  OnDataFn on_data_;
// 2026-09-13: retain only the bounded future sequence window, with a single callback owner.
//   const DatagramBudget budget_;
  const DatagramBudget budget_;
  // Send and receive each have this packet/byte budget; callback storage is included.
  std::flat_map<uint32_t, std::vector<uint8_t>> received_;
  uint32_t next_receive_seq_ = 0;
  size_t received_bytes_ = 0, delivering_bytes_ = 0;
  bool delivering_ = false;
  NowFn now_;
  mutable std::mutex mu_;
  const std::optional<ReliableUDPConnection> connection_;
  uint32_t next_send_seq_ = 0;
  // 2026-09-15: oldest sequence not yet acknowledged by this peer.
  uint32_t send_window_base_ = 0;
  RTTTracker rtt_tracker_;
  BandwidthEstimator bandwidth_estimator_;
  struct Pending {
    std::vector<uint8_t> packet;
    Clock::time_point sent_at;
    int retries;
  };
  // Nodes are freed on ACK/close; object overhead is separately bounded by count.
  std::map<uint32_t, Pending> pending_;
  size_t pending_bytes_ = 0;
  bool closed_ = false;
  UDPChannelStatus status_ = UDPChannelStatus::Ready;
};

}  // namespace frame_sync

#endif
