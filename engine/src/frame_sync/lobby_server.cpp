// Copyright 2026 Google LLC & Contributors
// Lobby Server: manages rooms, players, and chat for multi-room system (ms-18.3).
//
// Standalone TCP server. Players connect here first, create/join rooms,
// then get directed to a game server when a match starts.

#include "frame_sync/lobby_protocol.hpp"
#include "frame_sync/room_manager.hpp"

// GCC 15 compat: <utility> before Boost.Asio
#include <utility>
#include <boost/asio.hpp>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <deque>
#include <flat_set>
#include <iostream>
#include <memory>
#include <mutex>
#include <print>
#include <string>
#include <thread>
#include <vector>

namespace asio = boost::asio;
using tcp = asio::ip::tcp;

struct ClientSession {
  tcp::socket socket;
  std::string player_name;
  uint32_t current_room = 0;  // room the player is in (0 = none)
  std::vector<uint8_t> recv_buf;
  bool disconnected = false;

  explicit ClientSession(asio::io_context& io) : socket(io) {}
};

class LobbyServer {
 public:
  LobbyServer(asio::io_context& io, unsigned short port)
      : io_(io), acceptor_(io, tcp::endpoint(tcp::v4(), port)) {
    do_accept();
  }

  void stop() { running_ = false; }

 private:
  void do_accept() {
    acceptor_.async_accept([this](boost::system::error_code ec, tcp::socket socket) {
      if (ec) return;

      auto client = std::make_shared<ClientSession>(io_);
      client->socket = std::move(socket);

      std::println("New lobby client connected");

      {
        std::lock_guard<std::mutex> lock(mu_);
        clients_.push_back(client);
      }

      do_read(client);
      do_accept();
    });
  }

  void do_read(std::shared_ptr<ClientSession> client) {
    auto buf = std::make_shared<std::vector<uint8_t>>(4096);
    client->socket.async_read_some(
        asio::buffer(*buf),
        [this, client, buf](boost::system::error_code ec, std::size_t length) {
          if (ec) {
            handle_disconnect(client);
            return;
          }
          std::lock_guard<std::mutex> lock(mu_);
          client->recv_buf.insert(client->recv_buf.end(),
                                  buf->begin(), buf->begin() + length);
          while (process_one_message(client)) {}
          do_read(client);
        });
  }

