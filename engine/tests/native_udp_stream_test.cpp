#include "frame_sync/native_udp_stream.hpp"
#include "frame_sync/bounded_tcp_writer.hpp"
#include <gtest/gtest.h>
#include <future>
#include <thread>
#include <tuple>
#include <poll.h>
#include <cerrno>
#include <source_location>
using namespace std::chrono_literals;
namespace frame_sync {
namespace {
using Error=boost::system::error_code;
using Outcome=std::shared_ptr<std::tuple<int,Error,size_t>>;
using Buffer=std::shared_ptr<std::vector<uint8_t>>;
using Reading=std::pair<Buffer,Outcome>;
Outcome outcome(){return std::make_shared<std::tuple<int,Error,size_t>>();}
void finish(const Outcome& out,Error error,size_t bytes) {
  ++std::get<0>(*out);std::get<1>(*out)=error;std::get<2>(*out)=bytes;
}
class StreamPair : public testing::Test {
 public:
  StreamPair()=default;~StreamPair() override=default;
  StreamPair(const StreamPair&)=delete;StreamPair& operator=(const StreamPair&)=delete;
  StreamPair(StreamPair&&)=delete;StreamPair& operator=(StreamPair&&)=delete;
 protected:
  void SetUp() override {
    wire_left=std::make_shared<udp::socket>(io,udp::endpoint(asio::ip::make_address("127.0.0.1"),0));
    wire_right=std::make_shared<udp::socket>(io,udp::endpoint(asio::ip::make_address("127.0.0.1"),0));
    wire_left->non_blocking(true);wire_right->non_blocking(true);Open();
  }
  void TearDown() override {
    if(left)left->close();if(right)right->close();
    io.restart();io.poll();left.reset();right.reset();io.restart();io.poll();
  }
  static ReliableUDPConnection Id(uint8_t seed) {ReliableUDPConnection id{};id.fill(seed);return id;}
  void Open(NativeUDPStreamLimits a={},NativeUDPStreamLimits b={},uint8_t seed=1) {
    if(left)left->close();if(right)right->close();io.restart();io.poll();
    left=std::make_shared<NativeUDPSocket>(wire_left,wire_right->local_endpoint(),owner,Id(seed),a,[this]{return now;});
    right=std::make_shared<NativeUDPSocket>(wire_right,wire_left->local_endpoint(),owner,Id(seed),b,[this]{return now;});
    lc=left->control();rc=right->control();
  }
  // 2026-09-15: retain the previous immediate-read assumption for review.
  //   static std::pair<udp::endpoint,std::vector<uint8_t>> Extract(udp::socket& socket) {
  //     if(!socket.available())throw std::runtime_error("Expected actual UDP datagram absent");
  //     std::vector<uint8_t> data(1201);udp::endpoint from;
  //     const size_t size=socket.receive_from(asio::buffer(data),from);data.resize(size);
  //     return {from,std::move(data)};
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
  void Deliver(const NativeUDPSocket::Control& target,udp::endpoint from,std::vector<uint8_t> bytes) {
    asio::post(owner,[target,from=std::move(from),bytes=std::move(bytes)]{target.Deliver(from,bytes);});
    io.restart();io.poll();
  }
  void Pump(bool transfer=true) {
    io.restart();io.poll();
    if(transfer) {
      asio::post(owner,[this] {
        if(wire_right->available()) {auto [from,bytes]=Extract(*wire_right);max_wire=std::max(max_wire,bytes.size());++wire_packets;rc.Deliver(from,bytes);}
        if(wire_left->available()) {auto [from,bytes]=Extract(*wire_left);max_wire=std::max(max_wire,bytes.size());++wire_packets;lc.Deliver(from,bytes);}
      });
      io.restart();io.poll();
    }
    if(auto stats=lc.Stats())peak_pending=std::max(peak_pending,stats->pending_packets);
  }
  template<class Predicate> void Until(Predicate ready,bool transfer=true) {
    const auto deadline=std::chrono::steady_clock::now()+15s;
    while(!ready() && std::chrono::steady_clock::now()<deadline){Pump(transfer);std::this_thread::sleep_for(1ms);}
    ASSERT_TRUE(ready())<<"Bounded UDP stream completion deadline";
  }
  void Advance(std::chrono::milliseconds duration) {
    now+=duration;
    asio::post(owner,[a=lc,b=rc]{a.Tick();b.Tick();});Pump(false);
  }
  static Outcome WriteSome(NativeUDPSocket& stream,std::string text) {
    auto bytes=std::make_shared<std::string>(std::move(text));auto out=outcome();
    stream.async_write_some(asio::buffer(*bytes),[bytes,out](Error error,size_t n){finish(out,error,n);});
    return out;
  }
  static Reading ReadSome(NativeUDPSocket& stream,size_t size) {
    auto bytes=std::make_shared<std::vector<uint8_t>>(size);auto out=outcome();
    stream.async_read_some(asio::buffer(*bytes),[bytes,out](Error error,size_t n){finish(out,error,n);});
    return {bytes,out};
  }
  static std::string Text(const Reading& read) {
    return {read.first->begin(),read.first->begin()+std::get<2>(*read.second)};
  }
  asio::io_context io;
  NativeUDPSocket::executor_type owner=asio::make_strand(io);
  std::shared_ptr<udp::socket> wire_left,wire_right;
  std::shared_ptr<NativeUDPSocket> left,right;
  NativeUDPSocket::Control lc,rc;
  ReliableUDPChannel::Clock::time_point now{};
  size_t max_wire=0,wire_packets=0,peak_pending=0,readiness_waits=0;
  std::chrono::microseconds::rep max_readiness_wait_us=0;
};
#include "fixtures/native_udp/stream/data_cases.inc"
#include "fixtures/native_udp/stream/lifetime_cases.inc"
#include "fixtures/native_udp/stream/failure_cases.inc"
} // namespace
} // namespace frame_sync
