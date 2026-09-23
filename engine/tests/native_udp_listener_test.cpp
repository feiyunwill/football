#include "frame_sync/native_udp_listener.hpp"
#include "frame_sync/bounded_tcp_writer.hpp"
#include <gtest/gtest.h>
#include <thread>
#include <tuple>
#include <future>
#include <poll.h>
#include <cerrno>
#include <source_location>
using namespace std::chrono_literals;
namespace frame_sync {
namespace {
using Error=boost::system::error_code;
using Outcome=std::shared_ptr<std::tuple<int,Error,size_t>>;
using Reading=std::pair<std::shared_ptr<std::vector<uint8_t>>,Outcome>;
Outcome outcome(){return std::make_shared<std::tuple<int,Error,size_t>>();}
void finish(Outcome out,Error error,size_t size){++std::get<0>(*out);std::get<1>(*out)=error;std::get<2>(*out)=size;}
struct Accepted {
  int calls=0;Error error;
  std::unique_ptr<NativeUDPSocket> socket;
  Accepted()=default;~Accepted()=default;
  Accepted(const Accepted&)=delete;Accepted& operator=(const Accepted&)=delete;
  Accepted(Accepted&&)=default;Accepted& operator=(Accepted&&)=default;
};
struct Peer {
  Peer(asio::io_context& io,udp::endpoint server,NativeUDPSocket::executor_type owner,
       ReliableUDPChannel::NowFn clock)
    :wire(std::make_shared<udp::socket>(io,udp::endpoint(asio::ip::make_address("127.0.0.1"),0))),
     server(std::move(server)),owner(std::move(owner)),clock(std::move(clock)) {
    wire->non_blocking(true);Reset();
  }
  Peer()=delete;~Peer()=default;
  Peer(const Peer&)=delete;Peer& operator=(const Peer&)=delete;
  Peer(Peer&&)=delete;Peer& operator=(Peer&&)=delete;
  void Reset() {
    stream.reset();local_time=0;
    attempt=std::make_unique<NativeUDPBootstrapAttempt>(*native_udp_bootstrap::address(server),local_time,30000);
    confirm={};
  }
  void Send(std::span<const uint8_t> bytes){wire->send_to(asio::buffer(bytes.data(),bytes.size()),server);}
  std::shared_ptr<udp::socket> wire;
  const udp::endpoint server;
  const NativeUDPSocket::executor_type owner;
  const ReliableUDPChannel::NowFn clock;
  std::unique_ptr<NativeUDPBootstrapAttempt> attempt;
  std::unique_ptr<NativeUDPSocket> stream;
  NativeUDPBootstrapPacket confirm{};
  uint64_t local_time=0;
};
class ListenerFixture : public testing::Test {
 public:
  ListenerFixture()=default;~ListenerFixture() override=default;
  ListenerFixture(const ListenerFixture&)=delete;ListenerFixture& operator=(const ListenerFixture&)=delete;
  ListenerFixture(ListenerFixture&&)=delete;ListenerFixture& operator=(ListenerFixture&&)=delete;
 protected:
  void SetUp() override{Open({});}
  void TearDown() override {
    for(auto& peer:peers)if(peer->stream)peer->stream->close();
    if(listener)listener->close();
    io.restart();io.poll();peers.clear();listener.reset();io.restart();io.poll();
  }
  void Open(NativeUDPListenerLimits limits) {
    if(listener) {listener->close();io.restart();io.poll();listener.reset();}
    listener=std::make_unique<NativeUDPAcceptor>(io,
      udp::endpoint(asio::ip::make_address("127.0.0.1"),0),limits,[this]{return now;});
    io.restart();io.poll();
  }
  Peer& NewPeer() {
    peers.push_back(std::make_unique<Peer>(io,listener->local_endpoint(),owner,[this]{return now;}));
    return *peers.back();
  }
  // 2026-09-15: actual socket readiness is not implied by one io_context.poll.
  //   static std::pair<udp::endpoint,std::vector<uint8_t>> Extract(udp::socket& socket) {
  //     if(!socket.available())throw std::runtime_error("Expected actual UDP packet absent");
  //     std::vector<uint8_t> bytes(65536);udp::endpoint source;
  //     const auto n=socket.receive_from(asio::buffer(bytes),source);bytes.resize(n);
  //     return {source,std::move(bytes)};
  //   }
  std::pair<udp::endpoint,std::vector<uint8_t>> Extract(udp::socket& socket,
      std::source_location location=std::source_location::current()) {
    const auto started=std::chrono::steady_clock::now();
    const auto deadline=started+2s;
    if(!socket.available()) {
      ++readiness_waits;
      for(;;) {
        const auto remaining=deadline-std::chrono::steady_clock::now();
        if(remaining<=0ms)throw std::runtime_error(
          std::string("Actual UDP datagram readiness timeout at ")+location.file_name()+":"+
          std::to_string(location.line()));
        pollfd ready{socket.native_handle(),POLLIN,0};
        const int result=::poll(&ready,1,static_cast<int>(
          std::chrono::ceil<std::chrono::milliseconds>(remaining).count()));
        if(result<0 && errno==EINTR)continue;
        if(result<0)throw std::system_error(errno,std::generic_category(),"UDP fixture poll");
        if(result>0 && (ready.revents&POLLIN))break;
        if(result>0)throw std::runtime_error("UDP fixture descriptor failed");
      }
      max_readiness_wait_us=std::max(max_readiness_wait_us,
        std::chrono::duration_cast<std::chrono::microseconds>(
          std::chrono::steady_clock::now()-started).count());
      RecordProperty("readiness_waits",std::to_string(readiness_waits));
      RecordProperty("max_readiness_wait_us",std::to_string(max_readiness_wait_us));
    }
    std::vector<uint8_t> data(1201);udp::endpoint from;
    const size_t size=socket.receive_from(asio::buffer(data),from);data.resize(size);
    return {from,std::move(data)};
  }
  void Pulse(bool clients=true) {
    // 2026-09-16: real transfer uses real elapsed time so genuine UDP loss can
    // exercise both retransmission owners within the original ten-second bound.
    if(realtime_transfer)
      now=ReliableUDPChannel::Clock::time_point(100ms)+(ReliableUDPChannel::Clock::now()-realtime_origin);
    io.restart();io.poll();
    if(clients) {
      // 2026-09-21: retain prior one-packet-per-poll manual client owner.
      //       for(auto& p:peers) {
      //         // The fixture is the client's receive/retransmit owner.
      //         if(realtime_transfer && p->stream) {
      //           auto control=p->stream->control();asio::post(owner,[control]{control.Tick();});
      //         }
      //         if(!p->stream || !p->wire->available())continue;
      //         auto [source,bytes]=Extract(*p->wire);auto control=p->stream->control();
      //         asio::post(owner,[control,source,bytes=std::move(bytes)]{control.Deliver(source,bytes);});
      //       }
      for(auto& p:peers) {
        if(!p->stream)continue;
        auto control=p->stream->control();
        // The real dialer continuously arms async_receive_from. Drain a bounded
        // batch in this manual peer before ticking, so queued ACKs are consumed
        // without a synthetic one-packet-per-millisecond rate limit.
        const unsigned budget=realtime_transfer ? 64u : 1u;
        for(unsigned i=0;i<budget && p->wire->available();++i) {
          auto [source,bytes]=Extract(*p->wire);
          asio::post(owner,[control,source,bytes=std::move(bytes)]{control.Deliver(source,bytes);});
        }
        if(realtime_transfer)asio::post(owner,[control]{control.Tick();});
      }
      io.restart();io.poll();
    }
  }
  // 2026-09-15: include the calling operation in bounded fixture failures.
  // template<class Predicate> void Until(Predicate ready,bool clients=true) {
  template<class Predicate> void Until(Predicate ready,bool clients=true,
      std::source_location location=std::source_location::current()) {
    const auto deadline=std::chrono::steady_clock::now()+10s;
    while(!ready() && std::chrono::steady_clock::now()<deadline){Pulse(clients);std::this_thread::sleep_for(1ms);}
    // 2026-09-15: ASSERT_TRUE(ready())<<"Bounded actual listener completion deadline";
    ASSERT_TRUE(ready())<<"Bounded actual listener completion deadline at "<<location.file_name()<<":"<<location.line()
      <<" ignored="<<listener->stats().ignored<<" rejected="<<listener->stats().rejected
      <<" open="<<listener->is_open();
  }
  void Advance(std::chrono::milliseconds value,bool clients=true) {
    now+=value;std::this_thread::sleep_for(30ms);Pulse(clients);
  }
  std::shared_ptr<Accepted> AcceptOne() {
    auto result=std::make_shared<Accepted>();
    listener->async_accept([result](Error error,NativeUDPSocket socket) {
      ++result->calls;result->error=error;
      if(!error)result->socket=std::make_unique<NativeUDPSocket>(std::move(socket));
    });
    return result;
  }
  void Challenge(Peer& peer) {
    auto hello=peer.attempt->next_packet(peer.local_time);ASSERT_TRUE(hello);peer.Send(*hello);
    Until([&]{return peer.wire->available()>0;},false);
    auto [source,bytes]=Extract(*peer.wire);ASSERT_EQ(source,peer.server);
    EXPECT_FALSE(peer.attempt->receive(bytes,*native_udp_bootstrap::address(source),peer.local_time));
    ASSERT_EQ(peer.attempt->state(),NativeUDPBootstrapAttempt::State::AwaitEstablished);
    peer.confirm=*peer.attempt->next_packet(peer.local_time);
  }
  void Confirm(Peer& peer) {
    peer.Send(peer.confirm);Until([&]{return peer.wire->available()>0;},false);
    auto [source,bytes]=Extract(*peer.wire);ASSERT_EQ(source,peer.server);
    ASSERT_TRUE(peer.attempt->receive(bytes,*native_udp_bootstrap::address(source),peer.local_time));
    ASSERT_TRUE(peer.attempt->connection());
    peer.stream=std::make_unique<NativeUDPSocket>(peer.wire,peer.server,peer.owner,
      peer.attempt->connection(),NativeUDPStreamLimits{},peer.clock);
  }
  void Connect(Peer& peer){Challenge(peer);Confirm(peer);}
  static Outcome WriteSome(NativeUDPSocket& stream,std::string text) {
    auto data=std::make_shared<std::string>(std::move(text));auto result=outcome();
    stream.async_write_some(asio::buffer(*data),[data,result](Error e,size_t n){finish(result,e,n);});return result;
  }
  static Reading ReadSome(NativeUDPSocket& stream,size_t size) {
    auto data=std::make_shared<std::vector<uint8_t>>(size);auto result=outcome();
    stream.async_read_some(asio::buffer(*data),[data,result](Error e,size_t n){finish(result,e,n);});
    return {data,result};
  }
  static std::string Text(const Reading& read){return {read.first->begin(),read.first->begin()+std::get<2>(*read.second)};}
  static std::vector<uint8_t> Packet(const ReliableUDPConnection& id,std::string text,uint32_t seq=0) {
    std::vector<uint8_t> bytes(kReliableUDP_SessionHeaderSize+text.size());
    bytes[0]=kReliableUDP_SessionData;std::copy(id.begin(),id.end(),bytes.begin()+1);
    native_udp_bootstrap::put(bytes.data()+17,seq,4);
    native_udp_bootstrap::put(bytes.data()+21,text.size(),2);
    std::copy(text.begin(),text.end(),bytes.begin()+23);return bytes;
  }
  asio::io_context io;
  NativeUDPSocket::executor_type owner=asio::make_strand(io);
  ReliableUDPChannel::Clock::time_point now=ReliableUDPChannel::Clock::time_point(100ms);
  bool realtime_transfer=false;
  const ReliableUDPChannel::Clock::time_point realtime_origin=ReliableUDPChannel::Clock::now();
  std::unique_ptr<NativeUDPAcceptor> listener;
  std::vector<std::unique_ptr<Peer>> peers;
  size_t readiness_waits=0;
  std::chrono::microseconds::rep max_readiness_wait_us=0;
};
#include "fixtures/native_udp/listener/admission_cases.inc"
#include "fixtures/native_udp/listener/routing_cases.inc"
#include "fixtures/native_udp/listener/lifetime_cases.inc"
} // namespace
} // namespace frame_sync