  bool process_one_message(std::shared_ptr<ClientSession> client) {
    if (client->recv_buf.empty()) return false;
    uint8_t type = client->recv_buf[0];

    // CreateRoom: type(1) + RoomConfig
    if (type == std::to_underlying(LobbyMessageType::CreateRoom)) {
      if (client->recv_buf.size() < 1 + ROOM_CONFIG_SIZE) return false;

      RoomConfig config;
      size_t used = UnpackRoomConfig(client->recv_buf.data() + 1,
                                     client->recv_buf.size() - 1, &config);
      if (used == 0) return false;

      // Player must have a name set first
      if (client->player_name.empty()) {
        send_error(client, 1, "Name not set");
        client->recv_buf.erase(client->recv_buf.begin(),
                               client->recv_buf.begin() + 1 + used);
        return true;
      }

      // Leave current room if any
      if (client->current_room != 0) {
        room_mgr_.LeaveRoom(client->current_room, client->player_name);
        client->current_room = 0;
      }

      uint32_t room_id = room_mgr_.CreateRoom(config, client->player_name);
      client->current_room = room_id;

      // Send RoomCreated
      uint8_t resp[8];
      resp[0] = std::to_underlying(LobbyMessageType::RoomCreated);
      PackUint32(resp + 1, room_id);
      send_to_client(client, resp, 5);

      std::println("Room created: {} by {}", room_id, client->player_name);

      client->recv_buf.erase(client->recv_buf.begin(),
                             client->recv_buf.begin() + 1 + used);
      return true;
    }

    // JoinRoom: type(1) + room_id(4)
    if (type == std::to_underlying(LobbyMessageType::JoinRoom)) {
      if (client->recv_buf.size() < 1 + ROOM_ID_BYTES) return false;

      uint32_t room_id;
      UnpackUint32(client->recv_buf.data() + 1, ROOM_ID_BYTES, &room_id);

      if (client->player_name.empty()) {
        send_error(client, 1, "Name not set");
        client->recv_buf.erase(client->recv_buf.begin(),
                               client->recv_buf.begin() + 1 + ROOM_ID_BYTES);
        return true;
      }

      if (client->current_room != 0) {
        room_mgr_.LeaveRoom(client->current_room, client->player_name);
        client->current_room = 0;
      }

      bool ok = room_mgr_.JoinRoom(room_id, client->player_name);
      if (ok) {
        client->current_room = room_id;

        // Send RoomInfo
        send_room_info(client, room_id);

        // Notify others
        broadcast_player_joined(room_id, client->player_name);

        std::println("{} joined room {}", client->player_name, room_id);
      } else {
        send_error(client, 2, "Cannot join room");
      }

      client->recv_buf.erase(client->recv_buf.begin(),
                             client->recv_buf.begin() + 1 + ROOM_ID_BYTES);
      return true;
    }

    // LeaveRoom: type(1) + room_id(4)
    if (type == std::to_underlying(LobbyMessageType::LeaveRoom)) {
      if (client->recv_buf.size() < 1 + ROOM_ID_BYTES) return false;

      uint32_t room_id;
      UnpackUint32(client->recv_buf.data() + 1, ROOM_ID_BYTES, &room_id);

      if (client->current_room == room_id) {
        broadcast_player_left(room_id, client->player_name);
        room_mgr_.LeaveRoom(room_id, client->player_name);
        client->current_room = 0;
        std::println("{} left room {}", client->player_name, room_id);
      }

      client->recv_buf.erase(client->recv_buf.begin(),
                             client->recv_buf.begin() + 1 + ROOM_ID_BYTES);
      return true;
    }

    // RoomList: type(1) — no payload
    if (type == std::to_underlying(LobbyMessageType::RoomList)) {
      auto rooms = room_mgr_.ListRooms();
      send_room_list(client, rooms);
      client->recv_buf.erase(client->recv_buf.begin());
      return true;
    }

    // Chat: type(1) + room_id(4) + msg_len(2) + msg
    if (type == std::to_underlying(LobbyMessageType::Chat)) {
      if (client->recv_buf.size() < 7) return false;  // type + room_id + msg_len

      uint32_t room_id;
      UnpackUint32(client->recv_buf.data() + 1, ROOM_ID_BYTES, &room_id);

      uint16_t msg_len;
      UnpackUint16(client->recv_buf.data() + 5, sizeof(uint16_t), &msg_len);

      size_t need = 1 + ROOM_ID_BYTES + sizeof(uint16_t) + msg_len;
      if (client->recv_buf.size() < need) return false;

      std::string msg(client->recv_buf.begin() + 7,
                      client->recv_buf.begin() + 7 + msg_len);

      broadcast_chat(room_id, client->player_name, msg);

      client->recv_buf.erase(client->recv_buf.begin(),
                             client->recv_buf.begin() + need);
      return true;
    }

    // Ready: type(1) + room_id(4)
    if (type == std::to_underlying(LobbyMessageType::Ready)) {
      if (client->recv_buf.size() < 1 + ROOM_ID_BYTES) return false;

      uint32_t room_id;
      UnpackUint32(client->recv_buf.data() + 1, ROOM_ID_BYTES, &room_id);

      if (client->current_room == room_id) {
        room_mgr_.SetReady(room_id, client->player_name, true);
        send_room_info(client, room_id);
      }

      client->recv_buf.erase(client->recv_buf.begin(),
                             client->recv_buf.begin() + 1 + ROOM_ID_BYTES);
      return true;
    }

    // Unready: type(1) + room_id(4)
    if (type == std::to_underlying(LobbyMessageType::Unready)) {
      if (client->recv_buf.size() < 1 + ROOM_ID_BYTES) return false;

      uint32_t room_id;
      UnpackUint32(client->recv_buf.data() + 1, ROOM_ID_BYTES, &room_id);

      if (client->current_room == room_id) {
        room_mgr_.SetReady(room_id, client->player_name, false);
        send_room_info(client, room_id);
      }

      client->recv_buf.erase(client->recv_buf.begin(),
                             client->recv_buf.begin() + 1 + ROOM_ID_BYTES);
      return true;
    }

    // StartGame: type(1) + room_id(4) + game_address(varies) + game_port(2)
    if (type == std::to_underlying(LobbyMessageType::StartGame)) {
      if (client->recv_buf.size() < 1 + ROOM_ID_BYTES) return false;

      uint32_t room_id;
      UnpackUint32(client->recv_buf.data() + 1, ROOM_ID_BYTES, &room_id);

      // For now, the host provides the game server address
      // In a full implementation, the lobby would spawn a game server
      // Simplified: expect "host:port" string after room_id
      if (client->recv_buf.size() < 1 + ROOM_ID_BYTES + 3) {
        send_error(client, 3, "Need game address");
        client->recv_buf.erase(client->recv_buf.begin(),
                               client->recv_buf.begin() + 1 + ROOM_ID_BYTES);
        return true;
      }

      // Parse address from remaining buffer
      size_t offset = 1 + ROOM_ID_BYTES;
      std::string addr_str(client->recv_buf.begin() + offset,
                           client->recv_buf.end());

      // Find colon separator
      auto colon_pos = addr_str.find(':');
      std::string game_address;
      uint16_t game_port = 0;
      if (colon_pos != std::string::npos) {
        game_address = addr_str.substr(0, colon_pos);
        game_port = static_cast<uint16_t>(std::stoi(addr_str.substr(colon_pos + 1)));
      } else {
        game_address = addr_str;
        game_port = 12345;
      }

      bool ok = room_mgr_.StartGame(room_id, client->player_name,
                                     game_address, game_port);
      if (ok) {
        broadcast_game_started(room_id, game_address, game_port);
        std::println("Game started in room {}: {}:{}", room_id, game_address, game_port);
      } else {
        send_error(client, 4, "Cannot start game");
      }

      // Consume all remaining buffer for simplicity
      client->recv_buf.clear();
      return false;
    }

    // NameSet: type(1) + name_len(2) + name — custom extension for lobby
    // Using MessageType 0xFF as a private lobby message
    if (type == 0xFF) {
      if (client->recv_buf.size() < 3) return false;
      uint16_t name_len;
      UnpackUint16(client->recv_buf.data() + 1, sizeof(uint16_t), &name_len);
      if (client->recv_buf.size() < 3 + name_len) return false;

      client->player_name.assign(
          client->recv_buf.begin() + 3,
          client->recv_buf.begin() + 3 + name_len);

      std::println("Client identified as: {}", client->player_name);

      client->recv_buf.erase(client->recv_buf.begin(),
                             client->recv_buf.begin() + 3 + name_len);
      return true;
    }

    // Unknown: skip 1 byte
    client->recv_buf.erase(client->recv_buf.begin());
    return true;
  }

