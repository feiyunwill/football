#pragma once
// 2026-09-14: Real TCP lifecycle with short configured leases and checked frame-owner callbacks.
#include "frame_sync/engine_tcp_server.hpp"
#include <iostream>
#include <thread>
#include <poll.h>
namespace fs = frame_sync;
namespace asio = boost::asio;
using tcp = asio::ip::tcp;
using namespace std::chrono_literals;
size_t assertions = 0;
void require(bool value, const char* message) {
  ++assertions;if (!value) throw std::runtime_error(message);
}
template<class Condition> void until(Condition condition, const char* reason) {
  const auto deadline = std::chrono::steady_clock::now()+3s;
  while (std::chrono::steady_clock::now() < deadline) {
    if (condition()) return;
    std::this_thread::sleep_for(1ms);
  }
  require(false, reason);
}
class Server {
 public:
  Server() = delete;
  // 2026-09-14: a parameterized test server must not also be a default constructor.
  // explicit Server(std::chrono::milliseconds grace = 120ms, size_t state_bytes = 17,
  explicit Server(std::chrono::milliseconds grace, size_t state_bytes = 17,
                  size_t snapshot_limit = 1024*1024, bool initial_loading = false)
      : state_bytes_(state_bytes), server_(io_, 0, config(), callbacks(),
        [this] { owner();fs::BotGameSnapshot state;state.num_slots=2;
                 state.player_positions={0,0,0,0};state.unavailable_slots=3;return state; },
        limits(grace, snapshot_limit, initial_loading)) {
    frames_ = std::thread([this] {
      owner_ = std::this_thread::get_id();frame_ready_.store(true,std::memory_order_release);
      try { server_.run_frame_loop(); } catch (...) { frame_error_=std::current_exception();server_.stop(); }
    });
    network_ = std::thread([this] {
      try { io_.run(); } catch (...) { network_error_=std::current_exception();server_.stop(); }
    });
    until([&] { return frame_ready_.load(std::memory_order_acquire); }, "Frame owner startup");
  }
  ~Server() { stop(); }
  Server(const Server&) = delete;Server& operator=(const Server&) = delete;
  Server(Server&&) = delete;Server& operator=(Server&&) = delete;
  void stop() { server_.stop();if(frames_.joinable())frames_.join();if(network_.joinable())network_.join(); }
  void check() {
    stop();
    if(frame_error_)std::rethrow_exception(frame_error_);
    if(network_error_)std::rethrow_exception(network_error_);
    require(owner_calls_>0, "No owner callback executed");
  }
  unsigned short port() const { return server_.port(); }
  auto stats() const { return server_.stats(); }
 private:
  static fs::MultiplayerConfig config() {
    fs::MultiplayerConfig value;value.native_product=true;value.frame_rate_hz=50;value.render=false;return value;
  }
  static fs::EngineTCPServerLimits limits(std::chrono::milliseconds grace,size_t snapshot_limit,bool initial_loading) {
    fs::EngineTCPServerLimits value;value.recovery_grace=grace;value.ready_timeout=2s;
    value.idle_timeout=2s;value.snapshot_bytes=snapshot_limit;
    if(initial_loading) { value.ready_timeout=120ms;value.loading_timeout=600ms;value.idle_timeout=120ms; }
    return value;
  }
  void owner() {
    if (std::this_thread::get_id()!=owner_) throw std::runtime_error("Engine callback ran on IO thread");
    ++owner_calls_;
  }
  fs::EngineCallbacks callbacks() {
    fs::EngineCallbacks value;
    value.compute_hash=[this] { owner();return uint64_t{7}+frame_; };
    value.step_frame=[this](std::span<const fs::SlotInput>) { owner();++frame_; };
    value.save_state=[this] { owner();return fs::StateBlob(state_bytes_,17); };
    return value;
  }
  asio::io_context io_;
  const size_t state_bytes_;
  std::thread::id owner_;
  unsigned frame_=0,owner_calls_=0;
  std::atomic<bool> frame_ready_{false};
  fs::EngineTCPServer server_;
  std::exception_ptr frame_error_,network_error_;
  std::thread frames_,network_;
};
class Peer {
 public:
  Peer() = delete;
  explicit Peer(unsigned short port) : socket_(io_) {
    socket_.connect({asio::ip::address_v4::loopback(),port});socket_.non_blocking(true);
  }
  ~Peer() = default;
  Peer(const Peer&) = delete;Peer& operator=(const Peer&) = delete;
  Peer(Peer&&) = delete;Peer& operator=(Peer&&) = delete;
  void close() { boost::system::error_code ignored;socket_.close(ignored); }
  void send(const fs::NativeRecoveryPacket& packet) {
    const auto bytes=packet.view();size_t at=0;
    until([&] {
      boost::system::error_code ec;
      at+=socket_.write_some(asio::buffer(bytes.data()+at,bytes.size()-at),ec);
      if(ec && ec!=asio::error::would_block && ec!=asio::error::try_again)
        throw std::runtime_error("Peer send failed");
      return at==bytes.size();
    },"Peer write timed out");
  }
  // 2026-09-15: deliver complete buffered records before observing transport EOF.
  // A server may coalesce its final control records and close before the next read.
  // std::vector<uint8_t> read() {
  // size_t need=0;
  // until([&] {
  // std::array<uint8_t,4096> buffer{};boost::system::error_code ec;
  // const size_t received=socket_.read_some(asio::buffer(buffer),ec);
  // if(ec && ec!=asio::error::would_block && ec!=asio::error::try_again)
  // throw std::runtime_error("Peer read closed before expected packet");
  // require(fs::AppendBoundedBytes(receive_,buffer.data(),received,2*1024*1024),"Receive budget");
  // if(receive_.empty())return false;
  // // 2026-09-15: tests also receive the bounded cancellation acknowledgement.
  // // if(receive_[0]>=80 && receive_[0]<=90)
  // if(receive_[0]>=80 && receive_[0]<=92) {
  // const int size=fs::native_recovery_wire::record_size(receive_);
  // require(size>=0,"Malformed recovery header");need=size;
  // } else if(receive_[0]==3) need=27;
  // else if(receive_[0]==4) need=13;
  // else if(receive_[0]==8) need=9;
  // else if(receive_[0]==10 || receive_[0]==11)need=7;
  // else throw std::runtime_error("Unknown server record");
  // return need && receive_.size()>=need;
  // },"Expected packet not received");
  // std::vector<uint8_t> result(receive_.begin(),receive_.begin()+need);
  // receive_.erase(receive_.begin(),receive_.begin()+need);return result;
  // }
  // Observe the actual remote half-close so terminal-stream regression is deterministic.
  void wait_for_fin() {
    pollfd descriptor{socket_.native_handle(),POLLRDHUP,0};
    const int count=::poll(&descriptor,1,3000);
    require(count==1 && (descriptor.revents&POLLRDHUP),"Remote FIN was not observed");
  }
  std::vector<uint8_t> read() {
    size_t need=0;
    auto complete = [&] {
      if(receive_.empty())return false;
      // 2026-09-15: tests also receive the bounded cancellation acknowledgement.
      // if(receive_[0]>=80 && receive_[0]<=90)
      if(receive_[0]>=80 && receive_[0]<=92) {
        const int size=fs::native_recovery_wire::record_size(receive_);
        require(size>=0,"Malformed recovery header");need=size;
      } else if(receive_[0]==3) need=27;
      else if(receive_[0]==4) need=13;
      else if(receive_[0]==8) need=9;
      else if(receive_[0]==10 || receive_[0]==11)need=7;
      else throw std::runtime_error("Unknown server record");
      return need && receive_.size()>=need;
    };
    until([&] {
      if (complete()) return true;
      std::array<uint8_t,4096> buffer{};boost::system::error_code ec;
      const size_t received=socket_.read_some(asio::buffer(buffer),ec);
      require(fs::AppendBoundedBytes(receive_,buffer.data(),received,2*1024*1024),"Receive budget");
      if (complete()) return true;
      if(ec && ec!=asio::error::would_block && ec!=asio::error::try_again)
        throw std::runtime_error("Peer read closed before expected packet: buffered="+std::to_string(receive_.size()));
      return false;
    },"Expected packet not received");
    std::vector<uint8_t> result(receive_.begin(),receive_.begin()+need);
    receive_.erase(receive_.begin(),receive_.begin()+need);return result;
  }

  std::vector<uint8_t> kind(fs::NativeRecoveryKind expected) {
    for(unsigned n=0;n<200;++n) { auto bytes=read();if(bytes[0]==static_cast<uint8_t>(expected))return bytes; }
    throw std::runtime_error("Expected recovery control absent");
  }
  fs::NativeRecoverySession hello() {
    send(fs::pack_recovery_hello());return session();
  }
  fs::NativeRecoverySession session() {
    const auto result=fs::decode_recovery_session(kind(fs::NativeRecoveryKind::Session));
    require(result.has_value(),"Invalid session");return *result;
  }
  void ready(const fs::NativeRecoveryGrant& grant, uint64_t hash=7) {
    fs::NativeRecoveryReady proof;proof.grant=grant;proof.state_hash=hash;
    send(fs::pack_recovery_ready(proof));
  }
  void reject(fs::NativeRecoveryReject expected) {
    const auto decoded=fs::decode_recovery_rejected(kind(fs::NativeRecoveryKind::Rejected));
    require(decoded && *decoded==expected,"Wrong rejection");
  }
 private:
  asio::io_context io_;
  tcp::socket socket_;
  std::vector<uint8_t> receive_;
};
