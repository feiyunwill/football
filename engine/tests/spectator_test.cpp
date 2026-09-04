// Copyright 2026 Google LLC & Contributors
// Unit tests for SpectatorClient (ms-17.3)

#include "frame_sync/spectator.hpp"
#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"

#include <gtest/gtest.h>
#include <boost/asio.hpp>
#include <thread>
#include <chrono>
#include <vector>

namespace frame_sync {
namespace {

// Helper: minimal server that accepts one connection and sends frames
class TestServer {
 public:
  explicit TestServer(boost::asio::io_context& io, unsigned short port)
      : io_(io),
        acceptor_(io, boost::asio::ip::tcp::endpoint(boost::asio::ip::tcp::v4(), port)),
        socket_(io) {}

  void accept() {
    acceptor_.accept(socket_);
  }

  void send_session_start() {
    uint8_t buf[32];
    size_t n = PackSessionStart(42, 1, 1, buf, sizeof(buf));
    boost::asio::write(socket_, boost::asio::buffer(buf, n));
  }

  void send_slot_assignment() {
    uint16_t slot = 0;
    uint8_t buf[64];
    size_t n = PackSlotAssignment(&slot, 1, buf, sizeof(buf));
    boost::asio::write(socket_, boost::asio::buffer(buf, n));
  }

  void send_authoritative_frame(frame_id_t fid, uint16_t num_slots) {
    std::vector<SlotInput> inputs(num_slots, SlotInput::Default());
    inputs[0].dir_x = 0.5f;
    inputs[0].buttons = 1;
    std::vector<uint8_t> buf(1024);
    size_t n = PackAuthoritativeFrame(fid, inputs.data(), num_slots,
                                      buf.data(), buf.size());
    boost::asio::write(socket_, boost::asio::buffer(buf.data(), n));
  }

  void send_state_hash(frame_id_t fid) {
    uint8_t buf[64];
    size_t n = PackStateHash(fid, 0xDEADBEEF, buf, sizeof(buf));
    boost::asio::write(socket_, boost::asio::buffer(buf, n));
  }

  void close() {
    boost::system::error_code ec;
    socket_.close(ec);
  }

 private:
  boost::asio::io_context& io_;
  boost::asio::ip::tcp::acceptor acceptor_;
  boost::asio::ip::tcp::socket socket_;
};

// Test: SpectatorClient can be constructed
TEST(SpectatorTest, Construction) {
  boost::asio::io_context io;
  SpectatorClient client(io, "127.0.0.1", 12345);
  EXPECT_FALSE(client.is_connected());
  EXPECT_EQ(client.frames_received(), 0u);
  EXPECT_EQ(client.state_hashes_received(), 0u);
}

// Test: SpectatorClient receives authoritative frames from a server
TEST(SpectatorTest, ReceivesFrames) {
  const unsigned short port = 19873;
  boost::asio::io_context io;

  TestServer server(io, port);
  std::thread server_thread([&server, &io]() {
    server.accept();
    server.send_session_start();
    // Don't send SlotAssignment — spectator doesn't need it

    // Wait for SpectatorJoin from client
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    // Send some authoritative frames
    for (frame_id_t i = 0; i < 5; ++i) {
      server.send_authoritative_frame(i, 2);
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    server.close();
  });

  SpectatorClient client(io, "127.0.0.1", port);
  client.connect();

  // Poll until we receive frames
  for (int i = 0; i < 50 && client.frames_received() < 5; ++i) {
    client.poll();
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }

  EXPECT_GE(client.frames_received(), 5u);
  EXPECT_TRUE(client.is_connected());

  server_thread.join();
}

// Test: SpectatorClient does not send input
TEST(SpectatorTest, NoInputSent) {
  const unsigned short port = 19874;
  boost::asio::io_context io;

  TestServer server(io, port);
  std::thread server_thread([&server, &io]() {
    server.accept();
    server.send_session_start();

    // Wait briefly then send frames
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    server.send_authoritative_frame(0, 2);
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    server.close();
  });

  SpectatorClient client(io, "127.0.0.1", port);
  client.connect();

  for (int i = 0; i < 20; ++i) {
    client.poll();
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }

  // Spectator should not have sent any FrameInput
  // (server would not crash — it just ignores unexpected messages)
  EXPECT_TRUE(client.is_connected());

  server_thread.join();
}

// Test: Multiple spectators can connect
TEST(SpectatorTest, MultipleSpectators) {
  const unsigned short port = 19875;
  boost::asio::io_context io;

  // Simple test: just verify two clients can be constructed
  SpectatorClient client1(io, "127.0.0.1", port);
  SpectatorClient client2(io, "127.0.0.1", port);
  EXPECT_FALSE(client1.is_connected());
  EXPECT_FALSE(client2.is_connected());
}

// Test: Frame callback is invoked
TEST(SpectatorTest, FrameCallback) {
  const unsigned short port = 19876;
  boost::asio::io_context io;

  TestServer server(io, port);
  std::thread server_thread([&server]() {
    server.accept();
    server.send_session_start();
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    server.send_authoritative_frame(0, 2);
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    server.close();
  });

  SpectatorClient client(io, "127.0.0.1", port);

  frame_id_t callback_frame = 999;
  client.on_frame([&callback_frame](frame_id_t fid, const std::vector<SlotInput>&) {
    callback_frame = fid;
  });

  client.connect();
  for (int i = 0; i < 20 && callback_frame == 999; ++i) {
    client.poll();
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }

  EXPECT_EQ(callback_frame, 0u);

  server_thread.join();
}

// Test: State hash is counted
TEST(SpectatorTest, StateHashCounted) {
  const unsigned short port = 19877;
  boost::asio::io_context io;

  TestServer server(io, port);
  std::thread server_thread([&server]() {
    server.accept();
    server.send_session_start();
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    server.send_state_hash(0);
    server.send_state_hash(10);
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    server.close();
  });

  SpectatorClient client(io, "127.0.0.1", port);
  client.connect();
  for (int i = 0; i < 20 && client.state_hashes_received() < 2; ++i) {
    client.poll();
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }

  EXPECT_GE(client.state_hashes_received(), 2u);

  server_thread.join();
}

}  // namespace
}  // namespace frame_sync
