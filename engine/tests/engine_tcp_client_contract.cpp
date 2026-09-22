// 2026-09-09: shared TCPFrameClient against the actual GameEnv TCP server.
#include "frame_sync/tcp_frame_client.hpp"
#include "frame_sync/reconnecting_client.hpp"
#include "frame_sync/engine_tcp_bridge.hpp"
#include <atomic>
#include <iostream>
#include <thread>
namespace {
using namespace std::chrono_literals;
namespace fs=frame_sync;
size_t assertions=0;
void Require(bool value,const char* reason){++assertions;if(!value)throw std::runtime_error(reason);}
template<class F> void Until(F predicate,const char* reason,std::chrono::milliseconds limit=15000ms){
  const auto end=std::chrono::steady_clock::now()+limit;
  while(!predicate()){if(std::chrono::steady_clock::now()>=end)throw std::runtime_error(reason);std::this_thread::sleep_for(1ms);}
  ++assertions;
}
struct Server {
  GameEnv env;
  boost::asio::io_context io;
  fs::MultiplayerConfig config;
  std::unique_ptr<fs::EngineTCPServer> server;
  std::thread network,frames;
  std::exception_ptr network_error,frame_error;
  std::atomic<size_t> nonzero_inputs{0};
  Server(){
    config.left_agents=1;config.right_agents=0;config.seed=42;config.frame_rate_hz=60;
    fs::StartTCPGame(env,config);
// 2026-09-09: correct fixture to the existing public API/type.
//     auto engine=fs::MakeEngineCallbacks(&env,1,0);
    auto engine=fs::MakeGameEnvCallbacks(&env);
    auto step=engine.step_frame;
    engine.step_frame=[this,step](std::span<const fs::SlotInput> inputs){
      if(inputs[0].dir_x!=0||inputs[0].dir_y!=0)++nonzero_inputs;
      step(inputs);
    };
    server=std::make_unique<fs::EngineTCPServer>(io,0,config,std::move(engine),fs::MakeGameEnvBotObserver(&env,1,0));
// 2026-09-09: correct fixture to the existing public API/type.
//     network=std::thread([this]{try{io.run();}catch(...){network_error=std::current_exception();server->Stop();}});
    network=std::thread([this]{try{io.run();}catch(...){network_error=std::current_exception();server->stop();}});
// 2026-09-09: correct fixture to the existing public API/type.
//     frames=std::thread([this]{try{server->Run();}catch(...){frame_error=std::current_exception();server->Stop();}});
// 2026-09-09: correct fixture to the existing public API/type.
//     frames=std::thread([this]{try{server->Run();}catch(...){frame_error=std::current_exception();server->stop();}});
    frames=std::thread([this]{try{server->run_frame_loop();}catch(...){frame_error=std::current_exception();server->stop();}});
  }
  ~Server(){Stop();}
// 2026-09-09: correct fixture to the existing public API/type.
//   void Stop(){server->Stop();if(frames.joinable())frames.join();if(network.joinable())network.join();}
  void Stop(){server->stop();if(frames.joinable())frames.join();if(network.joinable())network.join();}
  void Check(){if(frame_error)std::rethrow_exception(frame_error);if(network_error)std::rethrow_exception(network_error);}
};
}
// 2026-09-09: correct fixture to the existing public API/type.
// int main(){
// 2026-09-09: run the same real GameEnv contract through manual and automatic
// restoration so the reconnect wrapper cannot pass using a counter-only engine.
// int main(int, char**){
//   try{
//     Server host;GameEnv local;size_t preparations=0;
//     fs::TCPFrameClient client("127.0.0.1",host.server->port(),[&](const fs::TCPSessionInfo& info){
//       Require(info.seed==42&&info.left==1&&info.right==0&&info.slots==std::vector<uint16_t>{0},"actual session metadata changed");
//       ++preparations;fs::MultiplayerConfig config;config.seed=info.seed;config.left_agents=info.left;config.right_agents=info.right;
// // 2026-09-09: correct fixture to the existing public API/type.
// //       fs::StartTCPGame(local,config);return fs::MakeEngineCallbacks(&local,info.left,info.right);
//       fs::StartTCPGame(local,config);return fs::MakeGameEnvCallbacks(&local);
//     });
//     Require(client.Connect(),"shared TCP client could not initialize actual GameEnv");
//     auto drive=[&](uint32_t target){
//       uint32_t last_sent=UINT32_MAX;
//       Until([&]{
//         client.Poll();
//         const auto stats=host.server->stats();
//         if(stats.accepting_inputs&&stats.next_frame==client.next_frame()&&stats.next_frame!=last_sent){
//           const fs::SlotInput input=stats.next_frame%2?fs::SlotInput{0,0.7f,0}:fs::SlotInput{0.6f,0,0};
//           Require(client.SendInput(input),"actual player input was rejected");last_sent=stats.next_frame;
//         }
//         client.Tick(fs::SlotInput::Default(),0);
//         Require(client.connected(),"actual TCP reconciliation/hash verification stopped");
//         return client.confirmed_count()>=target;
//       },"actual client did not confirm enough frames");
//     };
//     drive(12);Require(client.stats().verified_hashes>=2,"initial actual hashes were not verified");
//     Require(host.nonzero_inputs>0,"actual server did not apply nonzero client inputs");
//     client.Close();client.Poll();
//     Until([&]{client.Poll();return host.server->stats().bot_slots==1;},"actual disconnect did not trigger bot takeover");
//     // The current server's legacy token is known for its first assigned session.
//     // This tests restoration mechanics, not secure token issuance/authentication.
//     Require(client.Resume(fs::MakeSessionToken(0,42,1)),"actual client failed to restore the server snapshot");
//     const auto resume_frame=client.next_frame();Require(resume_frame>=12,"resume reset the frame origin to zero");
//     Require(client.confirmed_count()==resume_frame,"snapshot boundary and confirmation count disagree");
//     Require(preparations==1,"resume recreated the engine instead of restoring state");
//     drive(resume_frame+25);
//     Require(client.stats().verified_hashes>=2,"resumed actual engine hashes were not checked");
//     Require(host.server->stats().reconnects==1&&host.server->stats().bot_slots==0,"actual player control was not restored");
//     Require(client.simulation()->history_bytes()<=8*1024*1024&&client.stats().receive_capacity<=8192,"actual client exceeded its retained budgets");
// // 2026-09-09: correct fixture to the existing public API/type.
// //     const auto confirmed=client.confirmed_count(), hashes=client.stats().verified_hashes;
//     const auto confirmed=client.confirmed_count(); const auto hashes=client.stats().verified_hashes;
//     host.Stop();host.Check();
//     Until([&]{client.Poll();return !client.connected();},"server shutdown did not terminate client");
//     Require(client.status()==fs::TCPClientStatus::IoError,"shutdown ended for an unexpected reason");
//     std::cout<<"{\"passed\":true,\"assertions\":"<<assertions<<",\"skipped\":0,\"initial_confirmed\":12,\"resume_frame\":"<<resume_frame
//              <<",\"final_confirmed\":"<<confirmed<<",\"resumed_verified_hashes\":"<<hashes<<",\"actual_nonzero_inputs\":"<<host.nonzero_inputs.load()<<"}"<<std::endl;
//     return 0;
//   }catch(const std::exception& error){std::cerr<<"actual TCP client contract: "<<error.what()<<std::endl;return 1;}
// }

