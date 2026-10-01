// Copyright 2026 Google LLC & Contributors
// Lobby protocol and room metadata for multi-room system (ms-18.1).
// Defines message types and data structures for lobby operations.
//
// This is a pure header-only library with no network or server dependencies.

#ifndef GFOOTBALL_FRAME_SYNC_LOBBY_PROTOCOL_HPP
#define GFOOTBALL_FRAME_SYNC_LOBBY_PROTOCOL_HPP

#include <cstdint>
#include <cstddef>
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
  // 2026-09-09: length-prefix the address for TCP fragmentation/coalescing.
  // StartGame = 7,       // payload: room_id(4) (host only)
  StartGame = 7,       // room_id(4) + address_len(2) + host:port (host only)
  EndGame = 8,         // room_id(4), host confirms match completion

  // Server → Client
  RoomCreated = 10,    // payload: room_id(4)
  RoomListResponse = 11, // payload: room_count(2) + RoomMetadata[]
  RoomInfo = 12,       // payload: RoomMetadata
  ChatMessage = 13,    // payload: room_id(4) + sender_len(2) + sender + msg_len(2) + msg
  PlayerJoined = 14,   // payload: room_id(4) + player_name_len(2) + name
  PlayerLeft = 15,     // payload: room_id(4) + player_name_len(2) + name
  GameStarted = 16,    // payload: room_id(4) + game_host(32) + game_port(2)
  GameEnded = 17,      // payload: room_id(4), room is retired
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
inline constexpr size_t ROOM_ID_BYTES = 4;
// Version-1 lobby packets use fixed-width little-endian fields. Keep the
// original x86 packet lengths and reserved bytes for existing peers, while
// making the wire layout independent of C++ struct padding and host endian.
inline constexpr size_t ROOM_CONFIG_SIZE = 104;
inline constexpr size_t ROOM_METADATA_SIZE = 180;
namespace lobby_wire {
inline constexpr size_t kConfigSeed = 96;
inline constexpr size_t kConfigMaxPlayers = 100;
inline constexpr size_t kConfigAllowSpectators = 102;
inline constexpr size_t kMetadataSeed = 100;
inline constexpr size_t kMetadataMaxPlayers = 104;
inline constexpr size_t kMetadataPlayerCount = 106;
inline constexpr size_t kMetadataSpectatorCount = 108;
inline constexpr size_t kMetadataStatus = 110;
inline constexpr size_t kMetadataAddress = 111;
inline constexpr size_t kMetadataPort = 176;
}  // namespace lobby_wire

// ----- Serialization helpers -----

// Pack a uint32_t into buffer, return bytes written
inline size_t PackUint32(uint8_t* buf, uint32_t val) {
  if (!buf) return 0;
  for (size_t i = 0; i < ROOM_ID_BYTES; ++i)
    buf[i] = static_cast<uint8_t>(val >> (8 * i));
  return ROOM_ID_BYTES;
}

// Unpack a uint32_t from buffer, return bytes consumed
inline size_t UnpackUint32(const uint8_t* buf, size_t size, uint32_t* out) {
  if (!buf || !out || size < ROOM_ID_BYTES) return 0;
  uint32_t value = 0;
  for (size_t i = 0; i < ROOM_ID_BYTES; ++i)
    value |= static_cast<uint32_t>(buf[i]) << (8 * i);
  *out = value;
  return ROOM_ID_BYTES;
}

// Pack a uint16_t into buffer
inline size_t PackUint16(uint8_t* buf, uint16_t val) {
  if (!buf) return 0;
  buf[0] = static_cast<uint8_t>(val);
  buf[1] = static_cast<uint8_t>(val >> 8);
  return 2;
}

// Unpack a uint16_t from buffer
inline size_t UnpackUint16(const uint8_t* buf, size_t size, uint16_t* out) {
  if (!buf || !out || size < 2) return 0;
  *out = static_cast<uint16_t>(buf[0]) |
         static_cast<uint16_t>(static_cast<uint16_t>(buf[1]) << 8);
  return 2;
}

