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
#include "frame_sync/bounded_tcp_writer.hpp"

#include <utility>
#include <boost/asio.hpp>
#include <functional>
#include <array>
#include <string>
#include <vector>

namespace frame_sync {

/// @brief Lobby client — connects to lobby server for room operations
// 2026-09-09: bound live client IO and histories; serialize reads/writes in private poll executor.
// class LobbyClient {
//  public:
//   using Callback = std::move_only_function<void(LobbyMessageType, const uint8_t*, size_t)>;
//
//   LobbyClient(boost::asio::io_context& io)
//       : io_(io), socket_(io) {}
//
//   /// @brief Connect to lobby server
//   bool connect(const std::string& host, unsigned short port) {
//     boost::asio::ip::tcp::resolver resolver(io_);
//     boost::system::error_code ec;
//     auto endpoints = resolver.resolve(host, std::to_string(port), ec);
//     if (ec) return false;
//     boost::asio::connect(socket_, endpoints, ec);
//     if (ec) return false;
//     connected_ = true;
//     // 2026-09-09: poll owns reads; mixing async and synchronous reads loses messages.
//     // do_read();
//     return true;
//   }
//
//   /// @brief Set player name (sent to server)
//   void set_name(const std::string& name) {
//     // 2026-09-09: bound the payload before copying into the fixed buffer.
//     if (name.empty() || name.size() > 32) return;
//     player_name_ = name;
//     // Send NameSet message (type=0xFF)
//     uint8_t buf[256];
//     buf[0] = 0xFF;  // Private lobby message for name
//     PackUint16(buf + 1, static_cast<uint16_t>(name.size()));
//     std::memcpy(buf + 3, name.data(), name.size());
//     boost::system::error_code ec;
//     boost::asio::write(socket_, boost::asio::buffer(buf, 3 + name.size()), ec);
//   }
//
//   /// @brief Create a room
//   void create_room(const std::string& name, const std::string& scenario,
//                    uint16_t max_players = 2, uint32_t seed = 0) {
//     RoomConfig config{};
//     std::strncpy(config.name, name.c_str(), sizeof(config.name) - 1);
//     std::strncpy(config.scenario, scenario.c_str(), sizeof(config.scenario) - 1);
//     config.seed = seed;
//     config.max_players = max_players;
//     config.allow_spectators = true;
//
//     uint8_t buf[1 + ROOM_CONFIG_SIZE];
//     buf[0] = std::to_underlying(LobbyMessageType::CreateRoom);
//     PackRoomConfig(config, buf + 1, ROOM_CONFIG_SIZE);
//     boost::system::error_code ec;
//     boost::asio::write(socket_, boost::asio::buffer(buf, sizeof(buf)), ec);
//   }
//
//   /// @brief Join a room
//   void join_room(uint32_t room_id) {
//     uint8_t buf[5];
//     buf[0] = std::to_underlying(LobbyMessageType::JoinRoom);
//     PackUint32(buf + 1, room_id);
//     boost::system::error_code ec;
//     boost::asio::write(socket_, boost::asio::buffer(buf, sizeof(buf)), ec);
//   }
//
//   /// @brief Leave current room
//   void leave_room(uint32_t room_id) {
//     uint8_t buf[5];
//     buf[0] = std::to_underlying(LobbyMessageType::LeaveRoom);
//     PackUint32(buf + 1, room_id);
//     boost::system::error_code ec;
//     boost::asio::write(socket_, boost::asio::buffer(buf, sizeof(buf)), ec);
//   }
//
//   /// @brief Request room list
//   void request_room_list() {
//     uint8_t buf[1];
//     buf[0] = std::to_underlying(LobbyMessageType::RoomList);
//     boost::system::error_code ec;
//     boost::asio::write(socket_, boost::asio::buffer(buf, 1), ec);
//   }
//
//   /// @brief Send chat message
//   void send_chat(uint32_t room_id, const std::string& msg) {
//     if (msg.size() > 4096) return;
//     std::vector<uint8_t> buf(1 + ROOM_ID_BYTES + sizeof(uint16_t) + msg.size());
//     buf[0] = std::to_underlying(LobbyMessageType::Chat);
//     PackUint32(buf.data() + 1, room_id);
//     PackUint16(buf.data() + 5, static_cast<uint16_t>(msg.size()));
//     std::memcpy(buf.data() + 7, msg.data(), msg.size());
//     boost::system::error_code ec;
//     boost::asio::write(socket_, boost::asio::buffer(buf.data(), buf.size()), ec);
//   }
//
//   /// @brief Set ready
//   void set_ready(uint32_t room_id) {
//     uint8_t buf[5];
//     buf[0] = std::to_underlying(LobbyMessageType::Ready);
//     PackUint32(buf + 1, room_id);
//     boost::system::error_code ec;
//     boost::asio::write(socket_, boost::asio::buffer(buf, sizeof(buf)), ec);
//   }
//
//   /// @brief Start game (host only)
//   void start_game(uint32_t room_id, const std::string& game_addr) {
//     // 2026-09-09: explicit string length keeps following TCP messages intact.
//     //     std::vector<uint8_t> buf(1 + ROOM_ID_BYTES + game_addr.size());
//     //     buf[0] = std::to_underlying(LobbyMessageType::StartGame);
//     //     PackUint32(buf.data() + 1, room_id);
//     //     std::memcpy(buf.data() + 5, game_addr.data(), game_addr.size());
//     //     boost::system::error_code ec;
//     //     boost::asio::write(socket_, boost::asio::buffer(buf.data(), buf.size()), ec);
//     //   }
//     if (game_addr.size() > 96) return;
//     std::vector<uint8_t> buf(7 + game_addr.size());
//     buf[0] = std::to_underlying(LobbyMessageType::StartGame);
//     PackUint32(buf.data() + 1, room_id);
//     PackString(buf.data() + 5, buf.size() - 5, game_addr);
//     boost::system::error_code ec;
//     boost::asio::write(socket_, boost::asio::buffer(buf), ec);
//   }
//
//   /// @brief Non-blocking poll for incoming data
// //   void poll() {
// //     if (!connected_) return;
// //     boost::system::error_code ec;
// //     while (socket_.available(ec) > 0 && !ec) {
// //       std::vector<uint8_t> buf(4096);
// //       size_t n = socket_.read_some(boost::asio::buffer(buf), ec);
// //       if (ec || n == 0) {
// //         connected_ = false;
// //         return;
// //       }
// //       recv_buf_.insert(recv_buf_.end(), buf.begin(), buf.begin() + n);
// //       while (process_one_message()) {}
// //     }
// //     if (ec && ec != boost::asio::error::would_block) {
// //       connected_ = false;
// //     }
// //   }
// //
// //   /// @brief Set callback for incoming messages
//   // 2026-09-09: single-threaded polling detects EOF even when available() is zero.
//   void poll() {
//     if (!connected_) return;
//     boost::system::error_code ec;
//     socket_.non_blocking(true, ec);
//     if (ec) { connected_ = false; return; }
//     std::array<uint8_t, 4096> buf;
//     while (connected_) {
//       size_t n = socket_.read_some(boost::asio::buffer(buf), ec);
//       if (ec == boost::asio::error::would_block || ec == boost::asio::error::try_again) break;
//       if (ec || n == 0) { connected_ = false; break; }
//       recv_buf_.insert(recv_buf_.end(), buf.begin(), buf.begin() + n);
//       while (process_one_message()) {}
//     }
//     socket_.non_blocking(false, ec);
//   }
//
//   void on_message(Callback cb) { callback_ = std::move(cb); }
//
//   /// @brief Check if connected
//   [[nodiscard]] bool is_connected() const { return connected_; }
//
//   /// @brief Get latest room list (populated by RoomListResponse)
//   [[nodiscard]] const std::vector<RoomMetadata>& get_rooms() const { return rooms_; }
//
//   /// @brief Get latest room info (populated by RoomInfo)
//   [[nodiscard]] const RoomMetadata& get_current_room() const { return current_room_; }
//
//   /// @brief Get received chat messages
//   [[nodiscard]] const std::vector<std::pair<std::string, std::string>>& get_chats() const {
//     return chats_;
//   }
//
//   /// @brief Pop chats (clear buffer)
//   void pop_chats() { chats_.clear(); }
//
//   /// @brief Get player name
//   [[nodiscard]] const std::string& player_name() const { return player_name_; }
//
//   void disconnect() {
//     connected_ = false;
//     boost::system::error_code ec;
//     socket_.close(ec);
//   }
//
//  private:
//   // 2026-09-09: removed competing receive path; poll() is the only reader.
// //   void do_read() {
// //     auto buf = std::make_shared<std::vector<uint8_t>>(4096);
// //     socket_.async_read_some(
// //         boost::asio::buffer(*buf),
// //         [this, buf](boost::system::error_code ec, std::size_t length) {
// //           if (ec) {
// //             connected_ = false;
// //             return;
// //           }
// //           recv_buf_.insert(recv_buf_.end(), buf->begin(), buf->begin() + length);
// //           while (process_one_message()) {}
// //           if (connected_) do_read();
// //         });
// //   }
// //
//   bool process_one_message() {
//     if (recv_buf_.empty()) return false;
//     uint8_t type = recv_buf_[0];
//
//     // RoomListResponse: type(1) + count(2) + RoomMetadata[]
//     if (type == std::to_underlying(LobbyMessageType::RoomListResponse)) {
//       if (recv_buf_.size() < 3) return false;
//       uint16_t count;
//       UnpackUint16(recv_buf_.data() + 1, sizeof(uint16_t), &count);
//       size_t need = 3 + count * ROOM_METADATA_SIZE;
//       if (recv_buf_.size() < need) return false;
//
//       rooms_.clear();
//       for (uint16_t i = 0; i < count; ++i) {
//         RoomMetadata room;
//         UnpackRoomMetadata(recv_buf_.data() + 3 + i * ROOM_METADATA_SIZE,
//                            ROOM_METADATA_SIZE, &room);
//         rooms_.push_back(room);
//       }
//
//       if (callback_) callback_(static_cast<LobbyMessageType>(type), recv_buf_.data(), need);
//       recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + need);
//       return true;
//     }
//
//     // RoomInfo: type(1) + RoomMetadata
//     if (type == std::to_underlying(LobbyMessageType::RoomInfo)) {
//       if (recv_buf_.size() < 1 + ROOM_METADATA_SIZE) return false;
//       UnpackRoomMetadata(recv_buf_.data() + 1, ROOM_METADATA_SIZE, &current_room_);
//       if (callback_) callback_(static_cast<LobbyMessageType>(type), recv_buf_.data(), 1 + ROOM_METADATA_SIZE);
//       recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + 1 + ROOM_METADATA_SIZE);
//       return true;
//     }
//
//     // RoomCreated: type(1) + room_id(4)
//     if (type == std::to_underlying(LobbyMessageType::RoomCreated)) {
//       if (recv_buf_.size() < 5) return false;
//       if (callback_) callback_(static_cast<LobbyMessageType>(type), recv_buf_.data(), 5);
//       recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + 5);
//       return true;
//     }
//
//     // ChatMessage: type(1) + room_id(4) + sender + msg
//     if (type == std::to_underlying(LobbyMessageType::ChatMessage)) {
//       if (recv_buf_.size() < 5) return false;
//       // Minimum: type + room_id + 2 + 0 + 2 + 0 = 9
//       if (recv_buf_.size() < 9) return false;
//
//       size_t offset = 1 + ROOM_ID_BYTES;
//       std::string sender;
//       // 2026-09-09: do not consume either string until the whole chat packet arrives.
//       // offset += UnpackString(..., &sender); offset += UnpackString(..., &msg);
//       size_t used = UnpackString(recv_buf_.data() + offset, recv_buf_.size() - offset, &sender);
//       if (used == 0) return false;
//       offset += used;
//       std::string msg;
//       used = UnpackString(recv_buf_.data() + offset, recv_buf_.size() - offset, &msg);
//       if (used == 0) return false;
//       offset += used;
//
//       if (chats_.size() >= 1024) chats_.erase(chats_.begin());
//       chats_.emplace_back(std::move(sender), std::move(msg));
//       if (callback_) callback_(static_cast<LobbyMessageType>(type), recv_buf_.data(), offset);
//       recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + offset);
//       return true;
//     }
//
//     // PlayerJoined/PlayerLeft: type(1) + room_id(4) + name_len(2) + name
//     if (type == std::to_underlying(LobbyMessageType::PlayerJoined) ||
//         type == std::to_underlying(LobbyMessageType::PlayerLeft)) {
//       if (recv_buf_.size() < 7) return false;
//       uint16_t name_len;
//       UnpackUint16(recv_buf_.data() + 5, sizeof(uint16_t), &name_len);
//       size_t need = 7 + name_len;
//       if (recv_buf_.size() < need) return false;
//       if (callback_) callback_(static_cast<LobbyMessageType>(type), recv_buf_.data(), need);
//       recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + need);
//       return true;
//     }
//
//     // GameStarted: type(1) + room_id(4) + addr(32) + port(2)
//     if (type == std::to_underlying(LobbyMessageType::GameStarted)) {
//       if (recv_buf_.size() < 1 + 4 + 32 + 2) return false;
//       if (callback_) callback_(static_cast<LobbyMessageType>(type), recv_buf_.data(), 1 + 4 + 32 + 2);
//       recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + 1 + 4 + 32 + 2);
//       return true;
//     }
//
//     // Error: type(1) + code(2) + msg_len(2) + msg
//     if (type == std::to_underlying(LobbyMessageType::Error)) {
//       if (recv_buf_.size() < 5) return false;
//       uint16_t msg_len;
//       UnpackUint16(recv_buf_.data() + 3, sizeof(uint16_t), &msg_len);
//       size_t need = 5 + msg_len;
//       if (recv_buf_.size() < need) return false;
//       if (callback_) callback_(static_cast<LobbyMessageType>(type), recv_buf_.data(), need);
//       recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + need);
//       return true;
//     }
//
//     // Unknown: skip 1 byte
//     recv_buf_.erase(recv_buf_.begin());
//     return true;
//   }
//
//   boost::asio::io_context& io_;
//   boost::asio::ip::tcp::socket socket_;
//   bool connected_ = false;
//   std::string player_name_;
//   std::vector<uint8_t> recv_buf_;
//   Callback callback_;
//
//   std::vector<RoomMetadata> rooms_;
//   RoomMetadata current_room_;
//   std::vector<std::pair<std::string, std::string>> chats_;
// };
enum class LobbyClientStatus {
  Disconnected, Connected, SendCapacity, ReceiveCapacity, InvalidMessage, IoError, WriteTimeout
};
struct LobbyClientStats {
  size_t receive_capacity = 0;
  size_t queued_send_bytes = 0;
  size_t queued_send_messages = 0;
  size_t chat_string_bytes = 0;
  size_t chat_storage_bytes = 0;
  size_t room_storage_bytes = 0;
  size_t evicted_chats = 0;
  size_t last_poll_handlers = 0;
};

// Single-threaded UI API: poll() alone dispatches private transport callbacks.
// The caller's io_context need not run. No callback can run after destruction.
class LobbyClient {
 public:
  using Callback = std::move_only_function<void(LobbyMessageType, const uint8_t*, size_t)>;
  static constexpr size_t kRoomLimit = 256;
  static constexpr size_t kReceiveLimit = 3 + kRoomLimit * ROOM_METADATA_SIZE + 4096;
  static constexpr size_t kChatLimit = 1024;
  static constexpr size_t kChatByteLimit = 1024 * 1024;
  static constexpr size_t kPollHandlerLimit = 64;

