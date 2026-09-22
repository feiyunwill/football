// 2026-09-09: real TCP peers exercise the production polled lobby client.
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
struct Peer {
  asio::io_context io;
  tcp::acceptor acceptor{io, {tcp::v4(), 0}};
  fs::LobbyClient client;
  tcp::socket socket{io};
  explicit Peer(fs::StreamBudget budget = fs::StreamBudget(256, 128 * 1024)) : client(io, budget) {
    if (!client.connect("127.0.0.1", acceptor.local_endpoint().port()))
      throw std::runtime_error("loopback connect failed");
    socket = acceptor.accept();
  }
  void Send(const std::vector<uint8_t>& bytes) { asio::write(socket, asio::buffer(bytes)); }
  bool Receive(std::vector<uint8_t>& bytes, size_t count) {
    socket.non_blocking(true);
    return Until([&] {
      client.poll();
      std::array<uint8_t, 4096> buffer;
      boost::system::error_code ec;
      size_t length = socket.read_some(asio::buffer(buffer), ec);
      if (length) bytes.insert(bytes.end(), buffer.begin(), buffer.begin() + length);
      return bytes.size() >= count;
    });
  }
};
std::vector<uint8_t> Chat(const std::string& name, const std::string& message) {
  std::vector<uint8_t> bytes(9 + name.size() + message.size());
  bytes[0] = std::to_underlying(fs::LobbyMessageType::ChatMessage);
  fs::PackUint32(bytes.data() + 1, 1);
  size_t offset = 5;
  offset += fs::PackString(bytes.data() + offset, bytes.size() - offset, name);
  fs::PackString(bytes.data() + offset, bytes.size() - offset, message);
  return bytes;
}
size_t ChatBytes(const fs::LobbyClient& client) {
  size_t bytes = 0;
  for (const auto& [name, message] : client.get_chats()) bytes += name.capacity() + message.capacity() + 2;
  return bytes;
}