// Pack a string (length-prefixed: 2-byte length + data)
inline size_t PackString(uint8_t* buf, size_t buf_size, const std::string& str) {
  if (!buf || str.size() > UINT16_MAX) return 0;
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
  if (!buf || buf_size < ROOM_METADATA_SIZE) return 0;
  std::memset(buf, 0, ROOM_METADATA_SIZE);
  PackUint32(buf, room.room_id);
  std::memcpy(buf + 4, room.name, sizeof(room.name));
  std::memcpy(buf + 36, room.scenario, sizeof(room.scenario));
  PackUint32(buf + lobby_wire::kMetadataSeed, room.seed);
  PackUint16(buf + lobby_wire::kMetadataMaxPlayers, room.max_players);
  PackUint16(buf + lobby_wire::kMetadataPlayerCount, room.player_count);
  PackUint16(buf + lobby_wire::kMetadataSpectatorCount, room.spectator_count);
  buf[lobby_wire::kMetadataStatus] = static_cast<uint8_t>(room.status);
  std::memcpy(buf + lobby_wire::kMetadataAddress, room.game_address,
              sizeof(room.game_address));
  PackUint16(buf + lobby_wire::kMetadataPort, room.game_port);
  return ROOM_METADATA_SIZE;
}

inline size_t UnpackRoomMetadata(const uint8_t* buf, size_t size, RoomMetadata* out) {
  if (!buf || !out || size < ROOM_METADATA_SIZE) return 0;
  RoomMetadata room;
  UnpackUint32(buf, ROOM_ID_BYTES, &room.room_id);
  std::memcpy(room.name, buf + 4, sizeof(room.name));
  std::memcpy(room.scenario, buf + 36, sizeof(room.scenario));
  UnpackUint32(buf + lobby_wire::kMetadataSeed, ROOM_ID_BYTES, &room.seed);
  UnpackUint16(buf + lobby_wire::kMetadataMaxPlayers, 2, &room.max_players);
  UnpackUint16(buf + lobby_wire::kMetadataPlayerCount, 2, &room.player_count);
  UnpackUint16(buf + lobby_wire::kMetadataSpectatorCount, 2, &room.spectator_count);
  room.status = static_cast<RoomStatus>(buf[lobby_wire::kMetadataStatus]);
  std::memcpy(room.game_address, buf + lobby_wire::kMetadataAddress,
              sizeof(room.game_address));
  UnpackUint16(buf + lobby_wire::kMetadataPort, 2, &room.game_port);
  if (!std::memchr(room.name, 0, sizeof(room.name)) ||
      !std::memchr(room.scenario, 0, sizeof(room.scenario)) ||
      !std::memchr(room.game_address, 0, sizeof(room.game_address)) ||
      static_cast<uint8_t>(room.status) > static_cast<uint8_t>(RoomStatus::kFinished) ||
      room.max_players < 2 || room.max_players > 22 || room.player_count > room.max_players)
    return 0;
  *out = room;
  return ROOM_METADATA_SIZE;
}

// ----- Pack/Unpack RoomConfig -----
inline size_t PackRoomConfig(const RoomConfig& config, uint8_t* buf, size_t buf_size) {
  if (!buf || buf_size < ROOM_CONFIG_SIZE) return 0;
  std::memset(buf, 0, ROOM_CONFIG_SIZE);
  std::memcpy(buf, config.name, sizeof(config.name));
  std::memcpy(buf + 32, config.scenario, sizeof(config.scenario));
  PackUint32(buf + lobby_wire::kConfigSeed, config.seed);
  PackUint16(buf + lobby_wire::kConfigMaxPlayers, config.max_players);
  buf[lobby_wire::kConfigAllowSpectators] = config.allow_spectators ? 1 : 0;
  return ROOM_CONFIG_SIZE;
}

inline size_t UnpackRoomConfig(const uint8_t* buf, size_t size, RoomConfig* out) {
  if (!buf || !out || size < ROOM_CONFIG_SIZE) return 0;
  if (buf[lobby_wire::kConfigAllowSpectators] > 1) return 0;
  RoomConfig config;
  std::memcpy(config.name, buf, sizeof(config.name));
  std::memcpy(config.scenario, buf + 32, sizeof(config.scenario));
  UnpackUint32(buf + lobby_wire::kConfigSeed, ROOM_ID_BYTES, &config.seed);
  UnpackUint16(buf + lobby_wire::kConfigMaxPlayers, 2, &config.max_players);
  config.allow_spectators = buf[lobby_wire::kConfigAllowSpectators] == 1;
  if (!std::memchr(config.name, 0, sizeof(config.name)) ||
      !std::memchr(config.scenario, 0, sizeof(config.scenario))) return 0;
  *out = config;
  return ROOM_CONFIG_SIZE;
}

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_LOBBY_PROTOCOL_HPP
