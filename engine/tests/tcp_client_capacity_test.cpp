// 2026-09-09: real sockets exercise the production bounded TCP client/parser.
#include "frame_sync/tcp_frame_client.hpp"
#include "frame_sync/reconnecting_client.hpp"
#include <gtest/gtest.h>
#include <atomic>
#include <thread>
namespace {
namespace fs = frame_sync;
namespace asio = boost::asio;
using tcp = asio::ip::tcp;
using namespace std::chrono_literals;
using Bytes = std::vector<uint8_t>;
template<class F> bool Until(F predicate, std::chrono::milliseconds timeout = 3000ms) {
  const auto end = std::chrono::steady_clock::now() + timeout;
  do { if (predicate()) return true; std::this_thread::sleep_for(1ms); }
  while (std::chrono::steady_clock::now() < end);
  return false;
}
void Check(bool condition) { if (!condition) throw std::runtime_error("TCP peer fixture failed"); }
Bytes Read(tcp::socket& socket, size_t count) {
  socket.non_blocking(true); Bytes result(count); size_t got = 0;
  Check(Until([&] {
    boost::system::error_code error;
    got += socket.read_some(asio::buffer(result.data() + got, count - got), error);
    if (error && error != asio::error::would_block && error != asio::error::try_again)
      throw std::runtime_error("TCP fixture peer ended early");
    return got == count;
  }));
  return result;
}
void Send(tcp::socket& socket, const Bytes& bytes) {
  socket.non_blocking(false); asio::write(socket, asio::buffer(bytes));
}
Bytes Session(uint16_t left = 1, uint16_t right = 1, uint32_t seed = 42) {
  Bytes bytes(9); Check(fs::PackSessionStart(seed, left, right, bytes.data(), bytes.size()) == bytes.size()); return bytes;
}
Bytes Assignment(std::vector<uint16_t> slots = {0}) {
  Bytes bytes(3 + slots.size() * 2);
  Check(fs::PackSlotAssignment(slots.data(), static_cast<uint16_t>(slots.size()), bytes.data(), bytes.size()) == bytes.size()); return bytes;
}
Bytes Authority(uint32_t frame, std::vector<fs::SlotInput> inputs = {fs::SlotInput::Default(), fs::SlotInput::Default()}) {
  Bytes bytes(7 + inputs.size() * fs::SLOT_INPUT_BYTES);
  Check(fs::PackAuthoritativeFrame(frame, inputs.data(), static_cast<uint16_t>(inputs.size()), bytes.data(), bytes.size()) == bytes.size()); return bytes;
}
Bytes Hash(uint32_t frame, uint64_t hash) {
  Bytes bytes(fs::STATE_HASH_PACK_BYTES); Check(fs::PackStateHash(frame, hash, bytes.data(), bytes.size()) == bytes.size()); return bytes;
}
void Append(Bytes& to, const Bytes& from) { to.insert(to.end(), from.begin(), from.end()); }
void Hello(tcp::socket& peer, bool resume = false) {
  Send(peer, Session());
  auto request = Read(peer, resume ? fs::RECONNECT_REQUEST_BYTES : 1);
  Check(request[0] == std::to_underlying(resume ? fs::MessageType::ReconnectRequest : fs::MessageType::Connect));
  if (resume) { uint64_t token = 0; fs::UnpackReconnectRequest(request.data(), request.size(), &token); Check(token == 0x12345678); }
  Send(peer, Assignment());
}
void WaitClosed(tcp::socket& peer) {
  peer.non_blocking(true);
  Check(Until([&] { uint8_t bytes[512]; boost::system::error_code ec; peer.read_some(asio::buffer(bytes), ec);
    return ec == asio::error::eof || ec == asio::error::connection_reset; }));
}
struct Peer {
  using Script = std::function<void(tcp::socket&, const std::atomic<bool>&)>;
  asio::io_context io;
  tcp::acceptor acceptor{io, {tcp::v4(), 0}};
  std::atomic<bool> stop{false};
  std::exception_ptr failure;
  std::thread worker;
  explicit Peer(std::vector<Script> scripts) {
    acceptor.non_blocking(true);
    worker = std::thread([this, scripts = std::move(scripts)] {
      try {
        for (const auto& script : scripts) {
          tcp::socket socket(io);
          Check(Until([&] { if (stop) return true; boost::system::error_code ec;
            acceptor.accept(socket, ec); return !ec; }));
          if (stop) return;
          script(socket, stop);
        }
      } catch (...) { failure = std::current_exception(); }
    });
  }
  ~Peer() { stop = true; if (worker.joinable()) worker.join(); }
  unsigned short port() const { return acceptor.local_endpoint().port(); }
  static void Hold(const std::atomic<bool>& stop) { while (!stop) std::this_thread::sleep_for(1ms); }
  void Join() { stop = true; worker.join(); if (failure) std::rethrow_exception(failure); }
};
TEST(TCPClientCapacity, InvalidConfigurationIsRejectedBeforeConnecting) {
  EXPECT_THROW((fs::TCPClientTransport("", 1)), std::invalid_argument);
  EXPECT_THROW((fs::TCPClientTransport("localhost", 0)), std::invalid_argument);
  EXPECT_THROW((fs::TCPClientTransport(std::string(254, 'x'), 1)), std::invalid_argument);
  fs::TCPClientLimits limits; limits.send.byte_limit = 0;
  EXPECT_THROW((fs::TCPClientTransport("localhost", 1, limits)), std::invalid_argument);
  limits = {}; limits.authority_frames = 1025;
  EXPECT_THROW((fs::TCPClientTransport("localhost", 1, limits)), std::invalid_argument);
  limits = {}; limits.snapshot_bytes = 8 * 1024 * 1024 + 1;
  EXPECT_THROW((fs::TCPClientTransport("localhost", 1, limits)), std::invalid_argument);
}
TEST(TCPClientCapacity, PartialHandshakeHasAnAbsoluteDeadline) {
  Peer peer({[](auto& socket, const auto& stop) { Send(socket, {5, 42}); Peer::Hold(stop); }});
  fs::TCPClientLimits limits; limits.handshake_timeout = 50ms;
  fs::TCPClientTransport client("127.0.0.1", peer.port(), limits);
  EXPECT_FALSE(client.Connect()); EXPECT_EQ(client.status(), fs::TCPClientStatus::HandshakeTimeout);
  EXPECT_EQ(client.stats().receive_capacity, 0u); client.Poll(); peer.Join();
}
TEST(TCPClientCapacity, InvalidSessionAndSlotHeadersFailEarly) {
  for (const auto& bytes : {Session(12, 1), Session(0, 0), Bytes{254}}) {
    Peer peer({[bytes](auto& socket, const auto& stop) { Send(socket, bytes); Peer::Hold(stop); }});
    fs::TCPClientTransport client("127.0.0.1", peer.port()); EXPECT_FALSE(client.Connect());
    EXPECT_EQ(client.status(), fs::TCPClientStatus::InvalidMessage); EXPECT_EQ(client.stats().receive_capacity, 0u);
  }
  for (const auto& bytes : {Assignment({0, 0}), Assignment({2}), Bytes{7, 255, 255}}) {
    Peer peer({[bytes](auto& socket, const auto& stop) { Send(socket, Session()); Check(Read(socket, 1)[0] == 0); Send(socket, bytes); Peer::Hold(stop); }});
    fs::TCPClientTransport client("127.0.0.1", peer.port()); EXPECT_FALSE(client.Connect());
    EXPECT_EQ(client.status(), fs::TCPClientStatus::InvalidMessage);
  }
}
TEST(TCPClientCapacity, AuthorityCapacityReleasesOnPopAndPreservesWholeFrames) {
  std::atomic<bool> ready{false}, second{false};
  Peer peer({[&](auto& socket, const auto& stop) { Hello(socket); Check(Read(socket, 1)[0] == 6);
    Bytes bytes = Authority(0, {{0.2f, 0.f, 1}, {0.f, 0.3f, 2}}); Append(bytes, Authority(1)); Send(socket, bytes); ready = true;
    Check(Until([&] { return second || stop; })); if (!stop) Send(socket, Authority(2)); Peer::Hold(stop); }});
  fs::TCPClientLimits limits; limits.authority_frames = 2; limits.authority_bytes = 40;
  fs::TCPClientTransport client("127.0.0.1", peer.port(), limits); ASSERT_TRUE(client.Connect()); ASSERT_TRUE(client.Ready());
  ASSERT_TRUE(Until([&] { client.Poll(); return ready && client.stats().authority_frames == 2; }));
  EXPECT_EQ(client.stats().authority_bytes, 40u); fs::TCPAuthority frame;
  ASSERT_TRUE(client.PopAuthority(frame)); EXPECT_EQ(frame.frame, 0u); EXPECT_FLOAT_EQ(float(frame.inputs[1].dir_y), 0.3f);
  EXPECT_EQ(client.stats().authority_bytes, 20u); second = true;
  ASSERT_TRUE(Until([&] { client.Poll(); return client.stats().authority_frames == 2; }));
  ASSERT_TRUE(client.PopAuthority(frame)); EXPECT_EQ(frame.frame, 1u);
  ASSERT_TRUE(client.PopAuthority(frame)); EXPECT_EQ(frame.frame, 2u);
  EXPECT_EQ(client.stats().authority_bytes, 0u); EXPECT_LE(client.stats().receive_capacity, 8192u); peer.Join();
}
TEST(TCPClientCapacity, AuthorityAndHashOverflowStopAndReleasePayloads) {
  for (bool hashes : {false, true}) {
    Peer peer({[hashes](auto& socket, const auto& stop) { Hello(socket); Check(Read(socket, 1)[0] == 6);
      Bytes bytes; for (uint32_t frame = 0; frame < 3; ++frame) Append(bytes, hashes ? Hash(frame, frame) : Authority(frame));
      Send(socket, bytes); Peer::Hold(stop); }});
    fs::TCPClientLimits limits; limits.authority_frames = 2; limits.hashes = 2;
    fs::TCPClientTransport client("127.0.0.1", peer.port(), limits); ASSERT_TRUE(client.Connect()); ASSERT_TRUE(client.Ready());
    ASSERT_TRUE(Until([&] { client.Poll(); return !client.connected(); }));
    EXPECT_EQ(client.status(), fs::TCPClientStatus::Capacity);
    EXPECT_EQ(client.stats().authority_bytes, 0u); EXPECT_EQ(client.stats().hashes, 0u); EXPECT_EQ(client.stats().receive_capacity, 0u);
  }
}
TEST(TCPClientCapacity, MalformedInputsAndConflictingHashesAreTerminal) {
  Bytes oversized{3, 0, 0, 0, 0, 255, 255};
  auto invalid = Authority(0, {{std::numeric_limits<float>::quiet_NaN(), 0, 0}, fs::SlotInput::Default()});
  auto conflict = Hash(0, 3); Append(conflict, Hash(0, 4));
  for (const auto& bytes : {oversized, invalid, conflict, Bytes{254}}) {
    Peer peer({[bytes](auto& socket, const auto& stop) { Hello(socket); Check(Read(socket, 1)[0] == 6); Send(socket, bytes); Peer::Hold(stop); }});
    fs::TCPClientTransport client("127.0.0.1", peer.port()); ASSERT_TRUE(client.Connect()); ASSERT_TRUE(client.Ready());
    ASSERT_TRUE(Until([&] { client.Poll(); return !client.connected(); })); EXPECT_EQ(client.status(), fs::TCPClientStatus::InvalidMessage);
  }
}
TEST(TCPClientCapacity, ControlsConsumeEntirePacketsAndLeaveAuthorityAligned) {
  Peer peer({[](auto& socket, const auto& stop) { Hello(socket); Check(Read(socket, 1)[0] == 6);
    Bytes bytes{10,1,0,0,0,0,0,11,1,0,0,0,0,0,8,3,2,1,0,7,6,5,4}; Append(bytes, Authority(0)); Append(bytes, Hash(0, 9));
    for (size_t i = 0; i < bytes.size(); i += 3) Send(socket, Bytes(bytes.begin()+i, bytes.begin()+std::min(i+3,bytes.size())));
    Peer::Hold(stop); }});
  fs::TCPClientTransport client("127.0.0.1", peer.port()); ASSERT_TRUE(client.Connect()); ASSERT_TRUE(client.Ready());
  ASSERT_TRUE(Until([&] { client.Poll(); return client.stats().hashes == 1; }));
  EXPECT_FALSE(client.bots()[1]); fs::TCPAuthority frame; ASSERT_TRUE(client.PopAuthority(frame)); EXPECT_EQ(frame.frame, 0u);
  EXPECT_TRUE(client.VerifyHashes([](auto frame, auto hash) { return std::optional<bool>(frame == 0 && hash == 9); }));
  EXPECT_EQ(client.stats().verified_hashes, 1u); peer.Join();
}
TEST(TCPClientCapacity, OutgoingLimitIncludesUndispatchedPacketsAndCloseDrains) {
  std::atomic<bool> ready{false};
  Peer peer({[&](auto& socket, const auto& stop) { Hello(socket); Check(Read(socket, 1)[0] == 6); ready=true; Peer::Hold(stop); }});
  fs::TCPClientLimits limits; limits.send = fs::StreamBudget(1, 64);
  fs::TCPClientTransport client("127.0.0.1", peer.port(), limits); ASSERT_TRUE(client.Connect()); ASSERT_TRUE(client.Ready());
  ASSERT_TRUE(Until([&] { client.Poll(); return ready && client.stats().send_messages == 0; }));
  const uint16_t slot = 0; const auto input = fs::SlotInput::Default();
  ASSERT_TRUE(client.SendInput(0, &slot, &input, 1)); EXPECT_EQ(client.stats().send_messages, 1u);
  EXPECT_FALSE(client.SendInput(1, &slot, &input, 1)); EXPECT_EQ(client.status(), fs::TCPClientStatus::Capacity);
  ASSERT_TRUE(Until([&] { client.Poll(); return client.stats().send_bytes == 0; })); peer.Join();
}
TEST(TCPClientCapacity, IdlePeerTerminatesAndForeignSlotsCannotBeSent) {
  for (bool invalid_input : {false, true}) {
    Peer peer({[](auto& socket, const auto& stop) { Hello(socket); Check(Read(socket, 1)[0] == 6); Peer::Hold(stop); }});
    fs::TCPClientLimits limits; limits.idle_timeout = 50ms;
    fs::TCPClientTransport client("127.0.0.1", peer.port(), limits); ASSERT_TRUE(client.Connect()); ASSERT_TRUE(client.Ready());
    if (invalid_input) { const uint16_t foreign=1; const auto input=fs::SlotInput::Default(); EXPECT_FALSE(client.SendInput(0,&foreign,&input,1)); }
    ASSERT_TRUE(Until([&] { client.Poll(); return !client.connected(); }));
    EXPECT_EQ(client.status(), invalid_input ? fs::TCPClientStatus::InvalidInput : fs::TCPClientStatus::IdleTimeout);
  }
}
TEST(TCPClientCapacity, ResumeRestoresOneBoundedSnapshotAndKeepsCoalescedFrames) {
  std::atomic<bool> ready{false};
  Bytes state(96 * 1024); for (size_t i=0;i<state.size();++i) state[i]=uint8_t(i*13);
  Peer peer({[&](auto& socket,const auto&) { Hello(socket); Check(Read(socket,1)[0]==6);ready=true;WaitClosed(socket); },
    [&](auto& socket,const auto& stop) { Hello(socket,true); Bytes packet(9+state.size());
      Check(fs::PackStateSnapshot(37,state.data(),static_cast<uint32_t>(state.size()),packet.data(),packet.size())==packet.size());
      Append(packet,Authority(37)); Append(packet,Hash(37,123)); Send(socket,packet); Check(Read(socket,1)[0]==6);Peer::Hold(stop); }});
  fs::TCPClientTransport client("127.0.0.1",peer.port()); ASSERT_TRUE(client.Connect());ASSERT_TRUE(client.Ready());
  ASSERT_TRUE(Until([&]{client.Poll();return ready.load();})); client.Close();ASSERT_TRUE(client.Connect(0x12345678));
  auto snapshot=client.TakeBootstrap();ASSERT_TRUE(snapshot);EXPECT_EQ(snapshot->next_frame,37u);EXPECT_EQ(snapshot->state,state);
  EXPECT_LE(client.stats().receive_capacity,8192u); ASSERT_TRUE(client.Ready());
  ASSERT_TRUE(Until([&]{client.Poll();return client.stats().hashes==1;}));fs::TCPAuthority authority;ASSERT_TRUE(client.PopAuthority(authority));EXPECT_EQ(authority.frame,37u);
  client.Close();client.Poll();peer.Join();
}
struct CounterEngine {
  uint64_t state=0;size_t steps=0,preparations=0;
  fs::EngineCallbacks Prepare(const fs::TCPSessionInfo& session) {
    Check(session.left==1&&session.right==1);++preparations;
    fs::EngineCallbacks engine;
    engine.save_state=[this]{fs::StateBlob bytes(8);std::memcpy(bytes.data(),&state,8);return bytes;};
    engine.restore_state=[this](const fs::StateBlob& bytes){if(bytes.size()!=8)throw std::invalid_argument("counter snapshot");std::memcpy(&state,bytes.data(),8);};
    engine.compute_hash=[this]{return state;};
    engine.step_frame=[this](std::span<const fs::SlotInput> inputs){Check(inputs.size()==2);state=state*17+uint64_t(std::lround(inputs[0].dir_x*10))+uint64_t(std::lround(inputs[1].dir_y*10))+1;++steps;};
    return engine;
  }
};
TEST(TCPFrameClient, FrameZeroAndIndependentInputsUnblockPredictionAtItsCap) {
  std::atomic<bool> release{false};
  Peer peer({[&](auto& socket,const auto& stop){Hello(socket);Check(Read(socket,1)[0]==6);Check(Until([&]{return release||stop;}));if(stop)return;
    Bytes bytes=Authority(0,{{0.2f,0,0},{0,0.3f,0}});Append(bytes,Hash(0,6));Append(bytes,Authority(1));Append(bytes,Hash(1,103));Append(bytes,Authority(2));Append(bytes,Hash(2,1752));Send(socket,bytes);Peer::Hold(stop);}});
  CounterEngine engine;fs::TCPFrameClient client("127.0.0.1",peer.port(),[&](const auto& info){return engine.Prepare(info);});ASSERT_TRUE(client.Connect());
  for(int i=0;i<3;++i) EXPECT_TRUE(client.Tick({1,0,0}).predicted);
  EXPECT_FALSE(client.Tick({1,0,0}).predicted);EXPECT_EQ(client.next_frame(),3u);release=true;
  ASSERT_TRUE(Until([&]{client.Tick(fs::SlotInput::Default(),0);return client.confirmed_count()==3&&!client.stats().hashes;}));
  EXPECT_TRUE(client.connected());EXPECT_EQ(engine.state,1752u);EXPECT_EQ(client.stats().verified_hashes,3u);EXPECT_GT(client.rollback_count(),0);peer.Join();
}
TEST(TCPFrameClient, HashMismatchStopsAllFurtherEngineSteps) {
  Peer peer({[](auto& socket,const auto& stop){Hello(socket);Check(Read(socket,1)[0]==6);auto bytes=Authority(0);Append(bytes,Hash(0,0));Send(socket,bytes);Peer::Hold(stop);}});
  CounterEngine engine;fs::TCPFrameClient client("127.0.0.1",peer.port(),[&](const auto& info){return engine.Prepare(info);});ASSERT_TRUE(client.Connect());
  ASSERT_TRUE(Until([&]{client.Tick(fs::SlotInput::Default(),0);return !client.connected();}));EXPECT_EQ(client.status(),fs::TCPClientStatus::HashMismatch);
  const auto steps=engine.steps;for(int i=0;i<10;++i)client.Tick({1,0,0});EXPECT_EQ(engine.steps,steps);peer.Join();
}
TEST(TCPFrameClient, ResumeUsesSnapshotFrameOriginWithoutReinitializingEngine) {
  std::atomic<bool> ready{false};
  Peer peer({[&](auto& socket,const auto&){Hello(socket);Check(Read(socket,1)[0]==6);ready=true;WaitClosed(socket);},
    [](auto& socket,const auto& stop){Hello(socket,true);const uint64_t state=1000;Bytes packet(17);
      Check(fs::PackStateSnapshot(50,&state,8,packet.data(),packet.size())==packet.size());Append(packet,Authority(50));Append(packet,Hash(50,17001));Send(socket,packet);Check(Read(socket,1)[0]==6);Peer::Hold(stop);}});
  CounterEngine engine;fs::TCPFrameClient client("127.0.0.1",peer.port(),[&](const auto& info){return engine.Prepare(info);});ASSERT_TRUE(client.Connect());
  ASSERT_TRUE(Until([&]{client.Poll();return ready.load();}));client.Close();ASSERT_TRUE(client.Resume(0x12345678));
  EXPECT_EQ(client.next_frame(),50u);EXPECT_EQ(client.confirmed_count(),50u);EXPECT_EQ(engine.state,1000u);EXPECT_EQ(engine.preparations,1u);
  ASSERT_TRUE(Until([&]{client.Tick(fs::SlotInput::Default(),0);return client.confirmed_count()==51;}));
  EXPECT_TRUE(client.connected());EXPECT_EQ(engine.state,17001u);EXPECT_EQ(client.stats().verified_hashes,1u);peer.Join();
}

TEST(TCPClientCapacity, MaximumAssignmentAndInputUseAllTwentyTwoSlots) {
  std::atomic<bool> checked{false};
  Peer peer({[&](auto& socket,const auto& stop){Send(socket,Session(11,11));Check(Read(socket,1)[0]==0);
    std::vector<uint16_t> slots(22);for(size_t i=0;i<22;++i)slots[i]=static_cast<uint16_t>(i);Send(socket,Assignment(slots));Check(Read(socket,1)[0]==6);
    const auto bytes=Read(socket,271);uint32_t frame;std::vector<std::pair<uint16_t,fs::SlotInput>> entries;
    Check(fs::UnpackClientFrameInput(bytes.data(),bytes.size(),&frame,&entries)==271);Check(frame==7&&entries.size()==22);
    for(size_t i=0;i<22;++i)Check(entries[i].first==i&&entries[i].second.buttons==(i%12));
    Send(socket,Authority(7,std::vector<fs::SlotInput>(22)));checked=true;Peer::Hold(stop);}});
  fs::TCPClientTransport client("127.0.0.1",peer.port());ASSERT_TRUE(client.Connect());ASSERT_TRUE(client.Ready());
  std::array<fs::SlotInput,22> inputs{};for(size_t i=0;i<22;++i)inputs[i].buttons=i%12;
  ASSERT_TRUE(client.SendInput(7,client.session().slots.data(),inputs.data(),22));
  ASSERT_TRUE(Until([&]{client.Poll();return checked&&client.stats().authority_frames==1;}));fs::TCPAuthority authority;ASSERT_TRUE(client.PopAuthority(authority));EXPECT_EQ(authority.inputs.size(),22u);peer.Join();
}
TEST(TCPClientCapacity, OversizedSnapshotFailsAndASecondAttemptRetainsSessionIdentity) {
  std::atomic<bool> ready{false};
  Peer peer({[&](auto& socket,const auto&){Hello(socket);Check(Read(socket,1)[0]==6);ready=true;WaitClosed(socket);},
    [](auto& socket,const auto&){Hello(socket,true);Send(socket,{13,5,0,0,0,255,255,255,255});WaitClosed(socket);},
    [](auto& socket,const auto& stop){Hello(socket,true);const uint64_t value=99;Bytes packet(17);Check(fs::PackStateSnapshot(5,&value,8,packet.data(),packet.size())==17);Send(socket,packet);Check(Read(socket,1)[0]==6);Peer::Hold(stop);}});
  fs::TCPClientTransport client("127.0.0.1",peer.port());ASSERT_TRUE(client.Connect());ASSERT_TRUE(client.Ready());
  ASSERT_TRUE(Until([&]{client.Poll();return ready.load();}));client.Close();EXPECT_FALSE(client.Connect(0x12345678));
  EXPECT_EQ(client.status(),fs::TCPClientStatus::InvalidMessage);EXPECT_EQ(client.stats().snapshot_capacity,0u);EXPECT_EQ(client.stats().receive_capacity,0u);
  ASSERT_TRUE(client.Connect(0x12345678));auto snapshot=client.TakeBootstrap();ASSERT_TRUE(snapshot);EXPECT_EQ(snapshot->state.size(),8u);ASSERT_TRUE(client.Ready());
  client.Poll();peer.Join();
}
TEST(TCPClientCapacity, DestructionDiscardsPendingReadAndUndispatchedWrites) {
  for(int cycle=0;cycle<20;++cycle){
    Peer peer({[](auto& socket,const auto& stop){Hello(socket);Peer::Hold(stop);}});
    {fs::TCPClientTransport client("127.0.0.1",peer.port());ASSERT_TRUE(client.Connect());ASSERT_TRUE(client.Ready());
      const uint16_t slot=0;const auto input=fs::SlotInput::Default();ASSERT_TRUE(client.SendInput(0,&slot,&input,1));}
    peer.Join();
  }
}
TEST(ReconnectingClient, RetryConfigurationAndMissingCredentialFailBeforeIO) {
  CounterEngine engine;
  auto prepare = [&](const auto& info) { return engine.Prepare(info); };
  EXPECT_THROW((fs::ReconnectingClient("127.0.0.1", 1, prepare, 0)), std::invalid_argument);
  for (int attempts : {0, -1, 33, INT_MAX}) {
    fs::ReconnectOptions options; options.max_attempts = attempts;
    EXPECT_THROW((fs::ReconnectingClient("127.0.0.1", 1, prepare, 1, options)), std::invalid_argument);
  }
  fs::ReconnectOptions options; options.initial_delay = 0ms;
  EXPECT_THROW((fs::ReconnectingClient("127.0.0.1", 1, prepare, 1, options)), std::invalid_argument);
  options.initial_delay = 100ms; options.max_delay = 99ms;
  EXPECT_THROW((fs::ReconnectingClient("127.0.0.1", 1, prepare, 1, options)), std::invalid_argument);
  options.max_delay = 30001ms;
  EXPECT_THROW((fs::ReconnectingClient("127.0.0.1", 1, prepare, 1, options)), std::invalid_argument);
  EXPECT_EQ(engine.preparations, 0u);
}
TEST(ReconnectingClient, ConnectionRefusalSaturatesDelayAndExhaustsFiniteRetryBudget) {
  asio::io_context io; tcp::acceptor unused(io, {tcp::v4(), 0});
  const auto port = unused.local_endpoint().port(); unused.close();
  CounterEngine engine; fs::ReconnectingClient::Clock::time_point now{};
  fs::ReconnectOptions options; options.max_attempts = 32; options.initial_delay = 1ms; options.max_delay = 5ms;
  std::vector<int> attempts; int failed = 0, disconnected = 0;
  fs::ReconnectingClient::Callbacks callbacks;
  callbacks.on_reconnect_attempt = [&](int value) { attempts.push_back(value); };
  callbacks.on_reconnect_failed = [&] { ++failed; };
  callbacks.on_disconnect = [&] { ++disconnected; };
  fs::ReconnectingClient client("127.0.0.1", port, [&](const auto& info) { return engine.Prepare(info); },
// 2026-09-09: call the explicit snapshot-budget constructor without a warning.
//       1, options, std::move(callbacks), {}, {}, [&] { return now; });
      1, options, std::move(callbacks), {}, fs::SnapshotBudget{}, [&] { return now; });
// 2026-09-09: WSL's localhost proxy may accept an unused port then reset it;
// native connect refusal and immediate reset are both genuine unavailable peers.
//   EXPECT_FALSE(client.Connect()); EXPECT_EQ(client.last_error(), fs::TCPClientStatus::ConnectFailed);
  EXPECT_FALSE(client.Connect());
  EXPECT_TRUE(client.last_error() == fs::TCPClientStatus::ConnectFailed || client.last_error() == fs::TCPClientStatus::IoError);
  for (int attempt = 1; attempt <= 32; ++attempt) {
    ASSERT_EQ(client.state(), fs::ReconnectState::kReconnecting);
    const auto deadline = client.next_attempt();
    const auto delay = std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now);
    EXPECT_EQ(delay, attempt == 1 ? 1ms : attempt == 2 ? 2ms : attempt == 3 ? 4ms : 5ms);
    now = deadline - 1ms; client.Poll(); EXPECT_EQ(client.attempts(), attempt - 1);
    now = deadline; client.Poll(); EXPECT_EQ(client.attempts(), attempt);
  }
  EXPECT_EQ(attempts.size(), 32u); EXPECT_EQ(attempts.front(), 1); EXPECT_EQ(attempts.back(), 32);
  EXPECT_EQ(client.state(), fs::ReconnectState::kFailed); EXPECT_EQ(failed, 1); EXPECT_EQ(disconnected, 0);
  now += 24h;
  for (int i = 0; i < 100; ++i) client.Poll();
  EXPECT_EQ(attempts.size(), 32u); EXPECT_EQ(failed, 1); EXPECT_EQ(engine.preparations, 0u);
  EXPECT_EQ(client.stats().receive_capacity, 0u); EXPECT_EQ(client.stats().send_bytes, 0u);
}
TEST(ReconnectingClient, EOFTriggersAutomaticSnapshotResumeAndConfirmedHashProgress) {
  std::atomic<bool> drop{false};
  Peer peer({[&](auto& socket, const auto& stop) {
      Hello(socket); Check(Read(socket, 1)[0] == 6); Send(socket, Authority(0));
      Check(Until([&] { return drop || stop; }));
    }, [](auto& socket, const auto& stop) {
      Hello(socket, true); const uint64_t state = 1000; Bytes packet(17);
      Check(fs::PackStateSnapshot(50, &state, 8, packet.data(), packet.size()) == 17);
      Append(packet, Authority(50)); Append(packet, Hash(50, 17001)); Send(socket, packet);
      Check(Read(socket, 1)[0] == 6); Peer::Hold(stop);
    }});
  CounterEngine engine; fs::ReconnectingClient::Clock::time_point now{};
  int disconnects = 0, attempts = 0, successes = 0, failures = 0;
  fs::ReconnectingClient* active = nullptr;
  fs::ReconnectingClient::Callbacks callbacks;
  callbacks.on_disconnect = [&] { ++disconnects; EXPECT_EQ(active->state(), fs::ReconnectState::kReconnecting); active->Poll(); };
  callbacks.on_reconnect_attempt = [&](int value) { attempts = value; EXPECT_FALSE(active->Connect()); };
  callbacks.on_reconnect_success = [&] {
    ++successes; EXPECT_TRUE(active->connected()); EXPECT_EQ(active->confirmed_count(), 50u);
    EXPECT_EQ(engine.state, 1000u); active->Poll();
  };
  callbacks.on_reconnect_failed = [&] { ++failures; };
  fs::ReconnectingClient client("127.0.0.1", peer.port(), [&](const auto& info) { return engine.Prepare(info); },
// 2026-09-09: call the explicit snapshot-budget constructor without a warning.
//       0x12345678, {}, std::move(callbacks), {}, {}, [&] { return now; }); active = &client;
      0x12345678, {}, std::move(callbacks), {}, fs::SnapshotBudget{}, [&] { return now; }); active = &client;
  ASSERT_TRUE(client.Connect());
  ASSERT_TRUE(Until([&] { client.Tick(fs::SlotInput::Default(), 0); return client.confirmed_count() == 1; }));
  drop = true;
  ASSERT_TRUE(Until([&] { client.Poll(); return client.state() == fs::ReconnectState::kReconnecting; }));
  EXPECT_EQ(disconnects, 1); EXPECT_EQ(client.last_error(), fs::TCPClientStatus::IoError);
  for (int i = 0; i < 20; ++i) client.Poll(); EXPECT_EQ(attempts, 0);
  now = client.next_attempt(); client.Poll(); ASSERT_TRUE(client.connected());
  ASSERT_TRUE(Until([&] { client.Tick(fs::SlotInput::Default(), 0); return client.confirmed_count() == 51; }));
  EXPECT_EQ(engine.preparations, 1u); EXPECT_EQ(engine.state, 17001u); EXPECT_EQ(client.stats().verified_hashes, 1u);
  EXPECT_EQ(successes, 1); EXPECT_EQ(attempts, 1); EXPECT_EQ(failures, 0); EXPECT_EQ(disconnects, 1);
  client.Close(); client.Poll(); EXPECT_EQ(client.state(), fs::ReconnectState::kClosed); peer.Join();
}
TEST(ReconnectingClient, ProtocolAndHashFailuresDoNotRetryOrKeepStepping) {
  for (bool overload : {false, true}) {
    Peer peer({[overload](auto& socket, const auto& stop) {
      Hello(socket); Check(Read(socket, 1)[0] == 6); auto bytes = Authority(0);
      Append(bytes, overload ? Authority(1) : Hash(0, 0)); Send(socket, bytes); Peer::Hold(stop);
    }});
    CounterEngine engine; fs::TCPClientLimits limits; if (overload) limits.authority_frames = 1;
    int disconnects = 0, failed = 0, attempts = 0; fs::ReconnectingClient::Callbacks callbacks;
    callbacks.on_disconnect = [&] { ++disconnects; };
    callbacks.on_reconnect_failed = [&] { ++failed; };
    callbacks.on_reconnect_attempt = [&](int) { ++attempts; };
    fs::ReconnectingClient client("127.0.0.1", peer.port(), [&](const auto& info) { return engine.Prepare(info); },
        1, {}, std::move(callbacks), limits);
    ASSERT_TRUE(client.Connect());
    ASSERT_TRUE(Until([&] { client.Tick(fs::SlotInput::Default(), 0); return !client.connected(); }));
    EXPECT_EQ(client.state(), fs::ReconnectState::kFailed);
    EXPECT_EQ(client.last_error(), overload ? fs::TCPClientStatus::Capacity : fs::TCPClientStatus::HashMismatch);
    const auto steps = engine.steps;
    for (int i = 0; i < 20; ++i) { client.Poll(); client.Tick({1, 0, 0}); }
    EXPECT_EQ(engine.steps, steps); EXPECT_EQ(disconnects, 1); EXPECT_EQ(failed, 1); EXPECT_EQ(attempts, 0);
    EXPECT_EQ(client.stats().receive_capacity, 0u); EXPECT_EQ(client.stats().authority_bytes, 0u); peer.Join();
  }
}
TEST(ReconnectingClient, CloseInsideDisconnectCallbackCancelsAutomaticRecovery) {
  Peer peer({[](auto& socket, const auto&) { Hello(socket); Check(Read(socket, 1)[0] == 6); }});
  CounterEngine engine; fs::ReconnectingClient* active = nullptr; int disconnects = 0, attempts = 0;
  fs::ReconnectingClient::Callbacks callbacks;
  callbacks.on_disconnect = [&] { ++disconnects; active->Close(); };
  callbacks.on_reconnect_attempt = [&](int) { ++attempts; };
  fs::ReconnectingClient client("127.0.0.1", peer.port(), [&](const auto& info) { return engine.Prepare(info); },
      1, {}, std::move(callbacks)); active = &client;
  ASSERT_TRUE(client.Connect());
  ASSERT_TRUE(Until([&] { client.Poll(); return client.state() == fs::ReconnectState::kClosed; }));
  for (int i = 0; i < 20; ++i) client.Poll();
  EXPECT_EQ(disconnects, 1); EXPECT_EQ(attempts, 0); peer.Join();
}
TEST(ReconnectingClient, CloseOrThrowInsideRetryCallbackCannotStartANewConnection) {
  for (bool throwing : {false, true}) {
    asio::io_context io; tcp::acceptor unused(io, {tcp::v4(), 0});
    const auto port = unused.local_endpoint().port(); unused.close();
    CounterEngine engine; fs::ReconnectingClient::Clock::time_point now{};
    fs::ReconnectingClient* active = nullptr; int attempts = 0;
    fs::ReconnectingClient::Callbacks callbacks;
    callbacks.on_reconnect_attempt = [&](int) {
      ++attempts;
      if (throwing) throw std::runtime_error("host event failed");
      active->Close();
    };
    fs::ReconnectingClient client("127.0.0.1", port, [&](const auto& info) { return engine.Prepare(info); },
// 2026-09-09: call the explicit snapshot-budget constructor without a warning.
//         1, {}, std::move(callbacks), {}, {}, [&] { return now; }); active = &client;
        1, {}, std::move(callbacks), {}, fs::SnapshotBudget{}, [&] { return now; }); active = &client;
    EXPECT_FALSE(client.Connect()); now = client.next_attempt(); EXPECT_NO_THROW(client.Poll());
    EXPECT_EQ(client.state(), throwing ? fs::ReconnectState::kFailed : fs::ReconnectState::kClosed);
    now += 24h; for (int i = 0; i < 20; ++i) client.Poll();
    EXPECT_EQ(attempts, 1); EXPECT_EQ(engine.preparations, 0u);
  }
}
TEST(ReconnectingClient, CloseDuringEnginePreparationCannotReportConnectionSuccess) {
  Peer peer({[](auto& socket, const auto&) { Hello(socket); WaitClosed(socket); }});
  CounterEngine engine; fs::ReconnectingClient* active = nullptr;
  fs::ReconnectingClient client("127.0.0.1", peer.port(), [&](const auto& info) {
    active->Close(); return engine.Prepare(info);
  }, 1); active = &client;
  EXPECT_FALSE(client.Connect()); EXPECT_EQ(client.state(), fs::ReconnectState::kClosed);
  EXPECT_FALSE(client.connected()); EXPECT_EQ(engine.steps, 0u); peer.Join();
}
TEST(ReconnectingClient, FailedInitialEnginePreparationIsTerminal) {
  Peer peer({[](auto& socket, const auto&) { Hello(socket); WaitClosed(socket); }});
  int failures = 0; fs::ReconnectingClient::Callbacks callbacks;
  callbacks.on_reconnect_failed = [&] { ++failures; };
  fs::ReconnectingClient client("127.0.0.1", peer.port(), [](const auto&) -> fs::EngineCallbacks {
    throw std::runtime_error("cannot initialize actual host");
  }, 1, {}, std::move(callbacks));
  EXPECT_FALSE(client.Connect()); EXPECT_EQ(client.state(), fs::ReconnectState::kFailed);
  EXPECT_EQ(client.last_error(), fs::TCPClientStatus::EngineFailure);
  for (int i = 0; i < 20; ++i) client.Poll(); EXPECT_EQ(failures, 1); peer.Join();
}
TEST(ReconnectingClient, PartialResumeTimeoutRetriesTheSameSessionAndRestoresOnSecondAttempt) {
  Peer peer({[](auto& socket, const auto&) { Hello(socket); Check(Read(socket, 1)[0] == 6); },
    [](auto& socket, const auto&) { Hello(socket, true); Send(socket, {13, 50}); WaitClosed(socket); },
    [](auto& socket, const auto& stop) {
      Hello(socket, true); const uint64_t state = 1000; Bytes packet(17);
      Check(fs::PackStateSnapshot(50, &state, 8, packet.data(), packet.size()) == 17);
      Send(socket, packet); Check(Read(socket, 1)[0] == 6); Peer::Hold(stop);
    }});
  CounterEngine engine; fs::ReconnectingClient::Clock::time_point now{};
  fs::TCPClientLimits limits; limits.handshake_timeout = 100ms;
  int successes = 0; fs::ReconnectingClient::Callbacks callbacks;
  callbacks.on_reconnect_success = [&] { ++successes; };
  fs::ReconnectingClient client("127.0.0.1", peer.port(), [&](const auto& info) { return engine.Prepare(info); },
      0x12345678, {}, std::move(callbacks), limits, fs::SnapshotBudget{}, [&] { return now; });
  ASSERT_TRUE(client.Connect());
  ASSERT_TRUE(Until([&] { client.Poll(); return client.state() == fs::ReconnectState::kReconnecting; }));
  now = client.next_attempt(); client.Poll();
  ASSERT_EQ(client.state(), fs::ReconnectState::kReconnecting);
  EXPECT_EQ(client.last_error(), fs::TCPClientStatus::HandshakeTimeout); EXPECT_EQ(client.attempts(), 1);
  EXPECT_EQ(client.stats().receive_capacity, 0u); EXPECT_EQ(client.stats().snapshot_capacity, 0u);
  EXPECT_EQ(engine.preparations, 1u); EXPECT_EQ(engine.state, 0u); EXPECT_EQ(successes, 0);
  now = client.next_attempt(); client.Poll(); ASSERT_TRUE(client.connected());
  EXPECT_EQ(client.attempts(), 2); EXPECT_EQ(client.next_frame(), 50u); EXPECT_EQ(engine.state, 1000u);
  EXPECT_EQ(engine.preparations, 1u); EXPECT_EQ(successes, 1); client.Poll(); peer.Join();
}
TEST(ReconnectingClient, InvalidEngineSnapshotDoesNotSendReadyOrRetry) {
  Peer peer({[](auto& socket, const auto&) { Hello(socket); Check(Read(socket, 1)[0] == 6); },
    [](auto& socket, const auto&) {
      Hello(socket, true); const uint8_t wrong_state = 1; Bytes packet(10);
      Check(fs::PackStateSnapshot(50, &wrong_state, 1, packet.data(), packet.size()) == 10);
      Send(socket, packet);
      // No Ready or gameplay input may be sent after the host rejects restore.
      socket.non_blocking(true);
      Check(Until([&] { uint8_t byte; boost::system::error_code ec;
        const auto count = socket.read_some(asio::buffer(&byte, 1), ec); Check(count == 0);
        return ec == asio::error::eof || ec == asio::error::connection_reset;
      }));
    }});
  CounterEngine engine; fs::ReconnectingClient::Clock::time_point now{};
  int successes = 0, failures = 0; fs::ReconnectingClient::Callbacks callbacks;
  callbacks.on_reconnect_success = [&] { ++successes; };
  callbacks.on_reconnect_failed = [&] { ++failures; };
  fs::ReconnectingClient client("127.0.0.1", peer.port(), [&](const auto& info) { return engine.Prepare(info); },
      0x12345678, {}, std::move(callbacks), {}, fs::SnapshotBudget{}, [&] { return now; });
  ASSERT_TRUE(client.Connect());
  ASSERT_TRUE(Until([&] { client.Poll(); return client.state() == fs::ReconnectState::kReconnecting; }));
  now = client.next_attempt(); client.Poll(); EXPECT_EQ(client.state(), fs::ReconnectState::kFailed);
  EXPECT_EQ(client.last_error(), fs::TCPClientStatus::EngineFailure); EXPECT_EQ(successes, 0); EXPECT_EQ(failures, 1);
  EXPECT_EQ(engine.state, 0u); EXPECT_EQ(engine.steps, 0u); EXPECT_EQ(client.stats().snapshot_capacity, 0u);
  now += 24h; for (int i = 0; i < 20; ++i) client.Poll(); EXPECT_EQ(client.attempts(), 1); peer.Join();
}
}  // namespace
