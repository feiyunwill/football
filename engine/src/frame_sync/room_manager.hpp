// Copyright 2026 Google LLC & Contributors
// Room Manager for lobby system (ms-18.2).
// Manages room lifecycle: create, join, leave, list, ready state.
//
// This is a pure logic class with no network dependencies.

#ifndef GFOOTBALL_FRAME_SYNC_ROOM_MANAGER_HPP
#define GFOOTBALL_FRAME_SYNC_ROOM_MANAGER_HPP

#include "frame_sync/lobby_protocol.hpp"

#include <cstdint>
#include <functional>
#include <random>
#include <string>
#include <unordered_map>
#include <vector>

namespace frame_sync {

/// @brief Player session within a room
struct PlayerSession {
  std::string name;
  bool ready = false;
  bool is_host = false;
};

/// @brief Room state
struct RoomState {
  RoomMetadata meta;
  std::vector<PlayerSession> players;
  std::vector<std::string> spectators;

  [[nodiscard]] bool IsFull() const {
    return players.size() >= meta.max_players;
  }

  [[nodiscard]] bool HasPlayer(const std::string& name) const {
    for (const auto& p : players) {
      if (p.name == name) return true;
    }
    return false;
  }

  [[nodiscard]] bool AllReady() const {
    if (players.empty()) return false;
    for (const auto& p : players) {
      if (!p.ready && !p.is_host) return false;  // Host doesn't need to ready up
    }
    return true;
  }

  [[nodiscard]] const PlayerSession* GetHost() const {
    for (const auto& p : players) {
      if (p.is_host) return &p;
    }
    return nullptr;
  }
};

/// @brief Room manager — pure logic, no networking
class RoomManager {
 public:
  using RoomChangeCallback = std::move_only_function<void(uint32_t room_id, const RoomMetadata&)>;

  RoomManager() {
    rng_.seed(std::random_device{}());
  }

  /// @brief Create a new room
  /// @return room_id, or 0 on error
  uint32_t CreateRoom(const RoomConfig& config, const std::string& host_name) {
    uint32_t room_id = GenerateRoomId();

    RoomState room;
    room.meta.room_id = room_id;
    std::strncpy(room.meta.name, config.name, sizeof(room.meta.name));
    std::strncpy(room.meta.scenario, config.scenario, sizeof(room.meta.scenario));
    room.meta.seed = config.seed == 0 ? rng_() : config.seed;
    room.meta.max_players = config.max_players;
    room.meta.player_count = 1;
    room.meta.status = RoomStatus::kWaiting;

    PlayerSession host;
    host.name = host_name;
    host.ready = true;  // Host is always ready
    host.is_host = true;
    room.players.push_back(std::move(host));

    rooms_[room_id] = std::move(room);
    NotifyChange(room_id);
    return room_id;
  }

  /// @brief Join an existing room
  /// @return true on success
  bool JoinRoom(uint32_t room_id, const std::string& player_name) {
    auto it = rooms_.find(room_id);
    if (it == rooms_.end()) return false;
    auto& room = it->second;

    if (room.meta.status != RoomStatus::kWaiting) return false;
    if (room.IsFull()) return false;
    if (room.HasPlayer(player_name)) return false;

    PlayerSession player;
    player.name = player_name;
    player.ready = false;
    player.is_host = false;
    room.players.push_back(std::move(player));
    room.meta.player_count = static_cast<uint16_t>(room.players.size());

    NotifyChange(room_id);
    return true;
  }

  /// @brief Leave a room
  /// @return true on success
  bool LeaveRoom(uint32_t room_id, const std::string& player_name) {
    auto it = rooms_.find(room_id);
    if (it == rooms_.end()) return false;
    auto& room = it->second;

    auto& players = room.players;
    for (auto pit = players.begin(); pit != players.end(); ++pit) {
      if (pit->name == player_name) {
        bool was_host = pit->is_host;
        players.erase(pit);
        room.meta.player_count = static_cast<uint16_t>(players.size());

        // If host left, assign new host or remove room
        if (was_host) {
          if (players.empty()) {
            rooms_.erase(it);
            NotifyChange(room_id);
            return true;
          }
          players[0].is_host = true;
          players[0].ready = true;
        }

        NotifyChange(room_id);
        return true;
      }
    }
    return false;
  }

  /// @brief Set player ready state
  bool SetReady(uint32_t room_id, const std::string& player_name, bool ready) {
    auto it = rooms_.find(room_id);
    if (it == rooms_.end()) return false;
    auto& room = it->second;

    for (auto& p : room.players) {
      if (p.name == player_name) {
        p.ready = ready;
        NotifyChange(room_id);
        return true;
      }
    }
    return false;
  }

  /// @brief Start the game (host only)
  /// @return true on success
  bool StartGame(uint32_t room_id, const std::string& host_name,
                 const std::string& game_address, uint16_t game_port) {
    auto it = rooms_.find(room_id);
    if (it == rooms_.end()) return false;
    auto& room = it->second;

    // Only host can start
    const PlayerSession* host = room.GetHost();
    if (!host || host->name != host_name) return false;

    // Need at least 2 players
    if (room.players.size() < 2) return false;

    // All non-host players must be ready
    if (!room.AllReady()) return false;

    room.meta.status = RoomStatus::kPlaying;
    std::strncpy(room.meta.game_address, game_address.c_str(),
                 sizeof(room.meta.game_address));
    room.meta.game_port = game_port;

    NotifyChange(room_id);
    return true;
  }

  /// @brief Get room metadata
  [[nodiscard]] const RoomMetadata* GetRoomMetadata(uint32_t room_id) const {
    auto it = rooms_.find(room_id);
    if (it == rooms_.end()) return nullptr;
    return &it->second.meta;
  }

  /// @brief Get room state
  [[nodiscard]] const RoomState* GetRoom(uint32_t room_id) const {
    auto it = rooms_.find(room_id);
    if (it == rooms_.end()) return nullptr;
    return &it->second;
  }

  /// @brief List all rooms
  [[nodiscard]] std::vector<RoomMetadata> ListRooms() const {
    std::vector<RoomMetadata> result;
    for (const auto& [id, room] : rooms_) {
      result.push_back(room.meta);
    }
    return result;
  }

  /// @brief Get room by player name
  [[nodiscard]] uint32_t FindRoomByPlayer(const std::string& name) const {
    for (const auto& [id, room] : rooms_) {
      if (room.HasPlayer(name)) return id;
    }
    return 0;
  }

  /// @brief Get total room count
  [[nodiscard]] size_t RoomCount() const { return rooms_.size(); }

  /// @brief Remove finished rooms
  void Cleanup() {
    for (auto it = rooms_.begin(); it != rooms_.end();) {
      if (it->second.meta.status == RoomStatus::kFinished) {
        it = rooms_.erase(it);
      } else {
        ++it;
      }
    }
  }

 private:
  uint32_t GenerateRoomId() {
    std::uniform_int_distribution<uint32_t> dist(1, UINT32_MAX);
    uint32_t id;
    do {
      id = dist(rng_);
    } while (rooms_.count(id) > 0);
    return id;
  }

  void NotifyChange(uint32_t room_id) {
    if (change_cb_) {
      auto it = rooms_.find(room_id);
      if (it != rooms_.end()) {
        change_cb_(room_id, it->second.meta);
      }
    }
  }

  std::unordered_map<uint32_t, RoomState> rooms_;
  std::mt19937 rng_;
  RoomChangeCallback change_cb_;
};

}  // namespace frame_sync

#endif  // GFOOTBALL_FRAME_SYNC_ROOM_MANAGER_HPP
