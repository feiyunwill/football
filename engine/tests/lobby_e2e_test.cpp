// Copyright 2026 Google LLC & Contributors
// End-to-end test for lobby system (ms-18.5)
// Tests: lobby server + multiple clients, room create/join/chat/ready/start

#include "frame_sync/lobby_protocol.hpp"
#include "frame_sync/room_manager.hpp"
#include "frame_sync/lobby_client.hpp"

#include <gtest/gtest.h>
#include <boost/asio.hpp>
#include <thread>
#include <chrono>
#include <memory>
#include <vector>
#include <string>

namespace frame_sync {
namespace {

// ===== Lobby Server (minimal for testing) =====
// Simplified lobby server that handles basic protocol messages
class TestLobbyServer {
 private:
  struct TestClient {
    boost::asio::ip::tcp::socket socket;
    std::string name;
    uint32_t current_room = 0;
    std::vector<uint8_t> recv_buf;
    bool disconnected = false;
    explicit TestClient(boost::asio::ip::tcp::socket s) : socket(std::move(s)) {}
  };

 public:
  TestLobbyServer(boost::asio::io_context& io, unsigned short port)
      : io_(io), acceptor_(io, boost::asio::ip::tcp::endpoint(boost::asio::ip::tcp::v4(), port)) {
    do_accept();
  }

  void do_accept() {
    acceptor_.async_accept([this](boost::system::error_code ec, boost::asio::ip::tcp::socket socket) {
      if (ec) return;
      auto client = std::make_shared<TestClient>(std::move(socket));
      {
        std::lock_guard<std::mutex> lock(mu_);
        clients_.push_back(client);
      }
      do_read(client);
      do_accept();
    });
  }

  void do_read(std::shared_ptr<TestClient> client) {
    auto buf = std::make_shared<std::vector<uint8_t>>(4096);
    client->socket.async_read_some(
        boost::asio::buffer(*buf),
        [this, client, buf](boost::system::error_code ec, std::size_t length) {
          if (ec) {
            std::lock_guard<std::mutex> lock(mu_);
            client->disconnected = true;
            if (client->current_room != 0) {
              room_mgr_.LeaveRoom(client->current_room, client->name);
            }
            return;
          }
          std::lock_guard<std::mutex> lock(mu_);
          client->recv_buf.insert(client->recv_buf.end(), buf->begin(), buf->begin() + length);
          while (process_one(client)) {}
          do_read(client);
        });
  }