  void handle_disconnect(std::shared_ptr<ClientSession> client) {
    std::lock_guard<std::mutex> lock(mu_);
    client->disconnected = true;

    if (client->current_room != 0) {
      broadcast_player_left(client->current_room, client->player_name);
      room_mgr_.LeaveRoom(client->current_room, client->player_name);
      std::println("{} disconnected (left room {})", client->player_name, client->current_room);
    } else {
      std::println("{} disconnected", client->player_name);
    }
  }

  // ===== Send helpers =====

  void send_to_client(std::shared_ptr<ClientSession> client,
                      const uint8_t* data, size_t len) {
    boost::system::error_code ec;
    asio::write(client->socket, asio::buffer(data, len), ec);
    if (ec) client->disconnected = true;
  }

  void send_error(std::shared_ptr<ClientSession> client,
                  uint16_t code, const std::string& msg) {
    std::vector<uint8_t> buf(1 + sizeof(uint16_t) + sizeof(uint16_t) + msg.size());
    buf[0] = std::to_underlying(LobbyMessageType::Error);
    PackUint16(buf.data() + 1, code);
    PackUint16(buf.data() + 3, static_cast<uint16_t>(msg.size()));
    std::memcpy(buf.data() + 5, msg.data(), msg.size());
    send_to_client(client, buf.data(), buf.size());
  }

  void send_room_info(std::shared_ptr<ClientSession> client, uint32_t room_id) {
    const RoomMetadata* meta = room_mgr_.GetRoomMetadata(room_id);
    if (!meta) return;

    std::vector<uint8_t> buf(1 + ROOM_METADATA_SIZE);
    buf[0] = std::to_underlying(LobbyMessageType::RoomInfo);
    PackRoomMetadata(*meta, buf.data() + 1, ROOM_METADATA_SIZE);
    send_to_client(client, buf.data(), buf.size());
  }

