#ifndef GFOOTBALL_FRAME_SYNC_LOBBY_SERVER_HPP
#define GFOOTBALL_FRAME_SYNC_LOBBY_SERVER_HPP
// Copyright 2026 Google LLC & Contributors
// Lobby Server: manages rooms, players, and chat for multi-room system (ms-18.3).
//
// Standalone TCP server. Players connect here first, create/join rooms,
// then get directed to a game server when a match starts.

#include "frame_sync/lobby_protocol.hpp"
#include "frame_sync/room_manager.hpp"
#include "frame_sync/bounded_tcp_writer.hpp"

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
#include <charconv>
#include <atomic>
#include <vector>


namespace frame_sync {
namespace asio = boost::asio;
using tcp = asio::ip::tcp;

// 2026-09-09: bounded transport, connection accounting and asynchronous lifetime.
// struct LobbySession {
//   tcp::socket socket;
//   std::string player_name;
//   uint32_t current_room = 0;  // room the player is in (0 = none)
//   std::vector<uint8_t> recv_buf;
//   bool disconnected = false;
//   bool removed = false;
//   std::deque<std::vector<uint8_t>> outgoing;
//   size_t queued_bytes = 0;
// 
//   explicit LobbySession(asio::io_context& io) : socket(io) {}
// };
struct LobbyLimits {
  explicit LobbyLimits(size_t connections = 128, size_t messages = 256,
                       size_t bytes = 128 * 1024,
                       std::chrono::milliseconds identify = std::chrono::seconds(30))
      : connection_limit(connections), send(messages, bytes), identify_timeout(identify) {
    if (connections == 0 || connections > 1024 || identify.count() < 1 ||
        identify > std::chrono::minutes(5))
      throw std::invalid_argument("Invalid lobby connection/identification limit");
  }
  ~LobbyLimits() = default;
  LobbyLimits(const LobbyLimits&) = default;
  LobbyLimits& operator=(const LobbyLimits&) = default;
  LobbyLimits(LobbyLimits&&) = default;
  LobbyLimits& operator=(LobbyLimits&&) = default;
  size_t connection_limit;
  StreamBudget send;
  std::chrono::milliseconds identify_timeout;
};
struct LobbyStats {
  size_t connections = 0;
  size_t identified_connections = 0;
  size_t receive_capacity = 0;
  size_t queued_send_bytes = 0;
  size_t queued_send_messages = 0;
  size_t rejected_connections = 0;
  size_t overload_disconnects = 0;
  size_t invalid_messages = 0;
};
struct LobbySession {
  std::shared_ptr<tcp::socket> socket;
  BoundedTCPWriter writer;
  std::string player_name;
  uint32_t current_room = 0;
  std::vector<uint8_t> recv_buf;
  bool disconnected = false;
  bool removed = false;
  bool read_pending = false;
  const std::chrono::steady_clock::time_point connected_at = std::chrono::steady_clock::now();
  LobbySession(asio::io_context& io, StreamBudget budget)
      : socket(std::make_shared<tcp::socket>(io)), writer(socket, budget) {}
  ~LobbySession() = default;
  LobbySession(const LobbySession&) = delete;
  LobbySession& operator=(const LobbySession&) = delete;
  LobbySession(LobbySession&&) = delete;
  LobbySession& operator=(LobbySession&&) = delete;
};

// 2026-09-09: bounded transport, connection accounting and asynchronous lifetime.
// class LobbyServer {
//  public:
//   LobbyServer(asio::io_context& io, unsigned short port)
//       : io_(io), acceptor_(io, tcp::endpoint(tcp::v4(), port)) {
//     do_accept();
//   }
class LobbyServer {
 private:
  struct Impl : std::enable_shared_from_this<Impl> {
 public:
  Impl(asio::io_context& io, unsigned short port, const LobbyLimits& limits)
      : io_(io), acceptor_(io, tcp::endpoint(tcp::v4(), port)),
        limits_(limits.connection_limit, limits.send.message_limit, limits.send.byte_limit,
                limits.identify_timeout), maintenance_(io) {}
  void start() { do_accept(); do_maintenance(); }

  // 2026-09-09: close sockets on the IO executor so shutdown cancels pending reads.
  // void stop() { running_ = false; }// 2026-09-09: bounded transport, connection accounting and asynchronous lifetime.
// 
//   void stop() {
//     asio::post(io_, [this] {
//       running_ = false;
//       boost::system::error_code ec;
//       acceptor_.close(ec);
//       for (auto& client : clients_) client->socket.close(ec);
//     });
//   }
//   unsigned short port() const { return acceptor_.local_endpoint().port(); }

