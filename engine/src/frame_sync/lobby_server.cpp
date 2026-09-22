// Copyright 2026 Google LLC & Contributors
// 2026-09-09: implementation moved to lobby_server.hpp so tests use the real server.
#include "frame_sync/lobby_server.hpp"
#include <csignal>

int main(int argc, char* argv[]) {
  const unsigned short port = argc > 1 ? static_cast<unsigned short>(std::stoi(argv[1])) : 12346;
  boost::asio::io_context io;
  frame_sync::LobbyServer server(io, port);
  boost::asio::signal_set signals(io, SIGINT, SIGTERM);
  signals.async_wait([&](auto, auto) { server.stop(); });
  std::println("Lobby server listening on {}", server.port());
  io.run();
}