template<class Client> int RunClientContract() {
  try {
    Server host; GameEnv local; size_t preparations = 0;
    int disconnects = 0, attempts = 0, successes = 0, failures = 0;
    uint32_t automatic_boundary = 0;
    auto prepare = [&](const fs::TCPSessionInfo& info) {
      Require(info.seed == 42 && info.left == 1 && info.right == 0 && info.slots == std::vector<uint16_t>{0},
              "actual session metadata changed");
      ++preparations;
      fs::MultiplayerConfig config; config.seed = info.seed; config.left_agents = info.left; config.right_agents = info.right;
      fs::StartTCPGame(local, config); return fs::MakeGameEnvCallbacks(&local);
    };
    std::unique_ptr<Client> owner;
    if constexpr (std::same_as<Client, fs::ReconnectingClient>) {
      fs::ReconnectingClient::Callbacks callbacks;
      callbacks.on_disconnect = [&] { ++disconnects; };
      callbacks.on_reconnect_attempt = [&](int value) { attempts = value; };
      callbacks.on_reconnect_success = [&] { ++successes; automatic_boundary = owner->next_frame(); };
      callbacks.on_reconnect_failed = [&] { ++failures; };
      fs::ReconnectOptions options; options.initial_delay = 300ms;
      // First actual session's existing legacy token is provisioned by this
      // fixture only. This is not proof of secure issuance over the protocol.
      owner = std::make_unique<Client>("127.0.0.1", host.server->port(), prepare,
          fs::MakeSessionToken(0, 42, 1), options, std::move(callbacks));
    } else {
      owner = std::make_unique<Client>("127.0.0.1", host.server->port(), prepare);
    }
    auto& client = *owner;
    Require(client.Connect(), "shared TCP client could not initialize actual GameEnv");
    auto drive = [&](uint32_t target) {
      uint32_t last_sent = UINT32_MAX;
      Until([&] {
        client.Poll(); const auto stats = host.server->stats();
        if (stats.accepting_inputs && stats.next_frame == client.next_frame() && stats.next_frame != last_sent) {
          const fs::SlotInput input = stats.next_frame % 2 ? fs::SlotInput{0, 0.7f, 0} : fs::SlotInput{0.6f, 0, 0};
          Require(client.SendInput(input), "actual player input was rejected"); last_sent = stats.next_frame;
        }
        client.Tick(fs::SlotInput::Default(), 0);
        Require(client.connected(), "actual TCP reconciliation/hash verification stopped");
        return client.confirmed_count() >= target;
      }, "actual client did not confirm enough frames");
    };
    drive(12);
    Require(client.stats().verified_hashes >= 2, "initial actual hashes were not verified");
    Require(host.nonzero_inputs > 0, "actual server did not apply nonzero client inputs");
    if constexpr (std::same_as<Client, fs::ReconnectingClient>) {
      Require(client.ResetForReconnect(), "could not schedule actual snapshot recovery");
    } else {
      client.Close(); client.Poll();
    }
    // Keep the wrapper's backoff clock unpolled here until takeover is observed;
    // the server keeps running and owns the actual AI-controlled interval.
    Until([&] { return host.server->stats().bot_slots == 1; }, "actual disconnect did not trigger bot takeover");
    if constexpr (std::same_as<Client, fs::ReconnectingClient>) {
      Until([&] { client.Poll(); return client.connected(); }, "automatic actual GameEnv resume failed");
      Require(disconnects == 1 && attempts == 1 && successes == 1 && failures == 0,
              "actual reconnect callbacks or retry count were incorrect");
      Require(client.next_frame() == automatic_boundary, "success callback preceded snapshot restoration");
    } else {
      Require(client.Resume(fs::MakeSessionToken(0, 42, 1)), "actual client failed to restore the server snapshot");
    }
    const auto resume_frame = client.next_frame();
    Require(resume_frame >= 12, "resume reset the frame origin to zero");
    Require(client.confirmed_count() == resume_frame, "snapshot boundary and confirmation count disagree");
    Require(preparations == 1, "resume recreated the engine instead of restoring state");
    drive(resume_frame + 25);
    Require(client.stats().verified_hashes >= 2, "resumed actual engine hashes were not checked");
    Require(host.server->stats().reconnects == 1 && host.server->stats().bot_slots == 0,
            "actual player control was not restored");
    Require(client.simulation()->history_bytes() <= 8 * 1024 * 1024 && client.stats().receive_capacity <= 8192,
            "actual client exceeded its retained budgets");
    const auto confirmed = client.confirmed_count(); const auto hashes = client.stats().verified_hashes;
    host.Stop(); host.Check();
    Until([&] { client.Poll(); return !client.connected(); }, "server shutdown did not terminate client");
    Require(client.status() == fs::TCPClientStatus::IoError, "shutdown ended for an unexpected reason");
    client.Close();
    std::cout << "{\"passed\":true,\"assertions\":" << assertions << ",\"skipped\":0,\"initial_confirmed\":12,\"resume_frame\":" << resume_frame
              << ",\"final_confirmed\":" << confirmed << ",\"resumed_verified_hashes\":" << hashes
              << ",\"actual_nonzero_inputs\":" << host.nonzero_inputs.load()
              << ",\"automatic_reconnect\":" << (std::same_as<Client, fs::ReconnectingClient> ? "true" : "false")
              << ",\"reconnect_attempts\":" << attempts << "}" << std::endl;
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "actual TCP client contract: " << error.what() << std::endl; return 1;
  }
}
int main(int argc, char** argv) {
  if (argc == 1) return RunClientContract<fs::TCPFrameClient>();
  if (argc == 2 && std::string_view(argv[1]) == "--automatic") return RunClientContract<fs::ReconnectingClient>();
  std::cerr << "Usage: engine_tcp_client_contract [--automatic]" << std::endl; return 1;
}