  explicit LobbyClient(boost::asio::io_context&,
                       StreamBudget budget = StreamBudget(256, 128 * 1024))
      : send_budget_(budget.message_limit, budget.byte_limit) {
    chats_.reserve(kChatLimit);
  }
  ~LobbyClient() { disconnect(); }
  LobbyClient(const LobbyClient&) = delete;
  LobbyClient& operator=(const LobbyClient&) = delete;
  LobbyClient(LobbyClient&&) = delete;
  LobbyClient& operator=(LobbyClient&&) = delete;

  // Connection setup remains synchronous. Live traffic is asynchronous and
  // bounded; call poll regularly while connected and to drain cancellation.
  bool connect(const std::string& host, unsigned short port) {
    if (polling_) return false;
    disconnect();
    network_io_.restart();
    network_io_.poll();  // The closed previous transport cannot initiate more IO.
    writer_.reset();
    socket_ = std::make_shared<boost::asio::ip::tcp::socket>(network_io_);
    boost::asio::ip::tcp::resolver resolver(network_io_);
    boost::system::error_code ec;
    auto endpoints = resolver.resolve(host, std::to_string(port), ec);
    if (!ec) boost::asio::connect(*socket_, endpoints, ec);
    if (ec) { status_ = LobbyClientStatus::IoError; return false; }
    writer_ = std::make_unique<BoundedTCPWriter>(socket_, send_budget_);
    rooms_.clear(); current_room_ = {}; player_name_.clear(); pop_chats();
    evicted_chats_ = 0;
    connected_ = true;
    status_ = LobbyClientStatus::Connected;
    Read();
    return true;
  }

