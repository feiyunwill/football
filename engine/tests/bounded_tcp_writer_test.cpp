// 2026-09-09: actual TCP backpressure, retention through cancellation, and drain.
#include "frame_sync/bounded_tcp_writer.hpp"
#include <gtest/gtest.h>
#include <array>
#include <atomic>
#include <thread>

namespace {
namespace asio = boost::asio;
namespace fs = frame_sync;
using tcp = asio::ip::tcp;
using namespace std::chrono_literals;

struct Pair {
  std::shared_ptr<tcp::socket> sender;
  tcp::socket reader;
  explicit Pair(asio::io_context& io) : sender(std::make_shared<tcp::socket>(io)), reader(io) {
    tcp::acceptor acceptor(io, {asio::ip::address_v4::loopback(), 0});
    reader.connect(acceptor.local_endpoint());
    acceptor.accept(*sender);
    sender->set_option(asio::socket_base::send_buffer_size(4096));
    reader.set_option(asio::socket_base::receive_buffer_size(4096));
    reader.non_blocking(true);
  }
  ~Pair() = default;
  Pair(const Pair&) = delete;
  Pair& operator=(const Pair&) = delete;
  Pair(Pair&&) = delete;
  Pair& operator=(Pair&&) = delete;
};

void Pump(asio::io_context& io, std::chrono::milliseconds duration = 10ms) {
  io.restart();
  io.run_for(duration);
}
std::string Read(asio::io_context& io, tcp::socket& reader, size_t bytes) {
  std::string received;
  auto deadline = std::chrono::steady_clock::now() + 2s;
  while (received.size() < bytes && std::chrono::steady_clock::now() < deadline) {
    Pump(io, 1ms);
    std::array<char, 4096> buffer{};
    boost::system::error_code ec;
    auto n = reader.read_some(asio::buffer(buffer.data(), std::min(buffer.size(), bytes - received.size())), ec);
    if (!ec) received.append(buffer.data(), n);
    else if (ec != asio::error::would_block && ec != asio::error::try_again) {
      ADD_FAILURE() << ec.message();
      break;
    }
  }
  EXPECT_EQ(received.size(), bytes);
  Pump(io, 1ms);
  return received;
}

TEST(BoundedTCP, ValidatesBudgetsAndInvalidMessagesBeforeCopy) {
  asio::io_context io;
  Pair pair(io);
  EXPECT_THROW(fs::StreamBudget(0, 10), std::invalid_argument);
  EXPECT_THROW(fs::StreamBudget(1025, 10), std::invalid_argument);
  EXPECT_THROW(fs::StreamBudget(1, 0), std::invalid_argument);
  EXPECT_THROW(fs::StreamBudget(1, size_t(-1)), std::invalid_argument);
  EXPECT_THROW(fs::BoundedTCPWriter(nullptr), std::invalid_argument);
  EXPECT_THROW((fs::BoundedTCPWriter(pair.sender, fs::StreamBudget{}, 0ms)), std::invalid_argument);
  fs::StreamBudget altered;
  altered.message_limit = 0;
  EXPECT_THROW((fs::BoundedTCPWriter(pair.sender, altered)), std::invalid_argument);
  fs::BoundedTCPWriter writer(pair.sender);
  char data = 'a';
  EXPECT_FALSE(writer.TrySend(nullptr, 1));
  EXPECT_FALSE(writer.TrySend(&data, 0));
  EXPECT_EQ(writer.status(), fs::StreamStatus::InvalidMessage);
  EXPECT_FALSE(writer.TrySend(&data, size_t(-1)));
  EXPECT_EQ(writer.queued_bytes(), 0u);
  EXPECT_EQ(writer.queued_messages(), 0u);
}

TEST(BoundedTCP, CountLimitCopiesCallerBytesThenDrainsInOrderAndRecovers) {
  asio::io_context io;
  Pair pair(io);
  fs::BoundedTCPWriter writer(pair.sender, fs::StreamBudget(2, 64));
  std::vector<uint8_t> caller{'a', 'b', 'c'};
  caller.reserve(1024 * 1024);
  ASSERT_TRUE(writer.TrySend(caller.data(), caller.size()));
  caller.assign(3, 'x');
  ASSERT_TRUE(writer.TrySend("def", 3));
  EXPECT_EQ(writer.queued_bytes(), 6u);
  EXPECT_EQ(writer.queued_messages(), 2u);
  EXPECT_FALSE(writer.TrySend("ignored", 7));
  EXPECT_EQ(writer.status(), fs::StreamStatus::Capacity);
  EXPECT_EQ(Read(io, pair.reader, 6), "abcdef");
  EXPECT_EQ(writer.queued_bytes(), 0u);
  EXPECT_EQ(writer.queued_messages(), 0u);
  ASSERT_TRUE(writer.TrySend("gh", 2));
  EXPECT_EQ(Read(io, pair.reader, 2), "gh");
  EXPECT_EQ(writer.status(), fs::StreamStatus::Ready);
}

TEST(BoundedTCP, ByteLimitAppliesBeforeExecutorRunsAndAfterRepeatedDrain) {
  asio::io_context io;
  Pair pair(io);
  fs::BoundedTCPWriter writer(pair.sender, fs::StreamBudget(100, 10));
  for (unsigned cycle = 0; cycle < 100; ++cycle) {
    ASSERT_TRUE(writer.TrySend("012345", 6));
    ASSERT_TRUE(writer.TrySend("6789", 4));
    EXPECT_EQ(writer.queued_bytes(), 10u);
    EXPECT_FALSE(writer.TrySend("x", 1));
    EXPECT_EQ(Read(io, pair.reader, 10), "0123456789");
    EXPECT_EQ(writer.queued_bytes(), 0u);
  }
}

TEST(BoundedTCP, CloseBeforeDispatchDropsQueuedDataWithoutSending) {
  asio::io_context io;
  Pair pair(io);
  fs::BoundedTCPWriter writer(pair.sender);
  ASSERT_TRUE(writer.TrySend("a", 1));
  writer.Close();
  writer.Close();
  EXPECT_EQ(writer.queued_bytes(), 0u);
  EXPECT_EQ(writer.queued_messages(), 0u);
  EXPECT_FALSE(writer.TrySend("b", 1));
  Pump(io);
  EXPECT_FALSE(pair.sender->is_open());
  char byte;
  boost::system::error_code ec;
  // 2026-09-09: close completion does not imply remote FIN is already visible.
  // EXPECT_EQ(pair.reader.read_some(asio::buffer(&byte, 1), ec), 0u);
  const auto deadline = std::chrono::steady_clock::now() + 1s;
  do {
    EXPECT_EQ(pair.reader.read_some(asio::buffer(&byte, 1), ec), 0u);
    if (ec != asio::error::would_block && ec != asio::error::try_again) break;
    std::this_thread::sleep_for(1ms);
  } while (std::chrono::steady_clock::now() < deadline);
  EXPECT_EQ(ec, asio::error::eof);
}

TEST(BoundedTCP, CancelKeepsInFlightStorageUntilItsCallbackCompletes) {
  asio::io_context io;
  Pair pair(io);
  fs::BoundedTCPWriter writer(pair.sender, fs::StreamBudget(2, 8 * 1024 * 1024));
  const std::vector<uint8_t> payload(4 * 1024 * 1024, 0x52);
  ASSERT_TRUE(writer.TrySend(payload.data(), payload.size()));
  ASSERT_TRUE(writer.TrySend(payload.data(), payload.size()));
  Pump(io);
  ASSERT_EQ(writer.queued_messages(), 2u);
  writer.Close();
  EXPECT_EQ(writer.queued_bytes(), payload.size());
  EXPECT_EQ(writer.queued_messages(), 1u);
  Pump(io, 100ms);
  EXPECT_EQ(writer.queued_bytes(), 0u);
  EXPECT_EQ(writer.queued_messages(), 0u);
  EXPECT_EQ(writer.status(), fs::StreamStatus::Closed);
}

TEST(BoundedTCP, SlowReaderCannotBlockAnotherConnectionAndHasWriteDeadline) {
  asio::io_context io;
  Pair slow(io), healthy(io);
  fs::BoundedTCPWriter blocked(slow.sender, fs::StreamBudget(2, 8 * 1024 * 1024), 200ms);
  fs::BoundedTCPWriter working(healthy.sender);
  const std::vector<uint8_t> payload(4 * 1024 * 1024, 7);
  ASSERT_TRUE(blocked.TrySend(payload.data(), payload.size()));
  ASSERT_TRUE(blocked.TrySend(payload.data(), payload.size()));
  ASSERT_TRUE(working.TrySend("healthy", 7));
  Pump(io, 20ms);
  EXPECT_FALSE(blocked.is_closed());
  EXPECT_EQ(Read(io, healthy.reader, 7), "healthy");
  EXPECT_FALSE(working.is_closed());
  Pump(io, 300ms);
  EXPECT_TRUE(blocked.is_closed());
  EXPECT_EQ(blocked.status(), fs::StreamStatus::WriteTimeout);
  EXPECT_EQ(blocked.queued_bytes(), 0u);
  ASSERT_TRUE(working.TrySend("next", 4));
  EXPECT_EQ(Read(io, healthy.reader, 4), "next");
}

TEST(BoundedTCP, PeerResetReleasesAcceptedMessages) {
  asio::io_context io;
  Pair pair(io);
  fs::BoundedTCPWriter writer(pair.sender);
  pair.reader.set_option(asio::socket_base::linger(true, 0));
  pair.reader.close();
  // 2026-09-09: tiny writes can complete before the asynchronous reset arrives.
  // ASSERT_TRUE(writer.TrySend("one", 3));
  // ASSERT_TRUE(writer.TrySend("two", 3));
  const std::vector<uint8_t> payload(256 * 1024, 1);
  ASSERT_TRUE(writer.TrySend(payload.data(), payload.size()));
  ASSERT_TRUE(writer.TrySend(payload.data(), payload.size()));
  Pump(io, 100ms);
  EXPECT_TRUE(writer.is_closed());
  EXPECT_EQ(writer.status(), fs::StreamStatus::IoError);
  EXPECT_EQ(writer.queued_bytes(), 0u);
}

TEST(BoundedTCP, ReadIsBoundedAndCallbackCanSendWithoutReenteringMutex) {
  asio::io_context io;
  Pair pair(io);
  fs::BoundedTCPWriter writer(pair.sender);
  auto bytes = std::make_shared<std::array<char, 8>>();
  unsigned callbacks = 0;
  ASSERT_TRUE(writer.AsyncReadSome(asio::buffer(*bytes), [&, bytes](boost::system::error_code ec, size_t length) {
    EXPECT_FALSE(ec);
    EXPECT_EQ(std::string(bytes->data(), length), "read");
    ++callbacks;
    EXPECT_TRUE(writer.TrySend("reply", 5));
  }));
  EXPECT_FALSE(writer.AsyncReadSome(asio::buffer(*bytes), [](auto, auto) {}));
  pair.reader.write_some(asio::buffer("read", 4));
  EXPECT_EQ(Read(io, pair.reader, 5), "reply");
  EXPECT_EQ(callbacks, 1u);
  ASSERT_TRUE(writer.AsyncReadSome(asio::buffer(*bytes), [&, bytes](boost::system::error_code ec, size_t length) {
    EXPECT_EQ(ec, asio::error::operation_aborted);
    EXPECT_EQ(length, 0u);
    ++callbacks;
  }));
  writer.Close();
  Pump(io);
  EXPECT_EQ(callbacks, 2u);
}

TEST(BoundedTCP, DestructionCancelsWriteAndReleasesOwnedSocketAfterCompletion) {
  asio::io_context io;
  Pair pair(io);
  auto writer = std::make_unique<fs::BoundedTCPWriter>(pair.sender,
                                                     fs::StreamBudget(2, 8 * 1024 * 1024));
  const std::vector<uint8_t> payload(4 * 1024 * 1024, 9);
  ASSERT_TRUE(writer->TrySend(payload.data(), payload.size()));
  Pump(io);
  ASSERT_NE(writer->queued_bytes(), 0u);
  std::weak_ptr<tcp::socket> socket = pair.sender;
  pair.sender.reset();
  writer.reset();
  Pump(io, 100ms);
  EXPECT_TRUE(socket.expired());
}

TEST(BoundedTCP, ConcurrentProducersCannotQueueUnboundedExecutorWork) {
  asio::io_context io;
  Pair pair(io);
  fs::BoundedTCPWriter writer(pair.sender, fs::StreamBudget(128, 128));
  std::atomic<unsigned> accepted{0};
  std::array<std::thread, 4> producers;
  for (auto& producer : producers) producer = std::thread([&] {
    for (unsigned message = 0; message < 100; ++message)
      if (writer.TrySend("a", 1)) ++accepted;
  });
  for (auto& producer : producers) producer.join();
  EXPECT_EQ(accepted, 128u);
  EXPECT_EQ(writer.queued_messages(), 128u);
  EXPECT_EQ(writer.queued_bytes(), 128u);
  EXPECT_EQ(Read(io, pair.reader, 128), std::string(128, 'a'));
  EXPECT_EQ(writer.queued_bytes(), 0u);
}
}  // namespace