  bool process_one(std::shared_ptr<TestClient> client) {
    if (client->recv_buf.empty()) return false;
    uint8_t type = client->recv_buf[0];

    // NameSet (0xFF)
    if (type == 0xFF) {
      if (client->recv_buf.size() < 3) return false;
      uint16_t name_len;
      UnpackUint16(client->recv_buf.data() + 1, 2, &name_len);
      if (client->recv_buf.size() < 3 + name_len) return false;
      client->name.assign(client->recv_buf.begin() + 3, client->recv_buf.begin() + 3 + name_len);
      client->recv_buf.erase(client->recv_buf.begin(), client->recv_buf.begin() + 3 + name_len);
      return true;
    }

    // CreateRoom
    if (type == static_cast<uint8_t>(LobbyMessageType::CreateRoom)) {
      if (client->recv_buf.size() < 1 + ROOM_CONFIG_SIZE) return false;
      RoomConfig config;
      UnpackRoomConfig(client->recv_buf.data() + 1, ROOM_CONFIG_SIZE, &config);
      uint32_t id = room_mgr_.CreateRoom(config, client->name);
      client->current_room = id;

      uint8_t resp[5];
      resp[0] = static_cast<uint8_t>(LobbyMessageType::RoomCreated);
      PackUint32(resp + 1, id);
      send_to(client, resp, 5);
      client->recv_buf.erase(client->recv_buf.begin(), client->recv_buf.begin() + 1 + ROOM_CONFIG_SIZE);
      return true;
    }

    // JoinRoom
    if (type == static_cast<uint8_t>(LobbyMessageType::JoinRoom)) {
      if (client->recv_buf.size() < 5) return false;
      uint32_t room_id;
      UnpackUint32(client->recv_buf.data() + 1, 4, &room_id);
      bool ok = room_mgr_.JoinRoom(room_id, client->name);
      if (ok) client->current_room = room_id;

      // Send RoomInfo
      const auto* meta = room_mgr_.GetRoomMetadata(room_id);
      if (meta) {
        std::vector<uint8_t> buf(1 + ROOM_METADATA_SIZE);
        buf[0] = static_cast<uint8_t>(LobbyMessageType::RoomInfo);
        PackRoomMetadata(*meta, buf.data() + 1, ROOM_METADATA_SIZE);
        send_to(client, buf.data(), buf.size());
      }
      client->recv_buf.erase(client->recv_buf.begin(), client->recv_buf.begin() + 5);
      return true;
    }

    // RoomList
    if (type == static_cast<uint8_t>(LobbyMessageType::RoomList)) {
      auto rooms = room_mgr_.ListRooms();
      std::vector<uint8_t> buf(3 + rooms.size() * ROOM_METADATA_SIZE);
      buf[0] = static_cast<uint8_t>(LobbyMessageType::RoomListResponse);
      PackUint16(buf.data() + 1, static_cast<uint16_t>(rooms.size()));
      for (size_t i = 0; i < rooms.size(); ++i) {
        PackRoomMetadata(rooms[i], buf.data() + 3 + i * ROOM_METADATA_SIZE, ROOM_METADATA_SIZE);
      }
      send_to(client, buf.data(), 3 + rooms.size() * ROOM_METADATA_SIZE);
      client->recv_buf.erase(client->recv_buf.begin());
      return true;
    }

    // Ready
    if (type == static_cast<uint8_t>(LobbyMessageType::Ready)) {
      if (client->recv_buf.size() < 5) return false;
      uint32_t room_id;
      UnpackUint32(client->recv_buf.data() + 1, 4, &room_id);
      room_mgr_.SetReady(room_id, client->name, true);
      client->recv_buf.erase(client->recv_buf.begin(), client->recv_buf.begin() + 5);
      return true;
    }

    // Chat
    if (type == static_cast<uint8_t>(LobbyMessageType::Chat)) {
      if (client->recv_buf.size() < 7) return false;
      uint32_t room_id;
      UnpackUint32(client->recv_buf.data() + 1, 4, &room_id);
      uint16_t msg_len;
      UnpackUint16(client->recv_buf.data() + 5, 2, &msg_len);
      size_t need = 7 + msg_len;
      if (client->recv_buf.size() < need) return false;
      std::string msg(client->recv_buf.begin() + 7, client->recv_buf.begin() + 7 + msg_len);

      // Broadcast to room
      std::vector<uint8_t> bcast(1 + 4 + 2 + client->name.size() + 2 + msg.size());
      bcast[0] = static_cast<uint8_t>(LobbyMessageType::ChatMessage);
      size_t off = 1;
      off += PackUint32(bcast.data() + off, room_id);
      off += PackString(bcast.data() + off, bcast.size() - off, client->name);
      off += PackString(bcast.data() + off, bcast.size() - off, msg);
      broadcast_to_room(room_id, bcast.data(), off);

      client->recv_buf.erase(client->recv_buf.begin(), client->recv_buf.begin() + need);
      return true;
    }

    client->recv_buf.erase(client->recv_buf.begin());
    return true;
  }

  void send_to(std::shared_ptr<TestClient> client, const uint8_t* data, size_t len) {
    boost::system::error_code ec;
    boost::asio::write(client->socket, boost::asio::buffer(data, len), ec);
  }

  void broadcast_to_room(uint32_t room_id, const uint8_t* data, size_t len) {
    for (auto& c : clients_) {
      if (c->disconnected || c->current_room != room_id) continue;
      send_to(c, data, len);
    }
  }

  void stop() {
    boost::system::error_code ec;
    acceptor_.close(ec);
  }

