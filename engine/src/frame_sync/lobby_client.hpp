// Copyright 2026 Google LLC & Contributors
// Lobby Client for connecting to lobby server (ms-18.4).
// Provides API for room operations and chat.
//
// Usage:
//   LobbyClient lobby(io);
//   lobby.connect("127.0.0.1", 12346);
//   lobby.set_name("Alice");
//   lobby.create_room("My Room", "academy_empty_goal_close", 2);
//   lobby.poll();
//   auto rooms = lobby.get_rooms();

#ifndef GFOOTBALL_FRAME_SYNC_LOBBY_CLIENT_HPP
#define GFOOTBALL_FRAME_SYNC_LOBBY_CLIENT_HPP

#include "frame_sync/lobby_protocol.hpp"

#include <utility>
#include <boost/asio.hpp>
#include <functional>
#include <string>
#include <vector>

namespace frame_sync {

/// @brief Lobby client — connects to lobby server for room operations
class LobbyClient {
 public:
  using Callback = std::move_only_function<void(LobbyMessageType, const uint8_t*, size_t)>;

  LobbyClient(boost::asio::io_context& io)
      : io_(io), socket_(io) {}

  /// @brief Connect to lobby server
  bool connect(const std::string& host, unsigned short port) {
    boost::asio::ip::tcp::resolver resolver(io_);
    boost::system::error_code ec;
    auto endpoints = resolver.resolve(host, std::to_string(port), ec);
    if (ec) return false;
    boost::asio::connect(socket_, endpoints, ec);
    if (ec) return false;
    connected_ = true;
    do_read();
    return true;
  }

  /// @brief Set player name (sent to server)
  void set_name(const std::string& name) {
    player_name_ = name;
    // Send NameSet message (type=0xFF)
    uint8_t buf[256];
    buf[0] = 0xFF;  // Private lobby message for name
    PackUint16(buf + 1, static_cast<uint16_t>(name.size()));
    std::memcpy(buf + 3, name.data(), name.size());
    boost::system::error_code ec;
    boost::asio::write(socket_, boost::asio::buffer(buf, 3 + name.size()), ec);
  }

  /// @brief Create a room
  void create_room(const std::string& name, const std::string& scenario,
                   uint16_t max_players = 2, uint32_t seed = 0) {
    RoomConfig config{};
    std::strncpy(config.name, name.c_str(), sizeof(config.name) - 1);
    std::strncpy(config.scenario, scenario.c_str(), sizeof(config.scenario) - 1);
    config.seed = seed;
    config.max_players = max_players;
    config.allow_spectators = true;

    uint8_t buf[1 + ROOM_CONFIG_SIZE];
    buf[0] = std::to_underlying(LobbyMessageType::CreateRoom);
    PackRoomConfig(config, buf + 1, ROOM_CONFIG_SIZE);
    boost::system::error_code ec;
    boost::asio::write(socket_, boost::asio::buffer(buf, sizeof(buf)), ec);
  }

  /// @brief Join a room
  void join_room(uint32_t room_id) {
    uint8_t buf[5];
    buf[0] = std::to_underlying(LobbyMessageType::JoinRoom);
    PackUint32(buf + 1, room_id);
    boost::system::error_code ec;
    boost::asio::write(socket_, boost::asio::buffer(buf, sizeof(buf)), ec);
  }

  /// @brief Leave current room
  void leave_room(uint32_t room_id) {
    uint8_t buf[5];
    buf[0] = std::to_underlying(LobbyMessageType::LeaveRoom);
    PackUint32(buf + 1, room_id);
    boost::system::error_code ec;
    boost::asio::write(socket_, boost::asio::buffer(buf, sizeof(buf)), ec);
  }

  /// @brief Request room list
  void request_room_list() {
    uint8_t buf[1];
    buf[0] = std::to_underlying(LobbyMessageType::RoomList);
    boost::system::error_code ec;
    boost::asio::write(socket_, boost::asio::buffer(buf, 1), ec);
  }

