// 2026-09-14: Real TCP lifecycle with short configured leases and checked frame-owner callbacks.
#include "frame_sync/engine_tcp_server.hpp"
#include <iostream>
#include <thread>
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
                  size_t snapshot_limit = 1024*1024)
      : state_bytes_(state_bytes), server_(io_, 0, config(), callbacks(),
        [this] { owner();fs::BotGameSnapshot state;state.num_slots=2;
                 state.player_positions={0,0,0,0};state.unavailable_slots=3;return state; },
        limits(grace, snapshot_limit)) {
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
  static fs::EngineTCPServerLimits limits(std::chrono::milliseconds grace,size_t snapshot_limit) {
    fs::EngineTCPServerLimits value;value.recovery_grace=grace;value.ready_timeout=2s;
    value.idle_timeout=2s;value.snapshot_bytes=snapshot_limit;return value;
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
  std::vector<uint8_t> read() {
    size_t need=0;
    until([&] {
      std::array<uint8_t,4096> buffer{};boost::system::error_code ec;
      const size_t received=socket_.read_some(asio::buffer(buffer),ec);
      if(ec && ec!=asio::error::would_block && ec!=asio::error::try_again)
        throw std::runtime_error("Peer read closed before expected packet");
      require(fs::AppendBoundedBytes(receive_,buffer.data(),received,2*1024*1024),"Receive budget");
      if(receive_.empty())return false;
      if(receive_[0]>=80 && receive_[0]<=87) {
        const int size=fs::native_recovery_wire::record_size(receive_);
        require(size>=0,"Malformed recovery header");need=size;
      } else if(receive_[0]==3) need=27;
      else if(receive_[0]==4) need=13;
      else if(receive_[0]==8) need=9;
      else if(receive_[0]==10 || receive_[0]==11)need=7;
      else throw std::runtime_error("Unknown server record");
      return need && receive_.size()>=need;
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
void pregame_expiry() {
  Server server(120ms);
  Peer first(server.port());const auto admission=first.hello();require(admission.grant.slot==0,"First slot");
  first.close();
  until([&]{return server.stats().active_connections==0;},"Initial disconnect");
  require(server.stats().connections==1,"Pregame reservation freed immediately");
  Peer resumed(server.port());resumed.send(fs::pack_recovery_resume(admission.grant));const auto recovery=resumed.session();
  require(recovery.restoring && recovery.grant.slot==0 && recovery.grant.generation>admission.grant.generation,
          "Pregame reservation not transferred");
  resumed.close();
  until([&]{return server.stats().connections==0;},"Pregame lease not cleaned");
  Peer replacement(server.port());const auto fresh=replacement.hello();
  require(fresh.grant.slot==0 && fresh.grant.generation>recovery.grant.generation &&
          !fs::native_secret_equal(fresh.grant.secret,recovery.grant.secret),"Expired slot reused old ownership");
  Peer replay(server.port());replay.send(fs::pack_recovery_resume(recovery.grant));
  replay.reject(fs::NativeRecoveryReject::Unauthorized);
  require(server.stats().next_frame==0,"Unready lease advanced match");
  server.check();
}
void invalid_ready_release() {
  // 2026-09-14: supply the lease explicitly after removing the ambiguous constructor default.
  // Server server;
  Server server(120ms);
  Peer bad(server.port());const auto previous=bad.hello();bad.ready(previous.grant,8);
  bad.reject(fs::NativeRecoveryReject::InvalidState);
  Peer replacement(server.port());const auto next=replacement.hello();
  require(next.grant.slot==0 && next.grant.generation>previous.grant.generation,"Invalid Ready retained seat");
  Peer replay(server.port());replay.send(fs::pack_recovery_resume(previous.grant));
  replay.reject(fs::NativeRecoveryReject::Unauthorized);
  server.check();
}
void sealed_expiry() {
  Server server(80ms);
  Peer first(server.port());const auto initial=first.hello();first.ready(initial.grant);
  const auto accepted=fs::decode_recovery_accepted(first.kind(fs::NativeRecoveryKind::Accepted));
  require(accepted && accepted->second==0,"Initial acceptance not at frame zero");
  Peer late(server.port());late.send(fs::pack_recovery_hello());late.reject(fs::NativeRecoveryReject::Busy);
  first.close();
  until([&]{return server.stats().next_frame>=10;},"Offline authority stalled");
  Peer expired(server.port());expired.send(fs::pack_recovery_resume(initial.grant));
  expired.reject(fs::NativeRecoveryReject::Unauthorized);
  require(server.stats().bot_slots==1,"Expired started seat lost AI ownership");
  server.check();
}
void retries_do_not_extend_grace() {
  Server server(140ms,1024*1024);
  Peer first(server.port());auto grant=first.hello().grant;first.ready(grant);
  first.kind(fs::NativeRecoveryKind::Accepted);first.close();
  const auto offline=std::chrono::steady_clock::now();
  for(unsigned attempt=0;attempt<3;++attempt) {
    Peer retry(server.port());retry.send(fs::pack_recovery_resume(grant));const auto session=retry.session();
    require(session.restoring && session.grant.generation>grant.generation,"Retry ownership unchanged");
    grant=session.grant;
    const auto metadata=fs::decode_recovery_snapshot(retry.kind(fs::NativeRecoveryKind::Snapshot));
    require(metadata && metadata->size==1024*1024,"Maximum snapshot path not exercised");
    retry.close();
  }
  std::this_thread::sleep_until(offline+220ms);
  Peer expired(server.port());expired.send(fs::pack_recovery_resume(grant));
  expired.reject(fs::NativeRecoveryReject::Unauthorized);
  require(server.stats().next_frame>=8,"Repeated retry stalled authority");
  server.check();
}
void snapshot_rejection_is_local() {
  Server server(2s,4096,1024);
  Peer first(server.port()),other(server.port());
  const auto a=first.hello(),b=other.hello();first.ready(a.grant);other.ready(b.grant);
  first.kind(fs::NativeRecoveryKind::Accepted);other.kind(fs::NativeRecoveryKind::Accepted);
  first.close();
  Peer retry(server.port());retry.send(fs::pack_recovery_resume(a.grant));retry.session();
  retry.reject(fs::NativeRecoveryReject::SnapshotUnavailable);
  until([&]{return server.stats().next_frame>=10;},"Oversized snapshot stopped other player");
  require(server.stats().snapshot_rejections==1 && server.stats().active_connections==1 &&
          server.stats().bot_slots==1,"Snapshot rejection affected healthy player");
  server.check();
}
int main() {
  try {
    pregame_expiry();invalid_ready_release();sealed_expiry();retries_do_not_extend_grace();snapshot_rejection_is_local();
    std::cout<<"{\"passed\":true,\"checks\":5,\"assertions\":"<<assertions
      <<",\"skipped\":0,\"real_tcp\":true,\"frame_owner_checked\":true,\"actual_gameenv\":false}\n";
  } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
