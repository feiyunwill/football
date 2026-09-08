// Copyright 2026 Google LLC & Contributors
// Lobby protocol and room metadata for multi-room system (ms-18.1).
// Defines message types and data structures for lobby operations.
//
// This is a pure header-only library with no network or server dependencies.

#ifndef GFOOTBALL_FRAME_SYNC_LOBBY_PROTOCOL_HPP
#define GFOOTBALL_FRAME_SYNC_LOBBY_PROTOCOL_HPP

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <array>

namespace frame_sync {

// ----- Lobby message types -----
enum class LobbyMessageType : uint8_t {
  // Client → Server
  CreateRoom = 0,      // payload: RoomConfig
  JoinRoom = 1,        // payload: room_id(4)
  LeaveRoom = 2,       // payload: room_id(4)
  RoomList = 3,        // no payload, server responds with RoomListResponse
  Chat = 4,            // payload: room_id(4) + msg_len(2) + msg_bytes
  Ready = 5,           // payload: room_id(4)
  Unready = 6,         // payload: room_id(4)
  StartGame = 7,       // payload: room_id(4) (host only)

  // Server → Client
  RoomCreated = 10,    // payload: room_id(4)
  RoomListResponse = 11, // payload: room_count(2) + RoomMetadata[]
  RoomInfo = 12,       // payload: RoomMetadata
  ChatMessage = 13,    // payload: room_id(4) + sender_len(2) + sender + msg_len(2) + msg
  PlayerJoined = 14,   // payload: room_id(4) + player_name_len(2) + name
  PlayerLeft = 15,     // payload: room_id(4) + player_name_len(2) + name
  GameStarted = 16,    // payload: room_id(4) + game_host(32) + game_port(2)
  Error = 20,          // payload: error_code(2) + msg_len(2) + msg
};

// ----- Room status -----
enum class RoomStatus : uint8_t {
  kWaiting = 0,   // Waiting for players
  kPlaying = 1,   // Game in progress
  kFinished = 2,  // Game finished
};

// ----- Room configuration (for creation) -----
struct RoomConfig {
  char name[32] = {};         // Room display name
  char scenario[64] = {};     // Scenario name (e.g., "academy_empty_goal_close")
  uint32_t seed = 0;          // Random seed (0 = random)
  uint16_t max_players = 2;   // Max human players (1-8)
  bool allow_spectators = true;
};

// ----- Room metadata (shared between server and client) -----
struct RoomMetadata {
  uint32_t room_id = 0;
  char name[32] = {};
  char scenario[64] = {};
  uint32_t seed = 0;
  uint16_t max_players = 2;
  uint16_t player_count = 0;
  uint16_t spectator_count = 0;
  RoomStatus status = RoomStatus::kWaiting;
  char game_address[64] = {};   // IP:port of the game server (empty if not started)
  uint16_t game_port = 0;
};

// ----- Player info -----
struct PlayerInfo {
  char name[32] = {};
  bool ready = false;
  bool is_host = false;
};

// ----- Constants -----
inline constexpr size_t LOBBY_MSG_TYPE_BYTES = 1;
inline constexpr size_t ROOM_ID_BYTES = sizeof(uint32_t);
inline constexpr size_t ROOM_CONFIG_SIZE = sizeof(RoomConfig);
inline constexpr size_t ROOM_METADATA_SIZE = sizeof(RoomMetadata);

// ----- Serialization helpers -----

// Pack a uint32_t into buffer, return bytes written
inline size_t PackUint32(uint8_t* buf, uint32_t val) {
  std::memcpy(buf, &val, sizeof(uint32_t));
  return sizeof(uint32_t);
}

// Unpack a uint32_t from buffer, return bytes consumed
inline size_t UnpackUint32(const uint8_t* buf, size_t size, uint32_t* out) {
  if (size < sizeof(uint32_t)) return 0;
  std::memcpy(out, buf, sizeof(uint32_t));
  return sizeof(uint32_t);
}

// Pack a uint16_t into buffer
inline size_t PackUint16(uint8_t* buf, uint16_t val) {
  std::memcpy(buf, &val, sizeof(uint16_t));
  return sizeof(uint16_t);
}

// Unpack a uint16_t from buffer
inline size_t UnpackUint16(const uint8_t* buf, size_t size, uint16_t* out) {
  if (size < sizeof(uint16_t)) return 0;
  std::memcpy(out, buf, sizeof(uint16_t));
  return sizeof(uint16_t);
}

// Pack a string (length-prefixed: 2-byte length + data)
inline size_t PackString(uint8_t* buf, size_t buf_size, const std::string& str) {
  uint16_t len = static_cast<uint16_t>(str.size());
  if (len + sizeof(uint16_t) > buf_size) return 0;
  PackUint16(buf, len);
  std::memcpy(buf + sizeof(uint16_t), str.data(), len);
  return sizeof(uint16_t) + len;
}

// Unpack a string from buffer
inline size_t UnpackString(const uint8_t* buf, size_t size, std::string* out) {
  uint16_t len;
  size_t used = UnpackUint16(buf, size, &len);
  if (used == 0 || used + len > size) return 0;
  out->assign(reinterpret_cast<const char*>(buf + used), len);
  return used + len;
}

// ----- Pack/Unpack RoomMetadata -----
inline size_t PackRoomMetadata(const RoomMetadata& room, uint8_t* buf, size_t buf_size) {
  if (buf_size < ROOM_METADATA_SIZE) return 0;
  std::memcpy(buf, &room, ROOM_METADATA_SIZE);
  return ROOM_METADATA_SIZE;
}

inline size_t UnpackRoomMetadata(const uint8_t* buf, size_t size, RoomMetadata* out) {
  if (size < ROOM_METADATA_SIZE) return 0;
  std::memcpy(out, buf, ROOM_METADATA_SIZE);
  return ROOM_METADATA_SIZE;
}

// ----- Pack/Unpack RoomConfig -----
inline size_t PackRoomConfig(const RoomConfig& config, uint8_t* buf, size_t buf_size) {
  if (buf_size < ROOM_CONFIG_SIZE) return 0;
  std::memcpy(buf, &config, ROOM_CONFIG_SIZE);
  return ROOM_CONFIG_SIZE;
}

inline size_t UnpackRoomConfig(const uint8_t* buf, size_t size, RoomConfig* out) {
  if (size < ROOM_CONFIG_SIZE) return 0;
  std::memcpy(out, buf, ROOM_CONFIG_SIZE);
  return ROOM_CONFIG_SIZE;
}

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_LOBBY_PROTOCOL_HPP