  /// @brief Send chat message
  void send_chat(uint32_t room_id, const std::string& msg) {
    std::vector<uint8_t> buf(1 + ROOM_ID_BYTES + sizeof(uint16_t) + msg.size());
    buf[0] = std::to_underlying(LobbyMessageType::Chat);
    PackUint32(buf.data() + 1, room_id);
    PackUint16(buf.data() + 5, static_cast<uint16_t>(msg.size()));
    std::memcpy(buf.data() + 7, msg.data(), msg.size());
    boost::system::error_code ec;
    boost::asio::write(socket_, boost::asio::buffer(buf.data(), buf.size()), ec);
  }

  /// @brief Set ready
  void set_ready(uint32_t room_id) {
    uint8_t buf[5];
    buf[0] = std::to_underlying(LobbyMessageType::Ready);
    PackUint32(buf + 1, room_id);
    boost::system::error_code ec;
    boost::asio::write(socket_, boost::asio::buffer(buf, sizeof(buf)), ec);
  }

  /// @brief Start game (host only)
  void start_game(uint32_t room_id, const std::string& game_addr) {
    std::vector<uint8_t> buf(1 + ROOM_ID_BYTES + game_addr.size());
    buf[0] = std::to_underlying(LobbyMessageType::StartGame);
    PackUint32(buf.data() + 1, room_id);
    std::memcpy(buf.data() + 5, game_addr.data(), game_addr.size());
    boost::system::error_code ec;
    boost::asio::write(socket_, boost::asio::buffer(buf.data(), buf.size()), ec);
  }

  /// @brief Non-blocking poll for incoming data
  void poll() {
    if (!connected_) return;
    boost::system::error_code ec;
    while (socket_.available(ec) > 0 && !ec) {
      std::vector<uint8_t> buf(4096);
      size_t n = socket_.read_some(boost::asio::buffer(buf), ec);
      if (ec || n == 0) {
        connected_ = false;
        return;
      }
      recv_buf_.insert(recv_buf_.end(), buf.begin(), buf.begin() + n);
      while (process_one_message()) {}
    }
    if (ec && ec != boost::asio::error::would_block) {
      connected_ = false;
    }
  }

  /// @brief Set callback for incoming messages
  void on_message(Callback cb) { callback_ = std::move(cb); }

  /// @brief Check if connected
  [[nodiscard]] bool is_connected() const { return connected_; }

  /// @brief Get latest room list (populated by RoomListResponse)
  [[nodiscard]] const std::vector<RoomMetadata>& get_rooms() const { return rooms_; }

  /// @brief Get latest room info (populated by RoomInfo)
  [[nodiscard]] const RoomMetadata& get_current_room() const { return current_room_; }

  /// @brief Get received chat messages
  [[nodiscard]] const std::vector<std::pair<std::string, std::string>>& get_chats() const {
    return chats_;
  }

  /// @brief Pop chats (clear buffer)
  void pop_chats() { chats_.clear(); }

  /// @brief Get player name
  [[nodiscard]] const std::string& player_name() const { return player_name_; }

  void disconnect() {
    connected_ = false;
    boost::system::error_code ec;
    socket_.close(ec);
  }

 private:
  void do_read() {
    auto buf = std::make_shared<std::vector<uint8_t>>(4096);
    socket_.async_read_some(
        boost::asio::buffer(*buf),
        [this, buf](boost::system::error_code ec, std::size_t length) {
          if (ec) {
            connected_ = false;
            return;
          }
          recv_buf_.insert(recv_buf_.end(), buf->begin(), buf->begin() + length);
          while (process_one_message()) {}
          if (connected_) do_read();
        });
  }

  bool process_one_message() {
    if (recv_buf_.empty()) return false;
    uint8_t type = recv_buf_[0];

    // RoomListResponse: type(1) + count(2) + RoomMetadata[]
    if (type == std::to_underlying(LobbyMessageType::RoomListResponse)) {
      if (recv_buf_.size() < 3) return false;
      uint16_t count;
      UnpackUint16(recv_buf_.data() + 1, sizeof(uint16_t), &count);
      size_t need = 3 + count * ROOM_METADATA_SIZE;
      if (recv_buf_.size() < need) return false;

      rooms_.clear();
      for (uint16_t i = 0; i < count; ++i) {
        RoomMetadata room;
        UnpackRoomMetadata(recv_buf_.data() + 3 + i * ROOM_METADATA_SIZE,
                           ROOM_METADATA_SIZE, &room);
        rooms_.push_back(room);
      }

      if (callback_) callback_(static_cast<LobbyMessageType>(type), recv_buf_.data(), need);
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + need);
      return true;
    }