 private:
  boost::asio::io_context& io_;
  boost::asio::ip::tcp::acceptor acceptor_;
  std::mutex mu_;
  std::vector<std::shared_ptr<TestClient>> clients_;
  RoomManager room_mgr_;
};

// ===== Tests =====

TEST(LobbyE2ETest, CreateAndListRooms) {
  const unsigned short port = 19900;
  boost::asio::io_context io;

  TestLobbyServer server(io, port);
  std::thread io_thread([&io]() { io.run(); });

  std::this_thread::sleep_for(std::chrono::milliseconds(50));

  LobbyClient client(io);
  ASSERT_TRUE(client.connect("127.0.0.1", port));
  client.set_name("Alice");

  client.create_room("Test Room", "academy_empty_goal_close", 2);
  client.poll();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  client.poll();

  client.request_room_list();
  client.poll();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  client.poll();

  auto rooms = client.get_rooms();
  EXPECT_GE(rooms.size(), 1u);
  if (!rooms.empty()) {
    EXPECT_STREQ(rooms[0].name, "Test Room");
    EXPECT_EQ(rooms[0].player_count, 1);
  }

  client.disconnect();
  server.stop();
  io.stop();
  io_thread.join();
}

TEST(LobbyE2ETest, TwoPlayersJoinRoom) {
  const unsigned short port = 19901;
  boost::asio::io_context io;

  TestLobbyServer server(io, port);
  std::thread io_thread([&io]() { io.run(); });

  std::this_thread::sleep_for(std::chrono::milliseconds(50));

  LobbyClient alice(io);
  LobbyClient bob(io);

  ASSERT_TRUE(alice.connect("127.0.0.1", port));
  alice.set_name("Alice");
  ASSERT_TRUE(bob.connect("127.0.0.1", port));
  bob.set_name("Bob");

  // Alice creates room
  alice.create_room("Alice's Room", "academy_empty_goal_close", 2);
  alice.poll();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  alice.poll();

  // Get room list to find room ID
  alice.request_room_list();
  alice.poll();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  alice.poll();

  auto rooms = alice.get_rooms();
  ASSERT_GE(rooms.size(), 1u);
  uint32_t room_id = rooms[0].room_id;

  // Bob joins room
  bob.join_room(room_id);
  bob.poll();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  bob.poll();

  // Check room info
  const auto& room_info = bob.get_current_room();
  EXPECT_EQ(room_info.room_id, room_id);
  EXPECT_EQ(room_info.player_count, 2);

  bob.disconnect();
  alice.disconnect();
  server.stop();
  io.stop();
  io_thread.join();
}

TEST(LobbyE2ETest, ChatBetweenPlayers) {
  const unsigned short port = 19902;
  boost::asio::io_context io;

  TestLobbyServer server(io, port);
  std::thread io_thread([&io]() { io.run(); });

  std::this_thread::sleep_for(std::chrono::milliseconds(50));

  LobbyClient alice(io);
  LobbyClient bob(io);

  alice.connect("127.0.0.1", port);
  alice.set_name("Alice");
  bob.connect("127.0.0.1", port);
  bob.set_name("Bob");

  // Create and join room
  alice.create_room("Chat Room", "academy_empty_goal_close", 2);
  alice.poll();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  alice.poll();

  alice.request_room_list();
  alice.poll();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  alice.poll();

  auto rooms = alice.get_rooms();
  ASSERT_GE(rooms.size(), 1u);
  uint32_t room_id = rooms[0].room_id;

  bob.join_room(room_id);
  bob.poll();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  bob.poll();

  // Alice sends chat
  alice.send_chat(room_id, "Hello Bob!");
  bob.poll();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  bob.poll();

  auto chats = bob.get_chats();
  EXPECT_GE(chats.size(), 1u);
  if (!chats.empty()) {
    EXPECT_EQ(chats[0].first, "Alice");
    EXPECT_EQ(chats[0].second, "Hello Bob!");
  }

  bob.disconnect();
  alice.disconnect();
  server.stop();
  io.stop();
  io_thread.join();
}

TEST(LobbyE2ETest, ReadyUp) {
  const unsigned short port = 19903;
  boost::asio::io_context io;

  TestLobbyServer server(io, port);
  std::thread io_thread([&io]() { io.run(); });

  std::this_thread::sleep_for(std::chrono::milliseconds(50));

  LobbyClient alice(io);
  LobbyClient bob(io);

  alice.connect("127.0.0.1", port);
  alice.set_name("Alice");
  bob.connect("127.0.0.1", port);
  bob.set_name("Bob");

  alice.create_room("Ready Room", "academy_empty_goal_close", 2);
  alice.poll();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  alice.poll();

  alice.request_room_list();
  alice.poll();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  alice.poll();

  auto rooms = alice.get_rooms();
  ASSERT_GE(rooms.size(), 1u);
  uint32_t room_id = rooms[0].room_id;

  bob.join_room(room_id);
  bob.poll();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  bob.poll();

  // Bob ready up
  bob.set_ready(room_id);
  bob.poll();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  bob.poll();

  // Both poll for updated room info
  alice.poll();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  alice.poll();
  bob.poll();
  std::this_thread::sleep_for(std::chrono::milliseconds(50));
  bob.poll();

  // Verify — Bob received RoomInfo when joining (player_count=2)
  const auto& room_info = bob.get_current_room();
  EXPECT_EQ(room_info.player_count, 2);

  bob.disconnect();
  alice.disconnect();
  server.stop();
  io.stop();
  io_thread.join();
}

}  // namespace
}  // namespace frame_sync
