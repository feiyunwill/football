// 2026-09-09: production lobby connections, parser limits and overload recovery.
#include "frame_sync/lobby_server.hpp"
#include "frame_sync/lobby_client.hpp"
#include <gtest/gtest.h>
#include <thread>

namespace {
namespace asio = boost::asio;
namespace fs = frame_sync;
using tcp = asio::ip::tcp;
using namespace std::chrono_literals;

template<class Predicate> bool Until(Predicate predicate) {
  const auto deadline = std::chrono::steady_clock::now() + 2s;
  while (std::chrono::steady_clock::now() < deadline) {
    if (predicate()) return true;
    std::this_thread::sleep_for(1ms);
  }
  return false;
}
struct Harness {
  asio::io_context server_io;
  fs::LobbyServer server;
  std::thread thread;
  asio::io_context client_io;
  explicit Harness(fs::LobbyLimits limits = fs::LobbyLimits{})
      : server(server_io, 0, limits), thread([this] { server_io.run(); }) {}
  ~Harness() { server.stop(); if (thread.joinable()) thread.join(); }
  Harness(const Harness&) = delete;
  Harness& operator=(const Harness&) = delete;
  Harness(Harness&&) = delete;
  Harness& operator=(Harness&&) = delete;
  std::unique_ptr<tcp::socket> Connect() {
    auto socket = std::make_unique<tcp::socket>(client_io);
    socket->connect({asio::ip::address_v4::loopback(), server.port()});
    return socket;
  }
};
bool Closed(tcp::socket& socket) {
  boost::system::error_code ec;
  socket.non_blocking(true, ec);
  bool ended = Until([&] {
    std::array<uint8_t, 4096> discarded{};
    socket.read_some(asio::buffer(discarded), ec);
    return ec && ec != asio::error::would_block && ec != asio::error::try_again;
  });
  return ended && (ec == asio::error::eof || ec == asio::error::connection_reset);
}
void Send(tcp::socket& socket, const std::vector<uint8_t>& bytes) {
  asio::write(socket, asio::buffer(bytes));
}

TEST(LobbyCapacity, ConstructorRejectsBadLimits) {
  EXPECT_THROW(fs::LobbyLimits(0), std::invalid_argument);
  EXPECT_THROW(fs::LobbyLimits(1025), std::invalid_argument);
  EXPECT_THROW((fs::LobbyLimits(1, 0, 128)), std::invalid_argument);
  EXPECT_THROW((fs::LobbyLimits(1, 1, 0)), std::invalid_argument);
  EXPECT_THROW((fs::LobbyLimits(1, 1, 128, 0ms)), std::invalid_argument);
  asio::io_context io;
  fs::LobbyLimits mutated;
  mutated.connection_limit = 0;
  EXPECT_THROW((fs::LobbyServer(io, 0, mutated)), std::invalid_argument);
}

TEST(LobbyCapacity, RejectsExcessConnectionThenAcceptsAfterActualDisconnect) {
  Harness h(fs::LobbyLimits(3));
  auto first = h.Connect(), second = h.Connect(), third = h.Connect();
  ASSERT_TRUE(Until([&] { return h.server.stats().connections == 3; }));
  auto rejected = h.Connect();
  ASSERT_TRUE(Closed(*rejected));
  EXPECT_EQ(h.server.stats().connections, 3u);
  EXPECT_EQ(h.server.stats().rejected_connections, 1u);
  second->close();
  ASSERT_TRUE(Until([&] { return h.server.stats().connections == 2; }));
  auto replacement = h.Connect();
  ASSERT_TRUE(Until([&] { return h.server.stats().connections == 3; }));
  EXPECT_EQ(h.server.stats().rejected_connections, 1u);
}

TEST(LobbyCapacity, UnidentifiedReservationExpiresButNamedConnectionSurvives) {
  Harness h(fs::LobbyLimits(3, 256, 128 * 1024, 150ms));
  auto anonymous = h.Connect(), named = h.Connect();
  Send(*named, {0xFF, 4, 0, 'N', 'a', 'm', 'e'});
  ASSERT_TRUE(Until([&] { return h.server.stats().identified_connections == 1; }));
  ASSERT_TRUE(Closed(*anonymous));
  ASSERT_TRUE(Until([&] { return h.server.stats().connections == 1; }));
  EXPECT_EQ(h.server.stats().identified_connections, 1u);
  Send(*named, {std::to_underlying(fs::LobbyMessageType::RoomList)});
  std::array<uint8_t, 3> response{};
  EXPECT_EQ(asio::read(*named, asio::buffer(response)), 3u);
  EXPECT_EQ(response[0], std::to_underlying(fs::LobbyMessageType::RoomListResponse));
}

TEST(LobbyCapacity, OversizedLengthHeadersAreRejectedWithoutTheirPayloads) {
  Harness h;
  std::vector<std::vector<uint8_t>> invalid = {
    {0xFF, 0xFF, 0xFF},
    {std::to_underlying(fs::LobbyMessageType::Chat), 0, 0, 0, 0, 1, 16},
    {std::to_underlying(fs::LobbyMessageType::StartGame), 0, 0, 0, 0, 97, 0}
  };
  for (const auto& header : invalid) {
    auto peer = h.Connect();
    Send(*peer, header);
    ASSERT_TRUE(Closed(*peer));
    ASSERT_TRUE(Until([&] { return h.server.stats().connections == 0; }));
  }
  EXPECT_EQ(h.server.stats().invalid_messages, invalid.size());
  EXPECT_EQ(h.server.stats().receive_capacity, 0u);
}

TEST(LobbyCapacity, InvalidConfigBoolAndUnterminatedStringAreRejectedBeforeRoomCreation) {
  Harness h;
  for (bool invalid_bool : {true, false}) {
    auto peer = h.Connect();
    fs::RoomConfig config;
    std::vector<uint8_t> bytes(1 + fs::ROOM_CONFIG_SIZE);
    bytes[0] = std::to_underlying(fs::LobbyMessageType::CreateRoom);
    fs::PackRoomConfig(config, bytes.data() + 1, fs::ROOM_CONFIG_SIZE);
    if (invalid_bool) bytes[1 + offsetof(fs::RoomConfig, allow_spectators)] = 255;
    else std::memset(bytes.data() + 1 + offsetof(fs::RoomConfig, name), 'x', sizeof(config.name));
    Send(*peer, bytes);
    ASSERT_TRUE(Closed(*peer));
    ASSERT_TRUE(Until([&] { return h.server.stats().connections == 0; }));
  }
  EXPECT_EQ(h.server.stats().invalid_messages, 2u);
}

TEST(LobbyCapacity, OutboundMessageCapDisconnectsFlooderAndHealthyPeerStillWorks) {
  Harness h(fs::LobbyLimits(4, 8, 128 * 1024));
  fs::LobbyClient healthy(h.client_io);
  ASSERT_TRUE(healthy.connect("127.0.0.1", h.server.port()));
  healthy.set_name("Healthy");
  unsigned replies = 0;
  healthy.on_message([&](fs::LobbyMessageType type, const uint8_t*, size_t) {
    if (type == fs::LobbyMessageType::RoomListResponse) ++replies;
  });
  healthy.request_room_list();
  ASSERT_TRUE(Until([&] { healthy.poll(); return replies == 1; }));
  auto flooder = h.Connect();
  Send(*flooder, std::vector<uint8_t>(128, std::to_underlying(fs::LobbyMessageType::RoomList)));
  ASSERT_TRUE(Closed(*flooder));
  ASSERT_TRUE(Until([&] { return h.server.stats().connections == 1; }));
  EXPECT_EQ(h.server.stats().overload_disconnects, 1u);
  healthy.request_room_list();
  ASSERT_TRUE(Until([&] { healthy.poll(); return replies == 2; }));
  EXPECT_TRUE(healthy.is_connected());
  EXPECT_LE(h.server.stats().queued_send_messages, 8u);
}

TEST(LobbyCapacity, OutboundByteCapIsIndependentOfMessageCapAndRecovers) {
  Harness h(fs::LobbyLimits(2, 256, 64));
  auto flooder = h.Connect();
  Send(*flooder, std::vector<uint8_t>(128, std::to_underlying(fs::LobbyMessageType::RoomList)));
  ASSERT_TRUE(Closed(*flooder));
  ASSERT_TRUE(Until([&] { return h.server.stats().connections == 0; }));
  EXPECT_EQ(h.server.stats().overload_disconnects, 1u);
  EXPECT_EQ(h.server.stats().queued_send_bytes, 0u);
  auto normal = h.Connect();
  Send(*normal, {std::to_underlying(fs::LobbyMessageType::RoomList)});
  std::array<uint8_t, 3> response{};
  EXPECT_EQ(asio::read(*normal, asio::buffer(response)), 3u);
  EXPECT_EQ(response[0], std::to_underlying(fs::LobbyMessageType::RoomListResponse));
}

TEST(LobbyCapacity, LargestChatWithFragmentationAndFollowingMessageRemainsValid) {
  Harness h;
  fs::LobbyClient host(h.client_io);
  ASSERT_TRUE(host.connect("127.0.0.1", h.server.port()));
  host.set_name("Host");
  host.create_room("Capacity", "academy_empty_goal_close");
  host.request_room_list();
  ASSERT_TRUE(Until([&] { host.poll(); return !host.get_rooms().empty(); }));
  const auto room = host.get_rooms()[0].room_id;
  auto peer = h.Connect();
  std::vector<uint8_t> intro{0xFF, 4, 0, 'P', 'e', 'e', 'r',
                           std::to_underlying(fs::LobbyMessageType::JoinRoom), 0, 0, 0, 0};
  fs::PackUint32(intro.data() + 8, room);
  Send(*peer, intro);
  ASSERT_TRUE(Until([&] { return h.server.stats().identified_connections == 2; }));
  std::vector<uint8_t> chat(7 + 4096 + 1, 'x');
  chat[0] = std::to_underlying(fs::LobbyMessageType::Chat);
  fs::PackUint32(chat.data() + 1, room);
  fs::PackUint16(chat.data() + 5, 4096);
  chat.back() = std::to_underlying(fs::LobbyMessageType::RoomList);
  asio::write(*peer, asio::buffer(chat.data(), 4102));
  asio::write(*peer, asio::buffer(chat.data() + 4102, chat.size() - 4102));
  ASSERT_TRUE(Until([&] { host.poll(); return !host.get_chats().empty(); }));
  EXPECT_EQ(host.get_chats().back().second, std::string(4096, 'x'));
  EXPECT_EQ(h.server.stats().connections, 2u);
  EXPECT_LE(h.server.stats().receive_capacity, 2u * 16 * 1024);
  EXPECT_EQ(h.server.stats().invalid_messages, 0u);
}

TEST(LobbyCapacity, DestroyServerWithActiveReadsAndQueuedOutputDrainsCallbacks) {
  asio::io_context io, client_io;
  auto server = std::make_unique<fs::LobbyServer>(io, 0);
  const auto port = server->port();
  std::thread thread([&] { io.run(); });
  {
    tcp::socket peer(client_io);
    peer.connect({asio::ip::address_v4::loopback(), port});
    Send(peer, std::vector<uint8_t>(200, std::to_underlying(fs::LobbyMessageType::RoomList)));
    // The public server is gone while its IO callbacks still own the actor.
    server.reset();
    thread.join();
    EXPECT_TRUE(Closed(peer));
  }
}

TEST(LobbyCapacity, StoppedIoCanDestroyServerAndPendingHandlersWithoutResurrection) {
  asio::io_context io, client_io;
  {
    auto server = std::make_unique<fs::LobbyServer>(io, 0);
    tcp::socket peer(client_io);
    peer.connect({asio::ip::address_v4::loopback(), server->port()});
    Send(peer, {std::to_underlying(fs::LobbyMessageType::RoomList)});
    io.poll();
    io.stop();
    server.reset();
  }
  // ASan/LSan observe destruction of never-run cancellation callbacks below.
}
}  // namespace