  bool set_name(const std::string& name) {
    if (name.empty() || name.size() > 32) return false;
    std::array<uint8_t, 35> bytes{};
    bytes[0] = 0xFF;
    PackString(bytes.data() + 1, bytes.size() - 1, name);
    if (!Send(bytes.data(), 3 + name.size())) return false;
    player_name_ = name;
    return true;
  }
  bool create_room(const std::string& name, const std::string& scenario,
                   uint16_t max_players = 2, uint32_t seed = 0) {
    if (max_players < 2 || max_players > 22) return false;
    RoomConfig config{};
    std::strncpy(config.name, name.c_str(), sizeof(config.name) - 1);
    std::strncpy(config.scenario, scenario.c_str(), sizeof(config.scenario) - 1);
    config.seed = seed; config.max_players = max_players;
    std::array<uint8_t, 1 + ROOM_CONFIG_SIZE> bytes{};
    bytes[0] = std::to_underlying(LobbyMessageType::CreateRoom);
    PackRoomConfig(config, bytes.data() + 1, ROOM_CONFIG_SIZE);
    return Send(bytes.data(), bytes.size());
  }
  bool join_room(uint32_t room) { return SendRoom(LobbyMessageType::JoinRoom, room); }
  bool leave_room(uint32_t room) { return SendRoom(LobbyMessageType::LeaveRoom, room); }
  bool set_ready(uint32_t room) { return SendRoom(LobbyMessageType::Ready, room); }
  bool request_room_list() {
    const uint8_t type = std::to_underlying(LobbyMessageType::RoomList);
    return Send(&type, 1);
  }
  bool send_chat(uint32_t room, const std::string& message) {
    if (message.size() > 4096) return false;
    std::array<uint8_t, 7 + 4096> bytes{};
    bytes[0] = std::to_underlying(LobbyMessageType::Chat);
    PackUint32(bytes.data() + 1, room);
    PackString(bytes.data() + 5, bytes.size() - 5, message);
    return Send(bytes.data(), 7 + message.size());
  }
  bool start_game(uint32_t room, const std::string& address) {
    if (address.size() > 96) return false;
    std::array<uint8_t, 7 + 96> bytes{};
    bytes[0] = std::to_underlying(LobbyMessageType::StartGame);
    PackUint32(bytes.data() + 1, room);
    PackString(bytes.data() + 5, bytes.size() - 5, address);
    return Send(bytes.data(), 7 + address.size());
  }