  void stop() {
    if (!running_.exchange(false)) return;
    // Mark every writer closed synchronously while the IO context still exists.
    // Its later destruction must not post fresh work during IO-context teardown.
    {
      std::lock_guard lock(mu_);
      for (auto& client : clients_) MarkDisconnectedLocked(client);
    }
    asio::post(io_, [self = shared_from_this(), this] {
      std::lock_guard lock(mu_);
      boost::system::error_code ec;
      acceptor_.close(ec);
      maintenance_.cancel();
      CleanupLocked();
    });
  }
  unsigned short port() const { return acceptor_.local_endpoint().port(); }
  LobbyStats stats() const {
    std::lock_guard lock(mu_);
    LobbyStats result;
    result.connections = clients_.size();
    result.rejected_connections = rejected_connections_;
    result.overload_disconnects = overload_disconnects_;
    result.invalid_messages = invalid_messages_;
    for (const auto& client : clients_) {
      result.identified_connections += !client->player_name.empty() && !client->disconnected;
      result.receive_capacity += RetainedBytes(client->recv_buf);
      result.queued_send_bytes += client->writer.queued_bytes();
      result.queued_send_messages += client->writer.queued_messages();
    }
    return result;
  }

 private:// 2026-09-09: bounded transport, connection accounting and asynchronous lifetime.
// 
//   void do_accept() {
//     acceptor_.async_accept([this](boost::system::error_code ec, tcp::socket socket) {
//       if (ec) return;
// 
//       auto client = std::make_shared<LobbySession>(io_);
//       client->socket = std::move(socket);
// 
//       std::println("New lobby client connected");
// 
//       {
//         std::lock_guard<std::mutex> lock(mu_);
//         clients_.push_back(client);
//       }
// 
//       do_read(client);
//       do_accept();
//     });
//   }
// 
//   void do_read(std::shared_ptr<LobbySession> client) {
//     if (client->disconnected || !running_) return;
//     auto buf = std::make_shared<std::vector<uint8_t>>(4096);
//     client->socket.async_read_some(
//         asio::buffer(*buf),
//         [this, client, buf](boost::system::error_code ec, std::size_t length) {
//           if (ec) {
//             handle_disconnect(client);
//             return;
//           }
//           std::lock_guard<std::mutex> lock(mu_);
//           client->recv_buf.insert(client->recv_buf.end(),
//                                   buf->begin(), buf->begin() + length);
//           while (process_one_message(client)) {}
//           do_read(client);
//         });
//   }

  void do_accept() {
    acceptor_.async_accept([self = shared_from_this(), this](boost::system::error_code ec, tcp::socket socket) {
      std::lock_guard lock(mu_);
      if (ec || !running_) return;
      CleanupLocked();
      if (clients_.size() >= limits_.connection_limit) {
        ++rejected_connections_;
        socket.close(ec);
        do_accept();
        return;
      }
      auto client = std::make_shared<LobbySession>(io_, limits_.send);
      *client->socket = std::move(socket);
      clients_.push_back(client);
      do_read(client);
      do_accept();
    });
  }
  void do_maintenance() {
    maintenance_.expires_after(std::chrono::milliseconds(50));
    maintenance_.async_wait([self = shared_from_this(), this](boost::system::error_code ec) {
      std::lock_guard lock(mu_);
      if (ec || !running_) return;
      const auto now = std::chrono::steady_clock::now();
      for (auto& client : clients_)
        if (!client->disconnected && client->player_name.empty() &&
            now - client->connected_at >= limits_.identify_timeout)
          MarkDisconnectedLocked(client);
      CleanupLocked();
      do_maintenance();
    });
  }
  // mu_ is held by all callers. Payload ownership survives cancellation.
  void do_read(std::shared_ptr<LobbySession> client) {
    if (client->disconnected || !running_) return;
    auto buf = std::make_shared<std::array<uint8_t, 4096>>();
    client->read_pending = true;
    if (!client->writer.AsyncReadSome(asio::buffer(*buf),
        [self = shared_from_this(), this, client, buf](boost::system::error_code ec, size_t length) {
          std::lock_guard lock(mu_);
          client->read_pending = false;
          if (ec || !running_ || client->disconnected) {
            MarkDisconnectedLocked(client);
            CleanupLocked();
            return;
          }
          if (!AppendBoundedBytes(client->recv_buf, buf->data(), length, kReceiveBytes)) {
            MarkDisconnectedLocked(client, true);
            CleanupLocked();
            return;
          }
          while (!client->disconnected && process_one_message(client)) {}
          CleanupLocked();
          do_read(client);
        })) {
      client->read_pending = false;
      MarkDisconnectedLocked(client);
    }
  }

