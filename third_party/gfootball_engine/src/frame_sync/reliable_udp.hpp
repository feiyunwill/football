// Copyright 2019 Google LLC & Contributors
// Minimal reliable UDP over ASIO: seq, ack, retransmit. One channel per peer.

#ifndef GFOOTBALL_FRAME_SYNC_RELIABLE_UDP_HPP
#define GFOOTBALL_FRAME_SYNC_RELIABLE_UDP_HPP

#include <boost/asio.hpp>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <functional>
#include <map>
#include <mutex>
#include <vector>

namespace frame_sync {

namespace asio = boost::asio;
using udp = asio::ip::udp;

constexpr uint8_t kReliableUDP_Data = 0x00;
constexpr uint8_t kReliableUDP_Ack  = 0xFF;
constexpr size_t kReliableUDP_HeaderSize = 1 + 4 + 2;  // type, seq, len
constexpr size_t kReliableUDP_AckSize = 1 + 4;         // type, seq
constexpr int kReliableUDP_RetransmitMs = 50;
constexpr int kReliableUDP_MaxRetries = 5;

class ReliableUDPChannel {
 public:
  using OnDataFn = std::function<void(const uint8_t* data, size_t len)>;

  ReliableUDPChannel(udp::socket& socket, const udp::endpoint& remote, OnDataFn on_data)
      : socket_(socket), remote_(remote), on_data_(std::move(on_data)) {}

  void Send(const void* data, size_t len) {
    std::lock_guard<std::mutex> lock(mu_);
    uint32_t seq = next_send_seq_++;
    std::vector<uint8_t> packet(kReliableUDP_HeaderSize + len);
    packet[0] = kReliableUDP_Data;
    packet[1] = (seq >> 0) & 0xFF;
    packet[2] = (seq >> 8) & 0xFF;
    packet[3] = (seq >> 16) & 0xFF;
    packet[4] = (seq >> 24) & 0xFF;
    uint16_t ulen = static_cast<uint16_t>(len);
    packet[5] = ulen & 0xFF;
    packet[6] = (ulen >> 8) & 0xFF;
    if (len) memcpy(packet.data() + kReliableUDP_HeaderSize, data, len);
    pending_[seq] = { packet, std::chrono::steady_clock::now(), 0 };
    send_packet(pending_[seq].packet);
  }

  void HandleReceived(const uint8_t* buf, size_t len) {
    if (len < 1u) return;
    if (buf[0] == kReliableUDP_Ack) {
      if (len < kReliableUDP_AckSize) return;
      uint32_t seq = buf[1] | (buf[2]<<8) | (buf[3]<<16) | (buf[4]<<24);
      std::lock_guard<std::mutex> lock(mu_);
      pending_.erase(seq);
      return;
    }
    if (buf[0] == kReliableUDP_Data && len >= kReliableUDP_HeaderSize) {
      uint32_t seq = buf[1] | (buf[2]<<8) | (buf[3]<<16) | (buf[4]<<24);
      uint16_t plen = buf[5] | (buf[6]<<8);
      if (len < kReliableUDP_HeaderSize + plen) return;
      uint8_t ack_buf[kReliableUDP_AckSize];
      ack_buf[0] = kReliableUDP_Ack;
      ack_buf[1] = (seq >> 0) & 0xFF;
      ack_buf[2] = (seq >> 8) & 0xFF;
      ack_buf[3] = (seq >> 16) & 0xFF;
      ack_buf[4] = (seq >> 24) & 0xFF;
      socket_.send_to(asio::buffer(ack_buf), remote_);
      if (on_data_) on_data_(buf + kReliableUDP_HeaderSize, plen);
    }
  }

  void TickRetransmit() {
    auto now = std::chrono::steady_clock::now();
    std::lock_guard<std::mutex> lock(mu_);
    for (auto it = pending_.begin(); it != pending_.end(); ) {
      auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - it->second.sent_at).count();
      if (elapsed >= kReliableUDP_RetransmitMs) {
        if (it->second.retries >= kReliableUDP_MaxRetries) {
          it = pending_.erase(it);
          continue;
        }
        send_packet(it->second.packet);
        it->second.sent_at = now;
        it->second.retries++;
      }
      ++it;
    }
  }

  udp::endpoint remote() const { return remote_; }

 private:
  void send_packet(const std::vector<uint8_t>& packet) {
    socket_.send_to(asio::buffer(packet), remote_);
  }

  udp::socket& socket_;
  udp::endpoint remote_;
  OnDataFn on_data_;
  std::mutex mu_;
  uint32_t next_send_seq_ = 0;
  struct Pending {
    std::vector<uint8_t> packet;
    std::chrono::steady_clock::time_point sent_at;
    int retries = 0;
  };
  std::map<uint32_t, Pending> pending_;
};

}  // namespace frame_sync

#endif