  void poll() {
    if (polling_) return;
    struct PollGuard {
      bool& flag;
      explicit PollGuard(bool& value) : flag(value) { flag = true; }
      ~PollGuard() { flag = false; }
    } guard(polling_);
    last_poll_handlers_ = 0;
    network_io_.restart();
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(2);
    while (last_poll_handlers_ < kPollHandlerLimit && network_io_.poll_one() != 0) {
      ++last_poll_handlers_;
      if (std::chrono::steady_clock::now() >= deadline) break;
    }
    CheckTransport();
  }
  void on_message(Callback cb) { callback_ = std::make_shared<Callback>(std::move(cb)); }
  [[nodiscard]] bool is_connected() const { return connected_ && writer_ && !writer_->is_closed(); }
  [[nodiscard]] LobbyClientStatus status() const { return status_; }
  [[nodiscard]] const std::vector<RoomMetadata>& get_rooms() const { return rooms_; }
  [[nodiscard]] const RoomMetadata& get_current_room() const { return current_room_; }
  [[nodiscard]] const std::vector<std::pair<std::string, std::string>>& get_chats() const { return chats_; }
  [[nodiscard]] const std::string& player_name() const { return player_name_; }
  void pop_chats() { chats_.clear(); chat_bytes_ = 0; }
  [[nodiscard]] LobbyClientStats stats() const {
    return {recv_buf_.capacity(), writer_ ? writer_->queued_bytes() : 0,
            writer_ ? writer_->queued_messages() : 0, chat_bytes_,
            chats_.capacity() * sizeof(chats_[0]), rooms_.capacity() * sizeof(RoomMetadata),
            evicted_chats_, last_poll_handlers_};
  }
  void disconnect() { Fail(LobbyClientStatus::Disconnected); }

