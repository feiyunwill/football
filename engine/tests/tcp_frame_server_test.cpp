// 2026-09-09: use the same server implementation as the production executable.
#include "frame_sync/tcp_frame_server.hpp"
#include <gtest/gtest.h>
#include <thread>
namespace {
namespace asio = boost::asio;
namespace fs = frame_sync;
using tcp = asio::ip::tcp;
using namespace std::chrono_literals;
template<class Predicate> bool Until(Predicate predicate) {
  const auto deadline = std::chrono::steady_clock::now() + 3s;
  while (std::chrono::steady_clock::now() < deadline) {
    if (predicate()) return true;
    std::this_thread::sleep_for(1ms);
  }
  return false;
}
struct Harness {
  asio::io_context io, peers_io;
  fs::FrameSyncServer server;
  std::thread network, frames;
  Harness(uint16_t left = 1, uint16_t right = 1, fs::TCPFrameServerOptions options = {})
      : server(io, 0, left, right, 42, options), network([this] { io.run(); }) {}
  ~Harness() { server.stop(); if (frames.joinable()) frames.join(); network.join(); }
  void Start() { frames = std::thread([this] { server.run_frame_loop(); }); }
  std::unique_ptr<tcp::socket> Connect(int receive_bytes = 65536) {
    auto socket = std::make_unique<tcp::socket>(peers_io);
    socket->open(tcp::v4());
    socket->set_option(asio::socket_base::receive_buffer_size(receive_bytes));
    socket->connect({asio::ip::address_v4::loopback(), server.port()});
    return socket;
  }
};
bool Read(tcp::socket& socket, std::vector<uint8_t>& bytes, size_t count) {
  socket.non_blocking(true);
  return Until([&] {
    boost::system::error_code ec;
    std::array<uint8_t, 4096> buffer;
    auto length = socket.read_some(asio::buffer(buffer), ec);
    if (length) bytes.insert(bytes.end(), buffer.begin(), buffer.begin() + length);
    return bytes.size() >= count;
  });
}
bool Closed(tcp::socket& socket) {
  socket.non_blocking(true);
  return Until([&] {
    boost::system::error_code ec;
    std::array<uint8_t, 4096> buffer;
    socket.read_some(asio::buffer(buffer), ec);
    return ec == asio::error::eof || ec == asio::error::connection_reset;
  });
}
void Send(tcp::socket& socket, const std::vector<uint8_t>& bytes) {
  socket.non_blocking(false);
  asio::write(socket, asio::buffer(bytes));
}
std::vector<uint8_t> Input(fs::frame_id_t frame, uint16_t slot, fs::SlotInput input) {
  std::vector<uint8_t> bytes(7 + 2 + fs::SLOT_INPUT_BYTES);
  auto size = fs::PackClientFrameInput(frame, &slot, &input, 1, bytes.data(), bytes.size());
  if (size != bytes.size()) throw std::runtime_error("input fixture pack failed");
  return bytes;
}
TEST(TCPFrameServer, InvalidSlotsAndMutatedBudgetsFailBeforeClientAllocation) {
  asio::io_context io;
  EXPECT_THROW((fs::FrameSyncServer(io, 0, 0, 0, 42)), std::invalid_argument);
  EXPECT_THROW((fs::FrameSyncServer(io, 0, 12, 1, 42)), std::invalid_argument);
  fs::TCPFrameServerOptions options; options.send.byte_limit = 0;
  EXPECT_THROW((fs::FrameSyncServer(io, 0, 1, 1, 42, options)), std::invalid_argument);
  options = {}; options.frame_period = 0ms;
  EXPECT_THROW((fs::FrameSyncServer(io, 0, 1, 1, 42, options)), std::invalid_argument);
}
TEST(TCPFrameServer, FullConnectionsRejectAndRecoverBeforeMatchStarts) {
  Harness h;
  auto first = h.Connect(), second = h.Connect();
  ASSERT_TRUE(Until([&] { return h.server.stats().connections == 2; }));
  auto excess = h.Connect(); ASSERT_TRUE(Closed(*excess));
  EXPECT_EQ(h.server.stats().rejected_connections, 1u);
  first->close();
  ASSERT_TRUE(Until([&] { return h.server.stats().connections == 1; }));
  auto replacement = h.Connect();
  std::vector<uint8_t> handshake;
  ASSERT_TRUE(Read(*replacement, handshake, 14));
  ASSERT_EQ(handshake.size(), 14u);
  uint32_t seed; uint16_t left, right;
  ASSERT_EQ(fs::UnpackSessionStart(handshake.data(), 9, &seed, &left, &right), 9u);
  EXPECT_EQ(seed, 42u); EXPECT_EQ(left, 1); EXPECT_EQ(right, 1);
  std::vector<uint16_t> slots;
  ASSERT_EQ(fs::UnpackSlotAssignment(handshake.data() + 9, 5, &slots), 5u);
  ASSERT_EQ(slots.size(), 1u); EXPECT_EQ(slots[0], 0);
}
TEST(TCPFrameServer, UnreadyConnectionsExpireAndReleaseReservation) {
  fs::TCPFrameServerOptions options; options.ready_timeout = 100ms;
  Harness h(1, 1, options);
  auto peer = h.Connect(); ASSERT_TRUE(Closed(*peer));
  ASSERT_TRUE(Until([&] { return h.server.stats().connections == 0; }));
  EXPECT_EQ(h.server.stats().receive_capacity, 0u);
  EXPECT_EQ(h.server.stats().queued_send_bytes, 0u);
  auto replacement = h.Connect();
  ASSERT_TRUE(Until([&] { return h.server.stats().connections == 1; }));
}
TEST(TCPFrameServer, InvalidHeadersAndForeignSlotDisconnectWithoutGrowingBuffer) {
  Harness h;
  std::vector<std::vector<uint8_t>> packets{
    {std::to_underlying(fs::MessageType::Ready), std::to_underlying(fs::MessageType::FrameInput), 0, 0, 0, 0, 255, 255},
    {254}
  };
  auto foreign = Input(0, 5, fs::SlotInput::Default());
  foreign.insert(foreign.begin(), std::to_underlying(fs::MessageType::Ready)); packets.push_back(foreign);
  for (const auto& bytes : packets) {
    auto peer = h.Connect(); Send(*peer, bytes); ASSERT_TRUE(Closed(*peer));
    ASSERT_TRUE(Until([&] { return h.server.stats().connections == 0; }));
  }
  EXPECT_EQ(h.server.stats().invalid_messages, packets.size());
  EXPECT_EQ(h.server.stats().receive_capacity, 0u);
}
TEST(TCPFrameServer, FragmentedInputAndHeartbeatPreserveFrameAndSlotOrder) {
  fs::TCPFrameServerOptions options; options.input_timeout = 500ms;
  Harness h(1, 0, options);
  auto peer = h.Connect(); std::vector<uint8_t> handshake;
  ASSERT_TRUE(Read(*peer, handshake, 14));
  Send(*peer, {std::to_underlying(fs::MessageType::Ready)}); h.Start();
  ASSERT_TRUE(Until([&] { return h.server.stats().accepting_inputs; }));
  auto input = fs::SlotInput::Default(); input.dir_x = 0.5f; input.dir_y = -0.25f;
  auto bytes = Input(0, 0, input);
  Send(*peer, std::vector<uint8_t>(bytes.begin(), bytes.begin() + 6));
  EXPECT_EQ(h.server.stats().invalid_messages, 0u);
  Send(*peer, std::vector<uint8_t>(bytes.begin() + 6, bytes.end()));
  std::vector<uint8_t> authority;
  ASSERT_TRUE(Read(*peer, authority, 7 + fs::SLOT_INPUT_BYTES));
  fs::frame_id_t frame; std::vector<fs::SlotInput> decoded;
  ASSERT_EQ(fs::UnpackAuthoritativeFrame(authority.data(), authority.size(), &frame, &decoded), authority.size());
  EXPECT_EQ(frame, 0u); ASSERT_EQ(decoded.size(), 1u);
  EXPECT_FLOAT_EQ(decoded[0].dir_x, 0.5f); EXPECT_FLOAT_EQ(decoded[0].dir_y, -0.25f);
  ASSERT_TRUE(Until([&] { auto stats = h.server.stats(); return stats.next_frame == 1 && stats.accepting_inputs; }));
  std::vector<uint8_t> combined(fs::HEARTBEAT_PACK_BYTES);
  ASSERT_EQ(fs::PackHeartbeat(1, 0, combined.data(), combined.size()), combined.size());
  bytes = Input(1, 0, input); combined.insert(combined.end(), bytes.begin(), bytes.end()); Send(*peer, combined);
  authority.clear(); ASSERT_TRUE(Read(*peer, authority, 7 + fs::SLOT_INPUT_BYTES));
  ASSERT_GT(fs::UnpackAuthoritativeFrame(authority.data(), authority.size(), &frame, &decoded), 0u);
  EXPECT_EQ(frame, 1u); EXPECT_EQ(h.server.stats().invalid_messages, 0u);
}
TEST(TCPFrameServer, SlowReaderIsClosedWhileHealthyPeerReceivesConsecutiveFullFrames) {
  fs::TCPFrameServerOptions options;
  options.write_timeout = 100ms; options.input_timeout = 1ms; options.frame_period = 1ms;
  options.socket_send_bytes = 1024; options.send = fs::StreamBudget(256, 64 * 1024);
  Harness h(11, 11, options);
  auto slow = h.Connect(1024), healthy = h.Connect();
  std::vector<uint8_t> slow_handshake, healthy_handshake;
  ASSERT_TRUE(Read(*slow, slow_handshake, 14)); ASSERT_TRUE(Read(*healthy, healthy_handshake, 14));
  Send(*slow, {std::to_underlying(fs::MessageType::Ready)});
  Send(*healthy, {std::to_underlying(fs::MessageType::Ready)});
  ASSERT_TRUE(Until([&] { return h.server.all_ready(); })); h.Start();
  healthy->non_blocking(true);
  std::vector<uint8_t> buffer; size_t frames = 0; bool valid = true;
  const size_t frame_bytes = 7 + 22 * fs::SLOT_INPUT_BYTES;
  ASSERT_TRUE(Until([&] {
    std::array<uint8_t, 4096> bytes;
    boost::system::error_code ec;
    size_t length = healthy->read_some(asio::buffer(bytes), ec);
    if (ec && ec != asio::error::would_block && ec != asio::error::try_again) { valid = false; return true; }
    buffer.insert(buffer.end(), bytes.begin(), bytes.begin() + length);
    while (buffer.size() >= frame_bytes) {
      fs::frame_id_t frame; std::vector<fs::SlotInput> inputs;
      auto used = fs::UnpackAuthoritativeFrame(buffer.data(), frame_bytes, &frame, &inputs);
      if (used != frame_bytes || frame != frames || inputs.size() != 22) { valid = false; return true; }
      ++frames; buffer.erase(buffer.begin(), buffer.begin() + frame_bytes);
    }
    auto stats = h.server.stats();
    EXPECT_LE(stats.connections, 22u);
    EXPECT_LE(stats.queued_send_bytes, 2 * options.send.byte_limit);
    EXPECT_LE(stats.queued_send_messages, 2 * options.send.message_limit);
    return frames >= 200 && stats.active_connections == 1;
  }));
  EXPECT_TRUE(valid); EXPECT_GE(frames, 200u);
  auto stats = h.server.stats();
  EXPECT_EQ(stats.active_connections, 1u);
  EXPECT_EQ(stats.write_timeouts, 1u);
  EXPECT_EQ(stats.invalid_messages, 0u);
  EXPECT_EQ(stats.overloaded_connections, 0u);
  // No unbootstrapped client is admitted midway through the authority stream.
  auto late = h.Connect(); ASSERT_TRUE(Closed(*late));
  EXPECT_GE(h.server.stats().rejected_connections, 1u);
}
TEST(TCPFrameServer, StopWakesWaitingFrameLoopAndDrainsPendingSocketCallbacks) {
  Harness h;
  auto peer = h.Connect();
  h.Start();
  h.server.stop();
  h.frames.join();
  EXPECT_TRUE(Closed(*peer));
}
TEST(TCPFrameServer, WrapperDestructionWithLiveIoKeepsCallbacksSafe) {
  asio::io_context io, peer_io;
  auto server = std::make_unique<fs::FrameSyncServer>(io, 0, 1, 1, 42);
  const auto port = server->port();
  std::thread thread([&] { io.run(); });
  tcp::socket peer(peer_io); peer.connect({asio::ip::address_v4::loopback(), port});
  Send(peer, {std::to_underlying(fs::MessageType::Ready)});
  server.reset(); thread.join();
  EXPECT_TRUE(Closed(peer));
}
}  // namespace