    // RoomInfo: type(1) + RoomMetadata
    if (type == std::to_underlying(LobbyMessageType::RoomInfo)) {
      if (recv_buf_.size() < 1 + ROOM_METADATA_SIZE) return false;
      UnpackRoomMetadata(recv_buf_.data() + 1, ROOM_METADATA_SIZE, &current_room_);
      if (callback_) callback_(static_cast<LobbyMessageType>(type), recv_buf_.data(), 1 + ROOM_METADATA_SIZE);
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + 1 + ROOM_METADATA_SIZE);
      return true;
    }

    // RoomCreated: type(1) + room_id(4)
    if (type == std::to_underlying(LobbyMessageType::RoomCreated)) {
      if (recv_buf_.size() < 5) return false;
      if (callback_) callback_(static_cast<LobbyMessageType>(type), recv_buf_.data(), 5);
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + 5);
      return true;
    }

    // ChatMessage: type(1) + room_id(4) + sender + msg
    if (type == std::to_underlying(LobbyMessageType::ChatMessage)) {
      if (recv_buf_.size() < 5) return false;
      // Minimum: type + room_id + 2 + 0 + 2 + 0 = 9
      if (recv_buf_.size() < 9) return false;

      size_t offset = 1 + ROOM_ID_BYTES;
      std::string sender;
      offset += UnpackString(recv_buf_.data() + offset, recv_buf_.size() - offset, &sender);
      std::string msg;
      offset += UnpackString(recv_buf_.data() + offset, recv_buf_.size() - offset, &msg);

      chats_.emplace_back(std::move(sender), std::move(msg));
      if (callback_) callback_(static_cast<LobbyMessageType>(type), recv_buf_.data(), offset);
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + offset);
      return true;
    }

    // PlayerJoined/PlayerLeft: type(1) + room_id(4) + name_len(2) + name
    if (type == std::to_underlying(LobbyMessageType::PlayerJoined) ||
        type == std::to_underlying(LobbyMessageType::PlayerLeft)) {
      if (recv_buf_.size() < 7) return false;
      uint16_t name_len;
      UnpackUint16(recv_buf_.data() + 5, sizeof(uint16_t), &name_len);
      size_t need = 7 + name_len;
      if (recv_buf_.size() < need) return false;
      if (callback_) callback_(static_cast<LobbyMessageType>(type), recv_buf_.data(), need);
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + need);
      return true;
    }

    // GameStarted: type(1) + room_id(4) + addr(32) + port(2)
    if (type == std::to_underlying(LobbyMessageType::GameStarted)) {
      if (recv_buf_.size() < 1 + 4 + 32 + 2) return false;
      if (callback_) callback_(static_cast<LobbyMessageType>(type), recv_buf_.data(), 1 + 4 + 32 + 2);
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + 1 + 4 + 32 + 2);
      return true;
    }

    // Error: type(1) + code(2) + msg_len(2) + msg
    if (type == std::to_underlying(LobbyMessageType::Error)) {
      if (recv_buf_.size() < 5) return false;
      uint16_t msg_len;
      UnpackUint16(recv_buf_.data() + 3, sizeof(uint16_t), &msg_len);
      size_t need = 5 + msg_len;
      if (recv_buf_.size() < need) return false;
      if (callback_) callback_(static_cast<LobbyMessageType>(type), recv_buf_.data(), need);
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + need);
      return true;
    }

    // Unknown: skip 1 byte
    recv_buf_.erase(recv_buf_.begin());
    return true;
  }

  boost::asio::io_context& io_;
  boost::asio::ip::tcp::socket socket_;
  bool connected_ = false;
  std::string player_name_;
  std::vector<uint8_t> recv_buf_;
  Callback callback_;

  std::vector<RoomMetadata> rooms_;
  RoomMetadata current_room_;
  std::vector<std::pair<std::string, std::string>> chats_;
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_LOBBY_CLIENT_HPP
