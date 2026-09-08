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
  EXPECT_EQ(static_cast<uint8_t>(LobbyMessageType::RoomCreated), 10);
  EXPECT_EQ(static_cast<uint8_t>(LobbyMessageType::RoomListResponse), 11);
  EXPECT_EQ(static_cast<uint8_t>(LobbyMessageType::Error), 20);
}

}  // namespace
}  // namespace frame_sync