 private:
  void Fail(LobbyClientStatus reason) {
    connected_ = false;
    status_ = reason;
    if (writer_) writer_->Close();
    std::vector<uint8_t>().swap(recv_buf_);
  }
  void CheckTransport() {
    if (!connected_ || !writer_->is_closed()) return;
    const auto reason = writer_->status() == StreamStatus::WriteTimeout
        ? LobbyClientStatus::WriteTimeout : LobbyClientStatus::IoError;
    Fail(reason);
  }
  bool Send(const uint8_t* bytes, size_t length) {
    CheckTransport();
    if (!connected_) return false;
    if (writer_->TrySend(bytes, length)) return true;
    Fail(writer_->status() == StreamStatus::Capacity
        ? LobbyClientStatus::SendCapacity : LobbyClientStatus::IoError);
    return false;
  }
  bool SendRoom(LobbyMessageType type, uint32_t room) {
    uint8_t bytes[5]; bytes[0] = std::to_underlying(type);
    PackUint32(bytes + 1, room);
    return Send(bytes, sizeof(bytes));
  }
  void Read() {
    auto bytes = std::make_shared<std::array<uint8_t, 4096>>();
    if (!writer_->AsyncReadSome(boost::asio::buffer(*bytes),
          [this, bytes](boost::system::error_code ec, size_t length) {
            if (!connected_) return;
            if (ec || length == 0) { CheckTransport(); return; }
            if (!AppendBoundedBytes(recv_buf_, bytes->data(), length, kReceiveLimit)) {
              Fail(LobbyClientStatus::ReceiveCapacity); return;
            }
            try {
              while (connected_ && Process()) {}
            } catch (...) {
              Fail(LobbyClientStatus::InvalidMessage);
              throw;
            }
            if (connected_) Read();
          })) CheckTransport();
  }
  bool Invalid() { Fail(LobbyClientStatus::InvalidMessage); return false; }
  bool Dispatch(LobbyMessageType type, size_t length) {
    // Own this packet and consume the parser first: callbacks may disconnect,
    // replace themselves or clear histories without invalidating packet memory.
    auto callback = callback_;
    std::vector<uint8_t> packet;
    if (callback && *callback) packet.assign(recv_buf_.begin(), recv_buf_.begin() + length);
    recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + length);
    if (callback && *callback) (*callback)(type, packet.data(), packet.size());
    return connected_;
  }
  bool Process() {
    if (recv_buf_.empty()) return false;
    const auto type = static_cast<LobbyMessageType>(recv_buf_[0]);
    if (type == LobbyMessageType::RoomListResponse) {
      if (recv_buf_.size() < 3) return false;
      uint16_t count; UnpackUint16(recv_buf_.data() + 1, 2, &count);
      if (count > kRoomLimit) return Invalid();
      const size_t need = 3 + count * ROOM_METADATA_SIZE;
      if (recv_buf_.size() < need) return false;
      std::vector<RoomMetadata> rooms(count);
      for (size_t i = 0; i < count; ++i)
        if (!UnpackRoomMetadata(recv_buf_.data() + 3 + i * ROOM_METADATA_SIZE,
                                ROOM_METADATA_SIZE, &rooms[i])) return Invalid();
      rooms_ = std::move(rooms);
      return Dispatch(type, need);
    }
    if (type == LobbyMessageType::RoomInfo) {
      if (recv_buf_.size() < 1 + ROOM_METADATA_SIZE) return false;
      if (!UnpackRoomMetadata(recv_buf_.data() + 1, ROOM_METADATA_SIZE, &current_room_)) return Invalid();
      return Dispatch(type, 1 + ROOM_METADATA_SIZE);
    }
    if (type == LobbyMessageType::RoomCreated) {
      if (recv_buf_.size() < 5) return false;
      return Dispatch(type, 5);
    }
    if (type == LobbyMessageType::ChatMessage) {
      if (recv_buf_.size() < 7) return false;
      uint16_t sender_size; UnpackUint16(recv_buf_.data() + 5, 2, &sender_size);
      if (sender_size > 32) return Invalid();
      const size_t message_offset = 7 + sender_size;
      if (recv_buf_.size() < message_offset + 2) return false;
      uint16_t message_size; UnpackUint16(recv_buf_.data() + message_offset, 2, &message_size);
      if (message_size > 4096) return Invalid();
      const size_t need = message_offset + 2 + message_size;
      if (recv_buf_.size() < need) return false;
      std::string sender(reinterpret_cast<const char*>(recv_buf_.data() + 7), sender_size);
      std::string message(reinterpret_cast<const char*>(recv_buf_.data() + message_offset + 2), message_size);
      const size_t retained = sender.capacity() + message.capacity() + 2;
      while (!chats_.empty() && (chats_.size() >= kChatLimit || retained > kChatByteLimit - chat_bytes_)) {
        // Release the erased strings before vector's move assignments. An SSO
        // source otherwise may leave the destination's old large capacity alive.
        { std::pair<std::string, std::string> empty; chats_.front().swap(empty); }
        chats_.erase(chats_.begin()); ++evicted_chats_;
        chat_bytes_ = 0;
        for (const auto& chat : chats_) chat_bytes_ += chat.first.capacity() + chat.second.capacity() + 2;
      }
      if (retained > kChatByteLimit - chat_bytes_) return Invalid();
      chats_.emplace_back(std::move(sender), std::move(message));
      chat_bytes_ += retained;
      return Dispatch(type, need);
    }
    if (type == LobbyMessageType::PlayerJoined || type == LobbyMessageType::PlayerLeft) {
      if (recv_buf_.size() < 7) return false;
      uint16_t length; UnpackUint16(recv_buf_.data() + 5, 2, &length);
      if (length > 32) return Invalid();
      if (recv_buf_.size() < 7u + length) return false;
      return Dispatch(type, 7u + length);
    }
    if (type == LobbyMessageType::GameStarted) {
      if (recv_buf_.size() < 39) return false;
      if (!std::memchr(recv_buf_.data() + 5, 0, 32)) return Invalid();
      return Dispatch(type, 39);
    }
    if (type == LobbyMessageType::Error) {
      if (recv_buf_.size() < 5) return false;
      uint16_t length; UnpackUint16(recv_buf_.data() + 3, 2, &length);
      if (length > 4096) return Invalid();
      if (recv_buf_.size() < 5u + length) return false;
      return Dispatch(type, 5u + length);
    }
    return Invalid();
  }

  // Declared first, destroyed last, after all transport owners and UI state.
  boost::asio::io_context network_io_;
  const StreamBudget send_budget_;
  std::shared_ptr<boost::asio::ip::tcp::socket> socket_;
  std::unique_ptr<BoundedTCPWriter> writer_;
  bool connected_ = false;
  bool polling_ = false;
  LobbyClientStatus status_ = LobbyClientStatus::Disconnected;
  std::string player_name_;
  std::vector<uint8_t> recv_buf_;
  std::shared_ptr<Callback> callback_;
  std::vector<RoomMetadata> rooms_;
  RoomMetadata current_room_;
  std::vector<std::pair<std::string, std::string>> chats_;
  size_t chat_bytes_ = 0;
  size_t evicted_chats_ = 0;
  size_t last_poll_handlers_ = 0;
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_LOBBY_CLIENT_HPP