  void send_room_list(std::shared_ptr<ClientSession> client,
                      const std::vector<RoomMetadata>& rooms) {
    std::vector<uint8_t> buf(1 + sizeof(uint16_t) + rooms.size() * ROOM_METADATA_SIZE);
    buf[0] = std::to_underlying(LobbyMessageType::RoomListResponse);
    PackUint16(buf.data() + 1, static_cast<uint16_t>(rooms.size()));
    size_t offset = 3;
    for (const auto& room : rooms) {
      PackRoomMetadata(room, buf.data() + offset, ROOM_METADATA_SIZE);
      offset += ROOM_METADATA_SIZE;
    }
    send_to_client(client, buf.data(), offset);
  }

  // ===== Broadcast helpers =====

  void broadcast_to_room(uint32_t room_id, const uint8_t* data, size_t len,
                         const std::string& exclude = "") {
    for (auto& client : clients_) {
      if (client->disconnected) continue;
      if (client->current_room != room_id) continue;
      if (!exclude.empty() && client->player_name == exclude) continue;
      send_to_client(client, data, len);
    }
  }

  void broadcast_player_joined(uint32_t room_id, const std::string& name) {
    std::vector<uint8_t> buf(1 + ROOM_ID_BYTES + sizeof(uint16_t) + name.size());
    buf[0] = std::to_underlying(LobbyMessageType::PlayerJoined);
    PackUint32(buf.data() + 1, room_id);
    PackUint16(buf.data() + 5, static_cast<uint16_t>(name.size()));
    std::memcpy(buf.data() + 7, name.data(), name.size());
    broadcast_to_room(room_id, buf.data(), buf.size());
  }

  void broadcast_player_left(uint32_t room_id, const std::string& name) {
    std::vector<uint8_t> buf(1 + ROOM_ID_BYTES + sizeof(uint16_t) + name.size());
    buf[0] = std::to_underlying(LobbyMessageType::PlayerLeft);
    PackUint32(buf.data() + 1, room_id);
    PackUint16(buf.data() + 5, static_cast<uint16_t>(name.size()));
    std::memcpy(buf.data() + 7, name.data(), name.size());
    broadcast_to_room(room_id, buf.data(), buf.size());
  }

  void broadcast_chat(uint32_t room_id, const std::string& sender,
                      const std::string& msg) {
    std::vector<uint8_t> buf(1 + ROOM_ID_BYTES + sizeof(uint16_t) + sender.size()
                             + sizeof(uint16_t) + msg.size());
    buf[0] = std::to_underlying(LobbyMessageType::ChatMessage);
    size_t offset = 1;
    offset += PackUint32(buf.data() + offset, room_id);
    offset += PackString(buf.data() + offset, buf.size() - offset, sender);
    offset += PackString(buf.data() + offset, buf.size() - offset, msg);
    broadcast_to_room(room_id, buf.data(), offset);
  }

  void broadcast_game_started(uint32_t room_id, const std::string& addr,
                              uint16_t port) {
    std::vector<uint8_t> buf(1 + ROOM_ID_BYTES + 64 + sizeof(uint16_t));
    buf[0] = std::to_underlying(LobbyMessageType::GameStarted);
    size_t offset = 1;
    offset += PackUint32(buf.data() + offset, room_id);
    // Pack address as fixed 32 bytes + port
    std::strncpy(reinterpret_cast<char*>(buf.data() + offset), addr.c_str(), 32);
    offset += 32;
    PackUint16(buf.data() + offset, port);
    offset += sizeof(uint16_t);
    broadcast_to_room(room_id, buf.data(), offset);
  }

  asio::io_context& io_;
  tcp::acceptor acceptor_;
  mutable std::mutex mu_;
  std::vector<std::shared_ptr<ClientSession>> clients_;
  frame_sync::RoomManager room_mgr_;
  std::atomic<bool> running_{true};
};

int main(int argc, char* argv[]) {
  unsigned short port = 12346;

  if (argc >= 2) port = static_cast<unsigned short>(std::stoi(argv[1]));

  std::println("Starting lobby server on port {}", port);

  asio::io_context io;
  LobbyServer server(io, port);

  std::thread io_thread([&io]() { io.run(); });

  // Run until interrupted
  std::println("Lobby server running. Press Ctrl+C to stop.");
  while (true) {
    std::this_thread::sleep_for(std::chrono::seconds(1));
  }

  server.stop();
  io.stop();
  if (io_thread.joinable()) io_thread.join();

  return 0;
}
