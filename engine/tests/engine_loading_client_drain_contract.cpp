// 2026-09-15: exercise the actual client, prepared GameEnv and real cancellation socket.
#define main actual_client_program_main
// 2026-09-15: exercise the canonical product implementation.
// #include "integrated_client.cpp"
#include "frame_sync/integrated_client.cpp"
#undef main
#include "frame_sync/engine_tcp_server.hpp"
#include "frame_sync/native_udp_listener.hpp"
#include <iostream>
namespace fs=frame_sync;
using namespace std::chrono_literals;
size_t assertions=0;
void require(bool value,const char* reason) {++assertions;if(!value)throw std::runtime_error(reason);}
enum class Reply { Valid, Secret, Generation, Silent, Closed };
#if defined(FOOTBALL_NATIVE_UDP_CLIENT)
using DrainTransport = fs::NativeUDPTransport;
using DrainClient = IntegratedFrameSyncUDPClient;
#else
using DrainTransport = fs::NativeTCPTransport;
using DrainClient = IntegratedFrameSyncClient;
#endif
class ReplyServer {
 public:
  ReplyServer()=delete;
  explicit ReplyServer(Reply reply):acceptor_(io_,{asio::ip::address_v4::loopback(),0}),reply_(reply) {
   grant_.match.fill(7);grant_.secret.fill(9);grant_.generation=1;grant_.slot=0;
   accept();
   thread_=std::thread([this] {try{io_.run();}catch(...){error_=std::current_exception();io_.stop();}});
  }
  ~ReplyServer(){stop();}
  ReplyServer(const ReplyServer&)=delete;ReplyServer& operator=(const ReplyServer&)=delete;
  ReplyServer(ReplyServer&&)=delete;ReplyServer& operator=(ReplyServer&&)=delete;
  unsigned short port()const{return acceptor_.local_endpoint().port();}
  void stop(){io_.stop();if(thread_.joinable())thread_.join();}
  void check(){
   stop();if(error_)std::rethrow_exception(error_);
   require(connections_==1,"User cancellation reconnected");
   require(cancels_==1,"Actual client did not send exactly one cancellation");
  }
 private:
  void accept() {
// 2026-09-21: share the product session state across TCP and reliable UDP.
//    acceptor_.async_accept([this](boost::system::error_code ec,tcp::socket socket) {
   acceptor_.async_accept([this](boost::system::error_code ec,DrainTransport::Socket socket) {
    if(ec)return;
    ++connections_;
    if(writer_) {boost::system::error_code ignored;socket.close(ignored);accept();return;}
// 2026-09-21: share the product session state across TCP and reliable UDP.
//     socket_=std::make_shared<tcp::socket>(std::move(socket));
    socket_=std::make_shared<DrainTransport::Socket>(std::move(socket));
// 2026-09-21: share the product session state across TCP and reliable UDP.
//     writer_=std::make_unique<fs::BoundedTCPWriter>(socket_);
    writer_=std::make_unique<fs::BasicBoundedStreamWriter<DrainTransport::Socket>>(socket_);
    read();accept();
   });
  }
  void send(const fs::NativeRecoveryPacket& p) {
   if(!writer_->TrySend(p.bytes.data(),p.size))throw std::runtime_error("Fixture send failed");
  }
  void read() {
   if(!writer_->AsyncReadSome(asio::buffer(bytes_),[this](boost::system::error_code ec,size_t size) {
    if(ec)return;
    if(!fs::AppendBoundedBytes(receive_,bytes_.data(),size,8192))throw std::runtime_error("Fixture receive bound");
    while(!receive_.empty()) {
     if(receive_[0]==std::to_underlying(fs::MessageType::Heartbeat)) {
      if(receive_.size()<fs::HEARTBEAT_PACK_BYTES)break;
      fs::NativeRecoveryPacket echo;echo.size=fs::HEARTBEAT_PACK_BYTES;
      std::copy_n(receive_.begin(),echo.size,echo.bytes.begin());send(echo);
      receive_.erase(receive_.begin(),receive_.begin()+echo.size);continue;
     }
     const int count=fs::native_recovery_wire::record_size(receive_);
     if(count<0)throw std::runtime_error("Malformed actual client packet");
     if(!count)break;
     const auto packet=std::span<const uint8_t>(receive_.data(),count);
     const auto kind=static_cast<fs::NativeRecoveryKind>(packet[0]);
     if(kind==fs::NativeRecoveryKind::LoadHello) {
      if(!fs::is_recovery_load_hello(packet))throw std::runtime_error("Wrong client hello");
      fs::NativeRecoverySession session;session.match=fs::NativeMatchContract(42,1,2);
      session.grant=grant_;session.loading=true;send(fs::pack_recovery_session(session));
     } else if(kind==fs::NativeRecoveryKind::LoadReceipt || kind==fs::NativeRecoveryKind::LoadCancel) {
      const auto proof=fs::decode_recovery_load_control(packet,kind);
      if(!proof || proof->generation!=grant_.generation || proof->slot!=grant_.slot ||
         !fs::native_secret_equal(proof->match,grant_.match) ||
         !fs::native_secret_equal(proof->secret,grant_.secret))throw std::runtime_error("Wrong actual cancellation proof");
      if(kind==fs::NativeRecoveryKind::LoadCancel) {
       ++cancels_;
       auto answer=grant_;
       if(reply_==Reply::Secret)answer.secret[0]^=1;
       if(reply_==Reply::Generation)++answer.generation;
       if(reply_==Reply::Closed){writer_->Close();return;}
       if(reply_!=Reply::Silent)send(fs::pack_recovery_load_control(fs::NativeRecoveryKind::LoadCancelled,answer));
      }
     } else throw std::runtime_error("Client sent gameplay during cancelled preparation");
     receive_.erase(receive_.begin(),receive_.begin()+count);
    }
    if(!writer_->is_closed())read();
   }))throw std::runtime_error("Fixture read dispatch failed");
  }
  asio::io_context io_;
// 2026-09-21: share the product session state across TCP and reliable UDP.
//   tcp::acceptor acceptor_;
  DrainTransport::Acceptor acceptor_;
  const Reply reply_;
  fs::NativeRecoveryGrant grant_;
// 2026-09-21: share the product session state across TCP and reliable UDP.
//   std::shared_ptr<tcp::socket> socket_;
  std::shared_ptr<DrainTransport::Socket> socket_;
// 2026-09-21: share the product session state across TCP and reliable UDP.
//   std::unique_ptr<fs::BoundedTCPWriter> writer_;
  std::unique_ptr<fs::BasicBoundedStreamWriter<DrainTransport::Socket>> writer_;
  std::array<uint8_t,4096> bytes_{};
  std::vector<uint8_t> receive_;
  std::thread thread_;
  std::exception_ptr error_;
  size_t connections_=0,cancels_=0;
};
class CancelWindow {
 public:
  CancelWindow()=default;~CancelWindow()=default;
  CancelWindow(const CancelWindow&)=delete;CancelWindow& operator=(const CancelWindow&)=delete;
  CancelWindow(CancelWindow&&)=delete;CancelWindow& operator=(CancelWindow&&)=delete;
  void Title(const char*){}
  void Poll(){}
  CancelWindow& buffer(){return *this;}
  bool quit_requested()const{return true;}
  void Take(){}
};
int main(int,char**) {
 try{
  double maximum=0;
  for(Reply reply:{Reply::Valid,Reply::Secret,Reply::Generation,Reply::Silent,Reply::Closed}) {
   ReplyServer server(reply);GameEnv env;asio::io_context unused;
   fs::MultiplayerConfig config;config.native_product=true;config.render=false;
   config.frame_rate_hz=50;config.host="127.0.0.1";config.port=server.port();
// 2026-09-21: share the product session state across TCP and reliable UDP.
//    IntegratedFrameSyncClient client(unused,config.host,config.port,&env,config);
   DrainClient client(unused,config.host,config.port,&env,config);
   require(client.connect(),"Actual client could not prepare runtime");
   CancelWindow window;bool cancelled=false;
   const auto begin=std::chrono::steady_clock::now();
   try{client.initialize_on_owner(window);}catch(const GameLoadCancelled&){cancelled=true;}
   require(cancelled,"Actual loading checkpoint ignored user cancellation");
   client.stop();
   const double elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count();
   maximum=std::max(maximum,elapsed);
   require(elapsed<.25,"Cancellation drain exceeded the existing 250ms exit budget");
   require(!client.is_running() && client.confirmed_count()==0,"Cancelled preparation advanced gameplay");
   require(client.failed()==(reply==Reply::Secret || reply==Reply::Generation),"Forged receipt not reflected in failure result");
   client.stop();server.check();
  }
  std::cout<<"{\"passed\":true,\"checks\":5,\"assertions\":"<<assertions
    <<",\"skipped\":0,\"actual_gameenv\":true,\"actual_client\":true,\"transport\":\""
#if defined(FOOTBALL_NATIVE_UDP_CLIENT)
    <<"UDP"
#else
    <<"TCP"
#endif
    <<"\",\"maximum_cancel_seconds\":"<<maximum<<"}\n";
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