TEST(LobbyClientCapacity, CountLimitIsReservedBeforeIoAndOverflowDisconnectsExplicitly) {
  Peer p(fs::StreamBudget(2, 128));
  ASSERT_TRUE(p.client.set_name("Name"));
  ASSERT_TRUE(p.client.request_room_list());
  EXPECT_EQ(p.client.stats().queued_send_messages, 2u);
  EXPECT_EQ(p.client.stats().queued_send_bytes, 8u);
  EXPECT_FALSE(p.client.request_room_list());
  EXPECT_EQ(p.client.status(), fs::LobbyClientStatus::SendCapacity);
  EXPECT_FALSE(p.client.is_connected());
  EXPECT_EQ(p.client.stats().queued_send_bytes, 0u);
  p.client.poll();
  p.socket.non_blocking(true);
  size_t application_bytes = 0;
  boost::system::error_code ec;
  EXPECT_TRUE(Until([&] {
    p.client.poll(); std::array<uint8_t, 128> bytes{};
    application_bytes += p.socket.read_some(asio::buffer(bytes), ec);
    return ec && ec != asio::error::would_block && ec != asio::error::try_again;
  }));
  EXPECT_EQ(application_bytes, 0u);
  EXPECT_EQ(ec, asio::error::eof);
}
TEST(LobbyClientCapacity, ByteLimitIsIndependentOfMessageCount) {
  Peer p(fs::StreamBudget(256, 8));
  ASSERT_TRUE(p.client.set_name("Name"));
  ASSERT_TRUE(p.client.request_room_list());
  EXPECT_FALSE(p.client.request_room_list());
  EXPECT_EQ(p.client.status(), fs::LobbyClientStatus::SendCapacity);
  EXPECT_EQ(p.client.stats().queued_send_messages, 0u);
}
TEST(LobbyClientCapacity, FullQueueDrainsInOrderAndCanBeReusedOneHundredTimes) {
  Peer p(fs::StreamBudget(2, 10));
  for (size_t cycle = 0; cycle < 100; ++cycle) {
    ASSERT_TRUE(p.client.join_room(static_cast<uint32_t>(cycle)));
    ASSERT_TRUE(p.client.leave_room(static_cast<uint32_t>(cycle)));
    EXPECT_EQ(p.client.stats().queued_send_bytes, 10u);
    std::vector<uint8_t> bytes;
    ASSERT_TRUE(p.Receive(bytes, 10));
    ASSERT_EQ(bytes.size(), 10u);
    EXPECT_EQ(bytes[0], std::to_underlying(fs::LobbyMessageType::JoinRoom));
    EXPECT_EQ(bytes[5], std::to_underlying(fs::LobbyMessageType::LeaveRoom));
    uint32_t first, second;
    fs::UnpackUint32(bytes.data() + 1, 4, &first);
    fs::UnpackUint32(bytes.data() + 6, 4, &second);
    EXPECT_EQ(first, cycle); EXPECT_EQ(second, cycle);
    ASSERT_TRUE(Until([&] { p.client.poll(); return p.client.stats().queued_send_bytes == 0; }));
    EXPECT_TRUE(p.client.is_connected());
  }
}
TEST(LobbyClientCapacity, OversizedHeadersAndUnknownTypesFailBeforePayloadArrival) {
  const std::vector<std::vector<uint8_t>> headers = {
    {11, 1, 1},                         // 257 rooms
    {13, 0, 0, 0, 0, 33, 0},           // sender length 33
    {13, 0, 0, 0, 0, 0, 0, 1, 16},    // chat length 4097
    {14, 0, 0, 0, 0, 33, 0},           // player name 33
    {20, 0, 0, 1, 16},                 // error length 4097
    {254}
  };
  for (const auto& bytes : headers) {
    Peer p; p.Send(bytes);
    ASSERT_TRUE(Until([&] { p.client.poll(); return !p.client.is_connected(); }));
    EXPECT_EQ(p.client.status(), fs::LobbyClientStatus::InvalidMessage);
    EXPECT_EQ(p.client.stats().receive_capacity, 0u);
    EXPECT_TRUE(p.client.get_rooms().empty());
    EXPECT_TRUE(p.client.get_chats().empty());
  }
}
TEST(LobbyClientCapacity, MaximumRoomListFragmentedThenCoalescedMessageIsPreserved) {
  Peer p;
  std::vector<uint8_t> bytes(3 + 256 * fs::ROOM_METADATA_SIZE + 5);
  bytes[0] = 11; fs::PackUint16(bytes.data() + 1, 256);
  for (size_t i = 0; i < 256; ++i) {
    fs::RoomMetadata room; room.room_id = static_cast<uint32_t>(i + 1);
    fs::PackRoomMetadata(room, bytes.data() + 3 + i * fs::ROOM_METADATA_SIZE, fs::ROOM_METADATA_SIZE);
  }
  bytes[bytes.size() - 5] = 10;
  fs::PackUint32(bytes.data() + bytes.size() - 4, 987);
  unsigned callbacks = 0;
  p.client.on_message([&](fs::LobbyMessageType, const uint8_t*, size_t) { ++callbacks; });
  for (size_t offset = 0; offset < bytes.size();) {
    const auto length = std::min(size_t(997), bytes.size() - offset);
    asio::write(p.socket, asio::buffer(bytes.data() + offset, length));
    offset += length; p.client.poll();
  }
  ASSERT_TRUE(Until([&] { p.client.poll(); return callbacks == 2; }));
  ASSERT_EQ(p.client.get_rooms().size(), 256u);
  EXPECT_EQ(p.client.get_rooms().back().room_id, 256u);
  EXPECT_LE(p.client.stats().receive_capacity, fs::LobbyClient::kReceiveLimit);
  EXPECT_LE(p.client.stats().room_storage_bytes, 256 * fs::ROOM_METADATA_SIZE);
  EXPECT_LE(p.client.stats().last_poll_handlers, fs::LobbyClient::kPollHandlerLimit);
}
TEST(LobbyClientCapacity, ByteBoundedChatHistoryAccountsMixedStringCapacitiesAndRecovers) {
  Peer p; size_t messages = 0;
  p.client.on_message([&](fs::LobbyMessageType type, const uint8_t*, size_t) {
    if (type == fs::LobbyMessageType::ChatMessage) ++messages;
  });
  for (size_t i = 0; i < 600; ++i) {
    p.Send(Chat(i % 3 ? "A" : std::string(32, 'n'), i % 2 ? "tiny" : std::string(4096, 'x')));
    ASSERT_TRUE(Until([&] { p.client.poll(); return messages == i + 1; }));
    EXPECT_EQ(p.client.stats().chat_string_bytes, ChatBytes(p.client));
    EXPECT_LE(p.client.stats().chat_string_bytes, fs::LobbyClient::kChatByteLimit);
    EXPECT_LE(p.client.get_chats().size(), fs::LobbyClient::kChatLimit);
  }
  EXPECT_GT(p.client.stats().evicted_chats, 0u);
  EXPECT_EQ(p.client.get_chats().back().second, "tiny");
  p.client.pop_chats();
  EXPECT_EQ(p.client.stats().chat_string_bytes, 0u);
  EXPECT_LE(p.client.stats().chat_storage_bytes,
            fs::LobbyClient::kChatLimit * sizeof(std::pair<std::string, std::string>));
  p.Send(Chat("A", "after drain"));
  ASSERT_TRUE(Until([&] { p.client.poll(); return messages == 601; }));
  ASSERT_EQ(p.client.get_chats().size(), 1u);
  EXPECT_EQ(p.client.get_chats().front().second, "after drain");
}
TEST(LobbyClientCapacity, ChatCountLimitRetainsLatestMessagesBelowByteLimit) {
  Peer p; size_t messages = 0;
  p.client.on_message([&](fs::LobbyMessageType, const uint8_t*, size_t) { ++messages; });
  for (size_t i = 0; i < 1100; ++i) {
    p.Send(Chat("A", std::to_string(i)));
    ASSERT_TRUE(Until([&] { p.client.poll(); return messages == i + 1; }));
  }
  ASSERT_EQ(p.client.get_chats().size(), 1024u);
  EXPECT_EQ(p.client.get_chats().front().second, "76");
  EXPECT_EQ(p.client.get_chats().back().second, "1099");
  EXPECT_EQ(p.client.stats().evicted_chats, 76u);
  EXPECT_EQ(p.client.stats().chat_string_bytes, ChatBytes(p.client));
}
TEST(LobbyClientCapacity, CallbackCanDisconnectReplaceItselfAndKeepPacketAlive) {
  Peer p; unsigned calls = 0, replacement_calls = 0;
  p.client.on_message([&](fs::LobbyMessageType type, const uint8_t* data, size_t length) {
    ++calls;
    EXPECT_EQ(type, fs::LobbyMessageType::RoomCreated);
    ASSERT_EQ(length, 5u);
    p.client.disconnect();
    p.client.on_message([&](fs::LobbyMessageType, const uint8_t*, size_t) { ++replacement_calls; });
    p.client.poll();  // Nested polling is ignored.
    EXPECT_FALSE(p.client.connect("127.0.0.1", p.acceptor.local_endpoint().port()));
    EXPECT_EQ(data[0], 10);
    uint32_t room; fs::UnpackUint32(data + 1, 4, &room); EXPECT_EQ(room, 1u);
  });
  p.Send({10, 1, 0, 0, 0, 10, 2, 0, 0, 0});
  ASSERT_TRUE(Until([&] { p.client.poll(); return calls == 1; }));
  EXPECT_EQ(replacement_calls, 0u);
  ASSERT_TRUE(p.client.connect("127.0.0.1", p.acceptor.local_endpoint().port()));
  p.socket = p.acceptor.accept();
  p.Send({10, 3, 0, 0, 0});
  ASSERT_TRUE(Until([&] { p.client.poll(); return replacement_calls == 1; }));
}
TEST(LobbyClientCapacity, InvalidRoomMetadataDoesNotReplacePreviouslyValidList) {
  Peer p; unsigned calls = 0;
  p.client.on_message([&](fs::LobbyMessageType, const uint8_t*, size_t) { ++calls; });
  fs::RoomMetadata room; room.room_id = 456;
  std::vector<uint8_t> bytes(3 + fs::ROOM_METADATA_SIZE);
  bytes[0] = 11; fs::PackUint16(bytes.data() + 1, 1);
  fs::PackRoomMetadata(room, bytes.data() + 3, fs::ROOM_METADATA_SIZE);
  p.Send(bytes);
  ASSERT_TRUE(Until([&] { p.client.poll(); return calls == 1; }));
  std::memset(bytes.data() + 3 + offsetof(fs::RoomMetadata, name), 'x', sizeof(room.name));
  p.Send(bytes);
  ASSERT_TRUE(Until([&] { p.client.poll(); return !p.client.is_connected(); }));
  EXPECT_EQ(p.client.status(), fs::LobbyClientStatus::InvalidMessage);
  ASSERT_EQ(p.client.get_rooms().size(), 1u);
  EXPECT_EQ(p.client.get_rooms().front().room_id, 456u);
  EXPECT_EQ(calls, 1u);
}
TEST(LobbyClientCapacity, DestructionDiscardsNeverDispatchedReadsAndWritesSafely) {
  asio::io_context io;
  tcp::acceptor acceptor(io, {tcp::v4(), 0});
  auto client = std::make_unique<fs::LobbyClient>(io);
  ASSERT_TRUE(client->connect("127.0.0.1", acceptor.local_endpoint().port()));
  auto peer = acceptor.accept();
  ASSERT_TRUE(client->send_chat(1, std::string(4096, 'x')));
  client->on_message([](fs::LobbyMessageType, const uint8_t*, size_t) { ADD_FAILURE(); });
  client.reset();
  peer.non_blocking(true);
  boost::system::error_code ec;
  EXPECT_TRUE(Until([&] {
    std::array<uint8_t, 1> bytes; peer.read_some(asio::buffer(bytes), ec);
    return ec == asio::error::eof || ec == asio::error::connection_reset;
  }));
}
}  // namespace