  bool process_one_message(std::shared_ptr<LobbySession> client) {
    if (client->recv_buf.empty()) return false;
    uint8_t type = client->recv_buf[0];

    // CreateRoom: type(1) + RoomConfig
    if (type == std::to_underlying(LobbyMessageType::CreateRoom)) {
      if (client->recv_buf.size() < 1 + ROOM_CONFIG_SIZE) return false;

      RoomConfig config;
      size_t used = UnpackRoomConfig(client->recv_buf.data() + 1,
                                     client->recv_buf.size() - 1, &config);
// 2026-09-09: bounded transport, connection accounting and asynchronous lifetime.
//       if (used == 0) return false;
      if (used == 0) return RejectMessageLocked(client);

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

      if (room_id == 0) {
        send_error(client, 5, "Invalid room configuration or room limit");
        client->recv_buf.erase(client->recv_buf.begin(), client->recv_buf.begin() + 1 + used);
        return true;
      }

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

// 2026-09-09: bounded transport, connection accounting and asynchronous lifetime.
//       size_t need = 1 + ROOM_ID_BYTES + sizeof(uint16_t) + msg_len;
//       if (client->recv_buf.size() < need) return false;
      if (msg_len > 4096) return RejectMessageLocked(client);
      size_t need = 1 + ROOM_ID_BYTES + sizeof(uint16_t) + msg_len;
      if (client->recv_buf.size() < need) return false;

      std::string msg(client->recv_buf.begin() + 7,
                      client->recv_buf.begin() + 7 + msg_len);

      // 2026-09-09: a session may only send messages to its own room.
      // broadcast_chat(room_id, client->player_name, msg);
      if (!client->player_name.empty() && client->current_room == room_id)
        broadcast_chat(room_id, client->player_name, msg);
      else send_error(client, 5, "Not a room member");

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

    // 2026-09-09: length-prefixed StartGame survives TCP fragmentation/coalescing.
    //     // StartGame: type(1) + room_id(4) + game_address(varies) + game_port(2)
    //     if (type == std::to_underlying(LobbyMessageType::StartGame)) {
    //       if (client->recv_buf.size() < 1 + ROOM_ID_BYTES) return false;
    // 
    //       uint32_t room_id;
    //       UnpackUint32(client->recv_buf.data() + 1, ROOM_ID_BYTES, &room_id);
    // 
    //       // For now, the host provides the game server address
    //       // In a full implementation, the lobby would spawn a game server
    //       // Simplified: expect "host:port" string after room_id
    //       if (client->recv_buf.size() < 1 + ROOM_ID_BYTES + 3) {
    //         send_error(client, 3, "Need game address");
    //         client->recv_buf.erase(client->recv_buf.begin(),
    //                                client->recv_buf.begin() + 1 + ROOM_ID_BYTES);
    //         return true;
    //       }
    // 
    //       // Parse address from remaining buffer
    //       size_t offset = 1 + ROOM_ID_BYTES;
    //       std::string addr_str(client->recv_buf.begin() + offset,
    //                            client->recv_buf.end());
    // 
    //       // Find colon separator
    //       auto colon_pos = addr_str.find(':');
    //       std::string game_address;
    //       uint16_t game_port = 0;
    //       if (colon_pos != std::string::npos) {
    //         game_address = addr_str.substr(0, colon_pos);
    //         game_port = static_cast<uint16_t>(std::stoi(addr_str.substr(colon_pos + 1)));
    //       } else {
    //         game_address = addr_str;
    //         game_port = 12345;
    //       }
    // 
    //       bool ok = room_mgr_.StartGame(room_id, client->player_name,
    //                                      game_address, game_port);
    //       if (ok) {
    //         broadcast_game_started(room_id, game_address, game_port);
    //         std::println("Game started in room {}: {}:{}", room_id, game_address, game_port);
    //       } else {
    //         send_error(client, 4, "Cannot start game");
    //       }
    // 
    //       // Consume all remaining buffer for simplicity
    //       client->recv_buf.clear();
    //       return false;
    //     }
    // 
    if (type == std::to_underlying(LobbyMessageType::StartGame)) {
      if (client->recv_buf.size() < 7) return false;
      uint32_t room_id;
      uint16_t length;
      UnpackUint32(client->recv_buf.data() + 1, 4, &room_id);
      UnpackUint16(client->recv_buf.data() + 5, 2, &length);
// 2026-09-09: bounded transport, connection accounting and asynchronous lifetime.
//       if (length > 96) { client->recv_buf.clear(); send_error(client, 3, "Address too long"); return false; }
      if (length > 96) return RejectMessageLocked(client);
      if (client->recv_buf.size() < 7u + length) return false;
      std::string address(reinterpret_cast<const char*>(client->recv_buf.data() + 7), length);
      const auto colon = address.rfind(':');
      unsigned port = 0;
      bool valid = colon != std::string::npos && colon > 0;
      if (valid) {
        const char* first = address.data() + colon + 1;
        const char* last = address.data() + address.size();
        const auto parsed = std::from_chars(first, last, port);
        valid = parsed.ec == std::errc{} && parsed.ptr == last && port > 0 && port <= 65535;
      }
      if (valid && client->current_room == room_id &&
          room_mgr_.StartGame(room_id, client->player_name, address.substr(0, colon), static_cast<uint16_t>(port))) {
        broadcast_game_started(room_id, address.substr(0, colon), static_cast<uint16_t>(port));
      } else {
        send_error(client, 4, "Cannot start game: invalid address, host or ready state");
      }
      client->recv_buf.erase(client->recv_buf.begin(), client->recv_buf.begin() + 7 + length);
      return true;
    }

    // NameSet: type(1) + name_len(2) + name — custom extension for lobby
    // Using MessageType 0xFF as a private lobby message
    if (type == 0xFF) {
      if (client->recv_buf.size() < 3) return false;
      uint16_t name_len;
// 2026-09-09: bounded transport, connection accounting and asynchronous lifetime.
//       UnpackUint16(client->recv_buf.data() + 1, sizeof(uint16_t), &name_len);
//       if (client->recv_buf.size() < 3 + name_len) return false;
      UnpackUint16(client->recv_buf.data() + 1, sizeof(uint16_t), &name_len);
      if (name_len > 32) return RejectMessageLocked(client);
      if (client->recv_buf.size() < 3 + name_len) return false;

      const std::string proposed(client->recv_buf.begin() + 3, client->recv_buf.begin() + 3 + name_len);
      const bool duplicate = std::ranges::any_of(clients_, [&](const auto& other) {
        return other != client && !other->disconnected && other->player_name == proposed;
      });
      if (name_len == 0 || name_len > 32 || duplicate || client->current_room != 0) {
        send_error(client, 6, "Invalid or duplicate name; leave room before renaming");
        client->recv_buf.erase(client->recv_buf.begin(), client->recv_buf.begin() + 3 + name_len);
        return true;
      }
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
// 2026-09-09: bounded transport, connection accounting and asynchronous lifetime.
// 
//   void handle_disconnect(std::shared_ptr<LobbySession> client) {
//     std::lock_guard<std::mutex> lock(mu_);
//     if (client->removed) return;
//     client->removed = true;
//     client->disconnected = true;
// 
//     if (client->current_room != 0) {
//       broadcast_player_left(client->current_room, client->player_name);
//       room_mgr_.LeaveRoom(client->current_room, client->player_name);
//       std::println("{} disconnected (left room {})", client->player_name, client->current_room);
//     } else {
//       std::println("{} disconnected", client->player_name);
//     }
//     std::erase(clients_, client);
//   }
// 
//   // ===== Send helpers =====
// 
//   void send_to_client(std::shared_ptr<LobbySession> client,
//                       const uint8_t* data, size_t len) {
//     // 2026-09-09: queued async writes prevent one slow client from stalling all rooms.
//     // asio::write(client->socket, asio::buffer(data, len), ec);
//     if (client->disconnected) return;
//     if (len > 128 * 1024 - client->queued_bytes) {
//       client->disconnected = true;
//       boost::system::error_code ec;
//       client->socket.close(ec);
//       return;
//     }
//     const bool idle = client->outgoing.empty();
//     client->outgoing.emplace_back(data, data + len);
//     client->queued_bytes += len;
//     if (idle) do_write(client);
//   }
// 
//   void do_write(std::shared_ptr<LobbySession> client) {
//     asio::async_write(client->socket, asio::buffer(client->outgoing.front()),
//         [this, client](boost::system::error_code ec, size_t) {
//           if (ec) { handle_disconnect(client); return; }
//           std::lock_guard<std::mutex> lock(mu_);
//           client->queued_bytes -= client->outgoing.front().size();
//           client->outgoing.pop_front();
//           if (!client->outgoing.empty()) do_write(client);
//         });
//   }

  // Never clear recv_buf while its parser still has an erase pending, and never
  // erase clients_ while broadcasting. Cleanup runs after that operation ends.
  void MarkDisconnectedLocked(const std::shared_ptr<LobbySession>& client, bool overload = false) {
    if (client->disconnected) return;
    client->disconnected = true;
    if (overload) ++overload_disconnects_;
    client->writer.Close();
  }
  bool RejectMessageLocked(const std::shared_ptr<LobbySession>& client) {
    ++invalid_messages_;
    MarkDisconnectedLocked(client);
    return false;
  }
  void CleanupLocked() {
    for (auto& client : clients_) {
      if (!client->disconnected || client->removed) continue;
      client->removed = true;
      std::vector<uint8_t>().swap(client->recv_buf);
      if (client->current_room) {
        const auto room = std::exchange(client->current_room, 0);
        room_mgr_.LeaveRoom(room, client->player_name);
        broadcast_player_left(room, client->player_name);
      }
    }
    // Closing writes remain part of the connection budget until their buffers
    // and read completion have been released.
    std::erase_if(clients_, [](const auto& client) {
      return client->removed && !client->read_pending && client->writer.queued_messages() == 0;
    });
  }
  void send_to_client(std::shared_ptr<LobbySession> client, const uint8_t* data, size_t len) {
    if (client->disconnected) return;
    if (!client->writer.TrySend(data, len)) MarkDisconnectedLocked(client, true);
  }

  void send_error(std::shared_ptr<LobbySession> client,
                  uint16_t code, const std::string& msg) {
    std::vector<uint8_t> buf(1 + sizeof(uint16_t) + sizeof(uint16_t) + msg.size());
    buf[0] = std::to_underlying(LobbyMessageType::Error);
    PackUint16(buf.data() + 1, code);
    PackUint16(buf.data() + 3, static_cast<uint16_t>(msg.size()));
    std::memcpy(buf.data() + 5, msg.data(), msg.size());
    send_to_client(client, buf.data(), buf.size());
  }

  void send_room_info(std::shared_ptr<LobbySession> client, uint32_t room_id) {
    const RoomMetadata* meta = room_mgr_.GetRoomMetadata(room_id);
    if (!meta) return;

    std::vector<uint8_t> buf(1 + ROOM_METADATA_SIZE);
    buf[0] = std::to_underlying(LobbyMessageType::RoomInfo);
    PackRoomMetadata(*meta, buf.data() + 1, ROOM_METADATA_SIZE);
    send_to_client(client, buf.data(), buf.size());
  }

  void send_room_list(std::shared_ptr<LobbySession> client,
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
  std::vector<std::shared_ptr<LobbySession>> clients_;
  frame_sync::RoomManager room_mgr_;
// 2026-09-09: bounded transport, connection accounting and asynchronous lifetime.
//   std::atomic<bool> running_{true};
// };
// 
// }  // namespace frame_sync
  std::atomic<bool> running_{true};
  const LobbyLimits limits_;
  asio::steady_timer maintenance_;
  static constexpr size_t kReceiveBytes = 16 * 1024;
  size_t rejected_connections_ = 0;
  size_t overload_disconnects_ = 0;
  size_t invalid_messages_ = 0;
  };  // Impl

 public:
  LobbyServer(asio::io_context& io, unsigned short port, LobbyLimits limits = LobbyLimits{})
      : impl_(std::make_shared<Impl>(io, port, limits)) { impl_->start(); }
  ~LobbyServer() { stop(); }
  LobbyServer(const LobbyServer&) = delete;
  LobbyServer& operator=(const LobbyServer&) = delete;
  LobbyServer(LobbyServer&&) = delete;
  LobbyServer& operator=(LobbyServer&&) = delete;
  void stop() { impl_->stop(); }
  unsigned short port() const { return impl_->port(); }
  LobbyStats stats() const { return impl_->stats(); }
 private:
  std::shared_ptr<Impl> impl_;
};

}  // namespace frame_sync
#endif
