// Copyright 2026 Google LLC & Contributors
// Unit tests for RoomManager (ms-18.2)

#include "frame_sync/room_manager.hpp"

#include <gtest/gtest.h>
#include <string>

namespace frame_sync {
namespace {

RoomConfig MakeConfig(const char* name = "Test Room",
                      const char* scenario = "academy_empty_goal_close",
                      uint16_t max_players = 4) {
  RoomConfig c{};
  std::strncpy(c.name, name, sizeof(c.name));
  std::strncpy(c.scenario, scenario, sizeof(c.scenario));
  c.seed = 42;
  c.max_players = max_players;
  c.allow_spectators = true;
  return c;
}

TEST(RoomManagerTest, CreateRoom) {
  RoomManager mgr;
  auto config = MakeConfig();
  uint32_t id = mgr.CreateRoom(config, "Alice");

  EXPECT_NE(id, 0u);
  EXPECT_EQ(mgr.RoomCount(), 1u);

  const auto* meta = mgr.GetRoomMetadata(id);
  ASSERT_NE(meta, nullptr);
  EXPECT_STREQ(meta->name, "Test Room");
  EXPECT_EQ(meta->player_count, 1);
  EXPECT_EQ(meta->status, RoomStatus::kWaiting);
}

TEST(RoomManagerTest, JoinRoom) {
  RoomManager mgr;
  uint32_t id = mgr.CreateRoom(MakeConfig(), "Alice");

  EXPECT_TRUE(mgr.JoinRoom(id, "Bob"));
  const auto* meta = mgr.GetRoomMetadata(id);
  EXPECT_EQ(meta->player_count, 2);
}

TEST(RoomManagerTest, JoinRoom_Full) {
  RoomManager mgr;
  uint32_t id = mgr.CreateRoom(MakeConfig("Room", "scenario", 2), "Alice");

  EXPECT_TRUE(mgr.JoinRoom(id, "Bob"));
  EXPECT_FALSE(mgr.JoinRoom(id, "Charlie"));  // Room full
}

TEST(RoomManagerTest, JoinRoom_AlreadyIn) {
  RoomManager mgr;
  uint32_t id = mgr.CreateRoom(MakeConfig(), "Alice");

  EXPECT_FALSE(mgr.JoinRoom(id, "Alice"));  // Already in room
}

TEST(RoomManagerTest, JoinRoom_NotFound) {
  RoomManager mgr;
  EXPECT_FALSE(mgr.JoinRoom(999, "Alice"));
}

TEST(RoomManagerTest, LeaveRoom) {
  RoomManager mgr;
  uint32_t id = mgr.CreateRoom(MakeConfig(), "Alice");
  mgr.JoinRoom(id, "Bob");

  EXPECT_TRUE(mgr.LeaveRoom(id, "Bob"));
  const auto* meta = mgr.GetRoomMetadata(id);
  EXPECT_EQ(meta->player_count, 1);
}

TEST(RoomManagerTest, LeaveRoom_HostLeaves) {
  RoomManager mgr;
  uint32_t id = mgr.CreateRoom(MakeConfig(), "Alice");
  mgr.JoinRoom(id, "Bob");

  // Host leaves, Bob becomes host
  EXPECT_TRUE(mgr.LeaveRoom(id, "Alice"));
  const auto* room = mgr.GetRoom(id);
  ASSERT_NE(room, nullptr);
  EXPECT_EQ(room->players.size(), 1u);
  EXPECT_TRUE(room->players[0].is_host);
  EXPECT_EQ(room->players[0].name, "Bob");
}

TEST(RoomManagerTest, LeaveRoom_LastPlayerLeaves) {
  RoomManager mgr;
  uint32_t id = mgr.CreateRoom(MakeConfig(), "Alice");

  EXPECT_TRUE(mgr.LeaveRoom(id, "Alice"));
  EXPECT_EQ(mgr.RoomCount(), 0u);
}

TEST(RoomManagerTest, SetReady) {
  RoomManager mgr;
  uint32_t id = mgr.CreateRoom(MakeConfig(), "Alice");
  mgr.JoinRoom(id, "Bob");

  EXPECT_TRUE(mgr.SetReady(id, "Bob", true));
  const auto* room = mgr.GetRoom(id);
  ASSERT_NE(room, nullptr);
  EXPECT_TRUE(room->players[1].ready);
}

TEST(RoomManagerTest, StartGame_AllReady) {
  RoomManager mgr;
  uint32_t id = mgr.CreateRoom(MakeConfig(), "Alice");
  mgr.JoinRoom(id, "Bob");
  mgr.SetReady(id, "Bob", true);

  EXPECT_TRUE(mgr.StartGame(id, "Alice", "127.0.0.1", 12345));
  const auto* meta = mgr.GetRoomMetadata(id);
  EXPECT_EQ(meta->status, RoomStatus::kPlaying);
  EXPECT_STREQ(meta->game_address, "127.0.0.1");
  EXPECT_EQ(meta->game_port, 12345);
}

TEST(RoomManagerTest, StartGame_NotHost) {
  RoomManager mgr;
  uint32_t id = mgr.CreateRoom(MakeConfig(), "Alice");
  mgr.JoinRoom(id, "Bob");
  mgr.SetReady(id, "Bob", true);

  EXPECT_FALSE(mgr.StartGame(id, "Bob", "127.0.0.1", 12345));
}

TEST(RoomManagerTest, StartGame_NotAllReady) {
  RoomManager mgr;
  uint32_t id = mgr.CreateRoom(MakeConfig(), "Alice");
  mgr.JoinRoom(id, "Bob");
  // Bob not ready

  EXPECT_FALSE(mgr.StartGame(id, "Alice", "127.0.0.1", 12345));
}

TEST(RoomManagerTest, StartGame_NeedTwoPlayers) {
  RoomManager mgr;
  uint32_t id = mgr.CreateRoom(MakeConfig(), "Alice");

  // Only 1 player (host)
  EXPECT_FALSE(mgr.StartGame(id, "Alice", "127.0.0.1", 12345));
}

TEST(RoomManagerTest, ListRooms) {
  RoomManager mgr;
  mgr.CreateRoom(MakeConfig("Room A"), "Alice");
  mgr.CreateRoom(MakeConfig("Room B"), "Bob");

  auto rooms = mgr.ListRooms();
  EXPECT_EQ(rooms.size(), 2u);
}

TEST(RoomManagerTest, FindRoomByPlayer) {
  RoomManager mgr;
  uint32_t id = mgr.CreateRoom(MakeConfig(), "Alice");
  mgr.JoinRoom(id, "Bob");

  EXPECT_EQ(mgr.FindRoomByPlayer("Alice"), id);
  EXPECT_EQ(mgr.FindRoomByPlayer("Bob"), id);
  EXPECT_EQ(mgr.FindRoomByPlayer("Charlie"), 0u);
}

TEST(RoomManagerTest, JoinStartedRoom) {
  RoomManager mgr;
  uint32_t id = mgr.CreateRoom(MakeConfig(), "Alice");
  mgr.JoinRoom(id, "Bob");
  mgr.SetReady(id, "Bob", true);
  mgr.StartGame(id, "Alice", "127.0.0.1", 12345);

  // Can't join a room that's already playing
  EXPECT_FALSE(mgr.JoinRoom(id, "Charlie"));
}

TEST(RoomManagerTest, Cleanup) {
  RoomManager mgr;
  uint32_t id = mgr.CreateRoom(MakeConfig(), "Alice");
  mgr.JoinRoom(id, "Bob");
  mgr.SetReady(id, "Bob", true);
  mgr.StartGame(id, "Alice", "127.0.0.1", 12345);

  // Mark as finished
  auto* room = const_cast<RoomState*>(mgr.GetRoom(id));
  room->meta.status = RoomStatus::kFinished;

  mgr.Cleanup();
  EXPECT_EQ(mgr.RoomCount(), 0u);
}

}  // namespace
}  // namespace frame_sync
