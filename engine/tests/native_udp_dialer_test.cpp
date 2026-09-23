#include "frame_sync/native_udp_dialer.hpp"
#include "frame_sync/native_udp_listener.hpp"
#include "frame_sync/bounded_tcp_writer.hpp"
#include <gtest/gtest.h>
#include <thread>
#include <tuple>
#include <future>
using namespace std::chrono_literals;
namespace frame_sync {
namespace {
using Error=boost::system::error_code;
using Outcome=std::shared_ptr<std::tuple<int,Error,size_t>>;
using Reading=std::pair<std::shared_ptr<std::vector<uint8_t>>,Outcome>;
Outcome outcome(){return std::make_shared<std::tuple<int,Error,size_t>>();}
void finish(Outcome out,Error error,size_t size){++std::get<0>(*out);std::get<1>(*out)=error;std::get<2>(*out)=size;}
struct Connected {
  int calls=0;Error error;
  std::unique_ptr<NativeUDPSocket> socket;
  Connected()=default;~Connected()=default;
  Connected(const Connected&)=delete;Connected& operator=(const Connected&)=delete;
  Connected(Connected&&)=default;Connected& operator=(Connected&&)=default;
};
class Relay {
 public:
  Relay(asio::io_context& io,udp::endpoint server)
    :down(io,udp::endpoint(asio::ip::make_address("127.0.0.1"),0)),
     up(io,udp::endpoint(asio::ip::make_address("127.0.0.1"),0)),server(std::move(server)) {
    down.non_blocking(true);up.non_blocking(true);
  }
  Relay()=delete;~Relay()=default;
  Relay(const Relay&)=delete;Relay& operator=(const Relay&)=delete;
  Relay(Relay&&)=delete;Relay& operator=(Relay&&)=delete;
  bool Drop(std::span<const uint8_t> packet,bool from_client) {
    if(auto record=native_udp_bootstrap::decode(packet)) {
      const auto bit=1u<<static_cast<unsigned>(record->kind);
      if(drop_bootstrap_once&bit){drop_bootstrap_once&=~bit;++dropped;return true;}
    }
    if(!packet.empty() && from_client && packet[0]==kReliableUDP_SessionData && drop_client_data) {
      drop_client_data=false;++dropped;return true;
    }
    if(!packet.empty() && !from_client && packet[0]==kReliableUDP_SessionAck && drop_server_ack) {
      drop_server_ack=false;++dropped;return true;
    }
    return false;
  }
  void Pump() {
    for(unsigned i=0;i<8 && down.available();++i) {
      auto [source,bytes]=Extract(down);client=source;max_wire=std::max(max_wire,bytes.size());
      if(!Drop(bytes,true))up.send_to(asio::buffer(bytes),server);
    }
    for(unsigned i=0;i<8 && up.available();++i) {
      auto [source,bytes]=Extract(up);if(source!=server || !client)continue;
      max_wire=std::max(max_wire,bytes.size());
      if(hold_server_data && !bytes.empty() && bytes[0]==kReliableUDP_SessionData) {
        held_server_data=std::move(bytes);continue;
      }
      if(!Drop(bytes,false))down.send_to(asio::buffer(bytes),*client);
    }
  }
  static std::pair<udp::endpoint,std::vector<uint8_t>> Extract(udp::socket& socket) {
    std::vector<uint8_t> bytes(65536);udp::endpoint source;
    const auto n=socket.receive_from(asio::buffer(bytes),source);bytes.resize(n);
    return {source,std::move(bytes)};
  }
  udp::socket down,up;
  const udp::endpoint server;
  std::optional<udp::endpoint> client;
  unsigned drop_bootstrap_once=0;
  bool drop_client_data=false,drop_server_ack=false;
  size_t dropped=0,max_wire=0;
  bool hold_server_data=false;
  std::vector<uint8_t> held_server_data;
};
class DialFixture : public testing::Test {
 public:
  DialFixture()=default;~DialFixture() override=default;
  DialFixture(const DialFixture&)=delete;DialFixture& operator=(const DialFixture&)=delete;
  DialFixture(DialFixture&&)=delete;DialFixture& operator=(DialFixture&&)=delete;
 protected:
  void SetUp() override {
    listener=std::make_unique<NativeUDPAcceptor>(io,
      udp::endpoint(asio::ip::make_address("127.0.0.1"),0),NativeUDPListenerLimits{},
      [this]{return Now()+std::chrono::milliseconds(server_epoch);});
    ResetDialer({});
    Pulse();
  }
  void TearDown() override {
    if(dialer)dialer->Cancel();if(listener)listener->close();Pulse();
    dialer.reset();listener.reset();Pulse();relay.reset();Pulse();
  }
  ReliableUDPChannel::Clock::time_point Now() const {
    return ReliableUDPChannel::Clock::now()+std::chrono::milliseconds(offset.load());
  }
  void ResetDialer(NativeUDPDialLimits limits) {
    if(dialer){dialer->Cancel();Pulse();dialer.reset();Pulse();}
    dialer=std::make_unique<NativeUDPDialer>(io,limits,[this]{return Now();});
  }
  void Pulse() {
    if(relay)relay->Pump();io.restart();io.poll();
    if(relay)relay->Pump();io.restart();io.poll();
  }
  template<class Predicate> void Until(Predicate ready) {
    const auto deadline=std::chrono::steady_clock::now()+10s;
    while(!ready() && std::chrono::steady_clock::now()<deadline){Pulse();std::this_thread::sleep_for(1ms);}
    if(!ready())throw std::runtime_error("Bounded actual UDP dial completion deadline");
  }
  void Advance(std::chrono::milliseconds value) {
    offset.fetch_add(value.count());std::this_thread::sleep_for(30ms);Pulse();
  }
  std::shared_ptr<Connected> Accept() {
    auto result=std::make_shared<Connected>();
    listener->async_accept([result](Error e,NativeUDPSocket socket) {
      ++result->calls;result->error=e;
      if(!e)result->socket=std::make_unique<NativeUDPSocket>(std::move(socket));
    });
    return result;
  }
  std::shared_ptr<Connected> Dial(udp::endpoint endpoint) {
    auto result=std::make_shared<Connected>();
    dialer->async_connect(endpoint.address().to_string(),endpoint.port(),[result](Error e,NativeUDPSocket socket) {
      ++result->calls;result->error=e;
      if(!e)result->socket=std::make_unique<NativeUDPSocket>(std::move(socket));
    });
    return result;
  }
  std::shared_ptr<Connected> Dial(NativeUDPEndpoints endpoints) {
    auto result=std::make_shared<Connected>();
    dialer->async_connect(std::move(endpoints),[result](Error e,NativeUDPSocket socket) {
      ++result->calls;result->error=e;
      if(!e)result->socket=std::make_unique<NativeUDPSocket>(std::move(socket));
    });
    return result;
  }
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
  asio::io_context io;
  std::atomic<int64_t> offset{0};
  int64_t server_epoch=0;
  std::unique_ptr<NativeUDPAcceptor> listener;
  std::unique_ptr<NativeUDPDialer> dialer;
  std::unique_ptr<Relay> relay;
};
#include "fixtures/native_udp/dialer/connect_cases.inc"
#include "fixtures/native_udp/dialer/data_cases.inc"
#include "fixtures/native_udp/dialer/lifetime_cases.inc"
} // namespace
} // namespace frame_sync
