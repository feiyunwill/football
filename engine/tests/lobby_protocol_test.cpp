// Copyright 2026 Google LLC & Contributors
// Unit tests for lobby protocol (ms-18.1)

#include "frame_sync/lobby_protocol.hpp"

#include <gtest/gtest.h>
#include <cstring>

namespace frame_sync {
namespace {

TEST(LobbyProtocolTest, PackUnpackUint32) {
  uint8_t buf[4];
  uint32_t val = 0xDEADBEEF;
  size_t n = PackUint32(buf, val);
  EXPECT_EQ(n, sizeof(uint32_t));
  EXPECT_EQ(buf[0], 0xEF);
  EXPECT_EQ(buf[1], 0xBE);
  EXPECT_EQ(buf[2], 0xAD);
  EXPECT_EQ(buf[3], 0xDE);

  uint32_t out = 0;
  size_t consumed = UnpackUint32(buf, sizeof(buf), &out);
  EXPECT_EQ(consumed, sizeof(uint32_t));
  EXPECT_EQ(out, val);
}

TEST(LobbyProtocolTest, PackUnpackUint16) {
  uint8_t buf[2];
  uint16_t val = 12345;
  size_t n = PackUint16(buf, val);
  EXPECT_EQ(n, sizeof(uint16_t));
  EXPECT_EQ(buf[0], 0x39);
  EXPECT_EQ(buf[1], 0x30);

  uint16_t out = 0;
  size_t consumed = UnpackUint16(buf, sizeof(buf), &out);
  EXPECT_EQ(consumed, sizeof(uint16_t));
  EXPECT_EQ(out, val);
}

TEST(LobbyProtocolTest, PackUnpackString) {
  uint8_t buf[128];
  std::string str = "Hello, World!";
  size_t n = PackString(buf, sizeof(buf), str);
  EXPECT_GT(n, sizeof(uint16_t));

  std::string out;
  size_t consumed = UnpackString(buf, sizeof(buf), &out);
  EXPECT_EQ(consumed, n);
  EXPECT_EQ(out, str);
}

TEST(LobbyProtocolTest, PackUnpackEmptyString) {
  uint8_t buf[128];
  std::string str;
  size_t n = PackString(buf, sizeof(buf), str);
  EXPECT_EQ(n, sizeof(uint16_t));

  std::string out;
  size_t consumed = UnpackString(buf, sizeof(buf), &out);
  EXPECT_EQ(consumed, n);
  EXPECT_TRUE(out.empty());
}

TEST(LobbyProtocolTest, ExplicitFixedRoomWireLayoutAndZeroReservedBytes) {
  RoomConfig config;
  std::strcpy(config.name, "Room");
  std::strcpy(config.scenario, "academy_empty_goal_close");
  config.seed = 0x12345678;
  config.max_players = 8;
  config.allow_spectators = false;
  std::array<uint8_t, ROOM_CONFIG_SIZE> config_bytes;
  config_bytes.fill(0xAA);
  ASSERT_EQ(PackRoomConfig(config, config_bytes.data(), config_bytes.size()),
            ROOM_CONFIG_SIZE);
  EXPECT_EQ(config_bytes[96], 0x78);
  EXPECT_EQ(config_bytes[97], 0x56);
  EXPECT_EQ(config_bytes[98], 0x34);
  EXPECT_EQ(config_bytes[99], 0x12);
  EXPECT_EQ(config_bytes[100], 8);
  EXPECT_EQ(config_bytes[101], 0);
  EXPECT_EQ(config_bytes[102], 0);
  EXPECT_EQ(config_bytes[103], 0);

  RoomMetadata room;
  room.room_id = 0x11223344;
  std::strcpy(room.name, "Room");
  std::strcpy(room.scenario, "academy_empty_goal_close");
  room.seed = 0x12345678;
  room.max_players = 8;
  room.player_count = 2;
  room.spectator_count = 1;
  room.status = RoomStatus::kPlaying;
  std::strcpy(room.game_address, "127.0.0.1:13330");
  room.game_port = 13330;
  std::array<uint8_t, ROOM_METADATA_SIZE> room_bytes;
  room_bytes.fill(0xAA);
  ASSERT_EQ(PackRoomMetadata(room, room_bytes.data(), room_bytes.size()),
            ROOM_METADATA_SIZE);
  EXPECT_EQ(room_bytes[0], 0x44);
  EXPECT_EQ(room_bytes[1], 0x33);
  EXPECT_EQ(room_bytes[2], 0x22);
  EXPECT_EQ(room_bytes[3], 0x11);
  EXPECT_EQ(room_bytes[100], 0x78);
  EXPECT_EQ(room_bytes[101], 0x56);
  EXPECT_EQ(room_bytes[102], 0x34);
  EXPECT_EQ(room_bytes[103], 0x12);
  EXPECT_EQ(room_bytes[110], static_cast<uint8_t>(RoomStatus::kPlaying));
  EXPECT_EQ(room_bytes[175], 0);
  EXPECT_EQ(room_bytes[176], 0x12);
  EXPECT_EQ(room_bytes[177], 0x34);
  EXPECT_EQ(room_bytes[178], 0);
  EXPECT_EQ(room_bytes[179], 0);

  RoomMetadata decoded;
  ASSERT_EQ(UnpackRoomMetadata(room_bytes.data(), room_bytes.size(), &decoded),
            ROOM_METADATA_SIZE);
  EXPECT_EQ(decoded.room_id, room.room_id);
  EXPECT_EQ(decoded.seed, room.seed);
  EXPECT_EQ(decoded.game_port, room.game_port);
}

TEST(LobbyProtocolTest, PackStringRejectsLengthOverflow) {
  std::array<uint8_t, 2> bytes{};
  EXPECT_EQ(PackString(bytes.data(), bytes.size(), std::string(65536, 'x')), 0);
}

TEST(LobbyProtocolTest, PackUnpackRoomMetadata) {
  RoomMetadata room;
  room.room_id = 42;
  std::strncpy(room.name, "Test Room", sizeof(room.name));
  std::strncpy(room.scenario, "academy_empty_goal_close", sizeof(room.scenario));
  room.seed = 12345;
  room.max_players = 4;
  room.player_count = 2;
  room.spectator_count = 1;
  room.status = RoomStatus::kWaiting;
  std::strncpy(room.game_address, "127.0.0.1", sizeof(room.game_address));
  room.game_port = 12345;

  uint8_t buf[512];
  size_t n = PackRoomMetadata(room, buf, sizeof(buf));
  EXPECT_EQ(n, ROOM_METADATA_SIZE);

  RoomMetadata out{};
  size_t consumed = UnpackRoomMetadata(buf, sizeof(buf), &out);
  EXPECT_EQ(consumed, ROOM_METADATA_SIZE);
  EXPECT_EQ(out.room_id, 42u);
  EXPECT_STREQ(out.name, "Test Room");
  EXPECT_STREQ(out.scenario, "academy_empty_goal_close");
  EXPECT_EQ(out.seed, 12345u);
  EXPECT_EQ(out.max_players, 4);
  EXPECT_EQ(out.player_count, 2);
  EXPECT_EQ(out.spectator_count, 1);
  EXPECT_EQ(out.status, RoomStatus::kWaiting);
  EXPECT_STREQ(out.game_address, "127.0.0.1");
  EXPECT_EQ(out.game_port, 12345);
}

TEST(LobbyProtocolTest, PackUnpackRoomConfig) {
  RoomConfig config;
  std::strncpy(config.name, "My Room", sizeof(config.name));
  std::strncpy(config.scenario, "11_vs_11_stochastic", sizeof(config.scenario));
  config.seed = 99;
  config.max_players = 4;
  config.allow_spectators = false;

  uint8_t buf[256];
  size_t n = PackRoomConfig(config, buf, sizeof(buf));
  EXPECT_EQ(n, ROOM_CONFIG_SIZE);

  RoomConfig out{};
  size_t consumed = UnpackRoomConfig(buf, sizeof(buf), &out);
  EXPECT_EQ(consumed, ROOM_CONFIG_SIZE);
  EXPECT_STREQ(out.name, "My Room");
  EXPECT_STREQ(out.scenario, "11_vs_11_stochastic");
  EXPECT_EQ(out.seed, 99u);
  EXPECT_EQ(out.max_players, 4);
  EXPECT_FALSE(out.allow_spectators);
}

TEST(LobbyProtocolTest, PackRoomMetadata_BufferTooSmall) {
  RoomMetadata room;
  uint8_t buf[10];
  size_t n = PackRoomMetadata(room, buf, sizeof(buf));
  EXPECT_EQ(n, 0u);
}

TEST(LobbyProtocolTest, UnpackRoomMetadata_BufferTooSmall) {
  uint8_t buf[10];
  RoomMetadata out{};
  size_t n = UnpackRoomMetadata(buf, sizeof(buf), &out);
  EXPECT_EQ(n, 0u);
}

TEST(LobbyProtocolTest, PackString_BufferTooSmall) {
  uint8_t buf[2];
  std::string str = "too long";
  size_t n = PackString(buf, sizeof(buf), str);
  EXPECT_EQ(n, 0u);
}

TEST(LobbyProtocolTest, RoomStatusValues) {
  EXPECT_EQ(static_cast<uint8_t>(RoomStatus::kWaiting), 0);
  EXPECT_EQ(static_cast<uint8_t>(RoomStatus::kPlaying), 1);
  EXPECT_EQ(static_cast<uint8_t>(RoomStatus::kFinished), 2);
}

TEST(LobbyProtocolTest, LobbyMessageTypeValues) {
  EXPECT_EQ(static_cast<uint8_t>(LobbyMessageType::CreateRoom), 0);
  EXPECT_EQ(static_cast<uint8_t>(LobbyMessageType::JoinRoom), 1);
  EXPECT_EQ(static_cast<uint8_t>(LobbyMessageType::RoomList), 3);
  EXPECT_EQ(static_cast<uint8_t>(LobbyMessageType::Chat), 4);
  EXPECT_EQ(static_cast<uint8_t>(LobbyMessageType::EndGame), 8);
  EXPECT_EQ(static_cast<uint8_t>(LobbyMessageType::RoomCreated), 10);
  EXPECT_EQ(static_cast<uint8_t>(LobbyMessageType::RoomListResponse), 11);
  EXPECT_EQ(static_cast<uint8_t>(LobbyMessageType::GameEnded), 17);
  EXPECT_EQ(static_cast<uint8_t>(LobbyMessageType::Error), 20);
}

// 2026-09-09: malformed wire values must not escape staged decoders.
TEST(LobbyProtocolTest, InvalidConfigRepresentationAndStringsPreserveOutput) {
  RoomConfig valid;
  valid.seed = 1;
  std::array<uint8_t, ROOM_CONFIG_SIZE> bytes;
  PackRoomConfig(valid, bytes.data(), bytes.size());
  RoomConfig output;
  output.seed = 987;
  bytes[offsetof(RoomConfig, allow_spectators)] = 2;
  EXPECT_EQ(UnpackRoomConfig(bytes.data(), bytes.size(), &output), 0u);
  EXPECT_EQ(output.seed, 987u);
  EXPECT_TRUE(output.allow_spectators);
  bytes[offsetof(RoomConfig, allow_spectators)] = 1;
  std::memset(bytes.data() + offsetof(RoomConfig, scenario), 'x', sizeof(valid.scenario));
  EXPECT_EQ(UnpackRoomConfig(bytes.data(), bytes.size(), &output), 0u);
  EXPECT_EQ(output.seed, 987u);
}
TEST(LobbyProtocolTest, InvalidMetadataFieldsPreserveOutput) {
  const auto reject = [](RoomMetadata invalid) {
    std::array<uint8_t, ROOM_METADATA_SIZE> bytes;
    PackRoomMetadata(invalid, bytes.data(), bytes.size());
    RoomMetadata output;
    output.room_id = 987;
    EXPECT_EQ(UnpackRoomMetadata(bytes.data(), bytes.size(), &output), 0u);
    EXPECT_EQ(output.room_id, 987u);
  };
  RoomMetadata room;
  room.status = static_cast<RoomStatus>(255); reject(room);
  room = {}; room.player_count = 3; reject(room);
  room = {}; room.max_players = 23; reject(room);
  room = {}; std::memset(room.game_address, 'x', sizeof(room.game_address)); reject(room);
}

}  // namespace
}  // namespace frame_sync
