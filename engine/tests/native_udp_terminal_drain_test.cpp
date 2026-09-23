// 2026-09-21: actual shared server and UDP dialer, with only an oracle engine.
#include "frame_sync/native_udp_dialer.hpp"
#include "frame_sync/native_udp_listener.hpp"
#include "frame_sync/engine_tcp_server.hpp"
#include <gtest/gtest.h>
#include <future>
#include <thread>
#include <atomic>
using namespace std::chrono_literals;
namespace fs=frame_sync;namespace asio=boost::asio;using udp=asio::ip::udp;
using Error=boost::system::error_code;
class Relay {
 public:
  Relay()=delete;
  Relay(unsigned short upstream,uint8_t terminal,unsigned drops)
   :front_(io_,udp::endpoint(asio::ip::address_v4::loopback(),0)),
    back_(io_,udp::endpoint(asio::ip::address_v4::loopback(),0)),
    upstream_(asio::ip::address_v4::loopback(),upstream),terminal_(terminal),drops_(drops) {
    front_.non_blocking(true);back_.non_blocking(true);thread_=std::thread([this]{run();});
  }
  ~Relay(){stop_.store(true);if(thread_.joinable())thread_.join();}
  Relay(const Relay&)=delete;Relay& operator=(const Relay&)=delete;
  Relay(Relay&&)=delete;Relay& operator=(Relay&&)=delete;
  unsigned short port()const{return front_.local_endpoint().port();}
  unsigned dropped()const{return dropped_.load();}
  bool failed()const{return failed_.load();}
 private:
  void run() noexcept {
   try {
    while(!stop_.load()) {
     for(unsigned direction=0;direction<2;++direction)for(unsigned batch=0;batch<64;++batch) {
      auto& source=direction ? back_:front_;auto& target=direction ? front_:back_;
      std::array<uint8_t,1201> bytes{};udp::endpoint sender;Error error;
      const auto count=source.receive_from(asio::buffer(bytes),sender,0,error);
      if(error==asio::error::would_block || error==asio::error::try_again)break;
      if(error)throw boost::system::system_error(error);
      if(direction==0)client_=sender;
      else if(sender!=upstream_)continue;
      if(direction && count>=24 && bytes[0]==fs::kReliableUDP_SessionData &&
         bytes[23]==terminal_ && dropped_.load()<drops_) {++dropped_;continue;}
      if(direction && !client_.port())continue;
      target.send_to(asio::buffer(bytes.data(),count),direction ? client_:upstream_,0,error);
      if(error)throw boost::system::system_error(error);
     }
     std::this_thread::sleep_for(1ms);
    }
   }catch(...){failed_.store(true);}
  }
  asio::io_context io_;udp::socket front_,back_;udp::endpoint upstream_,client_;
  const uint8_t terminal_;const unsigned drops_;
  std::atomic<unsigned> dropped_{0};std::atomic<bool> stop_{false},failed_{false};std::thread thread_;
};
class Fixture {
 public:
  Fixture()=delete;
  Fixture(uint8_t terminal,unsigned drops)
   :server_(io_,0,config(),callbacks(),[]{fs::BotGameSnapshot value;value.num_slots=3;value.unavailable_slots=7;return value;},limits()),
    relay_(server_.port(),terminal,drops),dialer_(io_) {
   thread_=std::thread([this]{try{io_.run();}catch(...){network_error_.store(true);}});
   auto promise=std::make_shared<std::promise<std::shared_ptr<fs::NativeUDPSocket>>>();auto future=promise->get_future();
   dialer_.async_connect("127.0.0.1",relay_.port(),[promise](Error error,fs::NativeUDPSocket socket){
    if(error)promise->set_exception(std::make_exception_ptr(boost::system::system_error(error)));
    else promise->set_value(std::make_shared<fs::NativeUDPSocket>(std::move(socket)));
   });
   if(future.wait_for(2s)!=std::future_status::ready){stop();throw std::runtime_error("Actual UDP dial timeout");}
   try{socket_=future.get();}catch(...){stop();throw;}
  }
  ~Fixture(){stop();}
  Fixture(const Fixture&)=delete;Fixture& operator=(const Fixture&)=delete;
  Fixture(Fixture&&)=delete;Fixture& operator=(Fixture&&)=delete;
  void stop() {
   if(socket_)socket_->close();dialer_.Cancel();server_.stop();io_.stop();
   if(thread_.joinable())thread_.join();
  }
  void send(const fs::NativeRecoveryPacket& packet) {
   auto bytes=std::make_shared<std::vector<uint8_t>>(packet.view().begin(),packet.view().end());
   auto promise=std::make_shared<std::promise<void>>();auto future=promise->get_future();
   asio::async_write(*socket_,asio::buffer(*bytes),[socket=socket_,bytes,promise](Error error,size_t count){
    if(error || count!=bytes->size())promise->set_exception(std::make_exception_ptr(std::runtime_error("Actual UDP send failed")));
    else promise->set_value();
   });
   if(future.wait_for(2s)!=std::future_status::ready)throw std::runtime_error("Actual UDP send timeout");
   future.get();
  }
  std::vector<uint8_t> read(size_t size) {
   auto bytes=std::make_shared<std::vector<uint8_t>>(size);
   auto promise=std::make_shared<std::promise<bool>>();auto future=promise->get_future();
   asio::async_read(*socket_,asio::buffer(*bytes),[socket=socket_,bytes,promise](Error error,size_t count){
    promise->set_value(!error && count==bytes->size());
   });
   if(future.wait_for(2s)!=std::future_status::ready || !future.get())return {};
   return *bytes;
  }
  std::vector<uint8_t> packet() {
   auto bytes=read(10);if(bytes.empty())return {};
   const auto size=fs::native_recovery_wire::get(bytes,8,2);
   if(size>1090)throw std::runtime_error("Unbounded server control");
   auto body=read(size);if(body.size()!=size)return {};
   bytes.insert(bytes.end(),body.begin(),body.end());return bytes;
  }
  fs::NativeRecoveryGrant admit() {
   send(fs::pack_recovery_load_hello());const auto record=packet();
   const auto value=fs::decode_recovery_session(record);
   if(!value || !value->loading)throw std::runtime_error("Actual UDP loading admission missing");
   return value->grant;
  }
  bool wait_closed() {
   const auto until=std::chrono::steady_clock::now()+3s;
   while(std::chrono::steady_clock::now()<until){
    if(server_.stats().active_connections==0)return true;
    std::this_thread::sleep_for(1ms);
   }
   return false;
  }
  auto stats()const{return server_.stats();}
  unsigned dropped()const{return relay_.dropped();}
  bool clean()const{return !relay_.failed() && !network_error_.load();}
 private:
  static fs::MultiplayerConfig config(){fs::MultiplayerConfig c;c.native_product=true;c.render=false;c.left_agents=1;c.right_agents=2;c.frame_rate_hz=50;return c;}
  static fs::EngineTCPServerLimits limits(){fs::EngineTCPServerLimits l;l.ready_timeout=2s;l.idle_timeout=2s;return l;}
  static fs::EngineCallbacks callbacks(){fs::EngineCallbacks e;e.compute_hash=[]{return uint64_t{7};};e.step_frame=[](std::span<const fs::SlotInput>){};e.save_state=[]{return fs::StateBlob(17,7);};return e;}
  asio::io_context io_;
  fs::BasicEngineSessionServer<fs::NativeUDPTransport> server_;
  Relay relay_;fs::NativeUDPDialer dialer_;std::shared_ptr<fs::NativeUDPSocket> socket_;
  std::thread thread_;std::atomic<bool> network_error_{false};
};
void cancellation(unsigned drops) {
 Fixture peer(std::to_underlying(fs::NativeRecoveryKind::LoadCancelled),drops);
 const auto grant=peer.admit();peer.send(fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancel,grant));
 const auto bytes=peer.packet();const auto result=fs::decode_recovery_load_control(bytes,fs::NativeRecoveryKind::LoadCancelled);
 ASSERT_TRUE(result.has_value())<<"Terminal receipt vanished after application enqueue completed";
 EXPECT_EQ(result->generation,grant.generation);EXPECT_EQ(result->slot,grant.slot);
 EXPECT_TRUE(fs::native_secret_equal(result->match,grant.match));EXPECT_TRUE(fs::native_secret_equal(result->secret,grant.secret));
 EXPECT_EQ(peer.stats().loading_cancellations,1u);EXPECT_TRUE(peer.wait_closed());
 EXPECT_EQ(peer.dropped(),drops);EXPECT_TRUE(peer.clean());
}
TEST(NativeUDPTerminalDrain, CancellationWithoutLoss){cancellation(0);}
TEST(NativeUDPTerminalDrain, CancellationRetransmitsDroppedReceipt){cancellation(1);}
TEST(NativeUDPTerminalDrain, RejectionRetransmitsDroppedReceipt) {
 Fixture peer(std::to_underlying(fs::NativeRecoveryKind::Rejected),1);
 auto grant=peer.admit();grant.secret[0]^=1;
 peer.send(fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancel,grant));
 const auto result=fs::decode_recovery_rejected(peer.packet());
 ASSERT_TRUE(result.has_value())<<"Terminal rejection vanished after application enqueue completed";
 EXPECT_EQ(*result,fs::NativeRecoveryReject::Unauthorized);EXPECT_TRUE(peer.wait_closed());
 EXPECT_EQ(peer.dropped(),1u);EXPECT_TRUE(peer.clean());
}
TEST(NativeUDPTerminalDrain, UnresponsivePeerEventuallyReleasesTransport) {
 Fixture peer(std::to_underlying(fs::NativeRecoveryKind::LoadCancelled),100);
 const auto grant=peer.admit();peer.send(fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancel,grant));
 EXPECT_TRUE(peer.wait_closed());EXPECT_EQ(peer.stats().loading_cancellations,1u);
 EXPECT_GT(peer.dropped(),0u);EXPECT_TRUE(peer.clean());
}

// 2026-09-21: these are the actual product stop-then-io.stop sequences; LSan is
// part of acceptance, including zero dispatches and an outstanding stream read.
TEST(NativeUDPTerminalDrain, StopWithPendingApplicationRead) {
 Fixture peer(std::to_underlying(fs::NativeRecoveryKind::LoadCancelled),0);
 const auto grant=peer.admit();EXPECT_EQ(grant.slot,0u);
 peer.stop();EXPECT_TRUE(peer.clean());
}
TEST(NativeUDPTerminalDrain, StopBeforeFirstDispatch) {
 asio::io_context io;
 fs::MultiplayerConfig config;config.native_product=true;config.frame_rate_hz=50;
 fs::EngineCallbacks engine;engine.compute_hash=[]{return uint64_t{7};};
 engine.step_frame=[](std::span<const fs::SlotInput>){};
 engine.save_state=[]{return fs::StateBlob(17,7);};
 fs::BasicEngineSessionServer<fs::NativeUDPTransport> server(io,0,config,engine,[]{
  fs::BotGameSnapshot value;value.num_slots=2;return value;
 });
 EXPECT_GT(server.port(),0u);server.stop();io.stop();
}
