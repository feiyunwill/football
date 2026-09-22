// Copyright 2026 Google LLC & Contributors
// 2026-09-09: real datagrams, controlled time, and no-ACK capacity boundaries.
#include "frame_sync/reliable_udp.hpp"
#include <gtest/gtest.h>
#include <array>
#include <atomic>
#include <limits>
#include <thread>

namespace frame_sync {
namespace {
class DatagramTest : public ::testing::Test {
 protected:
  asio::io_context io;
  udp::socket sender{io, udp::endpoint(asio::ip::address_v4::loopback(), 0)};
  udp::socket receiver{io, udp::endpoint(asio::ip::address_v4::loopback(), 0)};
  ReliableUDPChannel::Clock::time_point now = ReliableUDPChannel::Clock::now();
  void SetUp() override {
    sender.non_blocking(true);
    receiver.non_blocking(true);
  }
  std::vector<uint8_t> Receive(udp::socket& socket) {
    std::vector<uint8_t> bytes(kReliableUDP_MaxPacketSize);
    udp::endpoint source;
    auto deadline = ReliableUDPChannel::Clock::now() + std::chrono::seconds(1);
    for (;;) {
      boost::system::error_code ec;
      auto count = socket.receive_from(asio::buffer(bytes), source, 0, ec);
      if (!ec) { bytes.resize(count); return bytes; }
      if (ec != asio::error::would_block && ec != asio::error::try_again) {
        ADD_FAILURE() << ec.message();
        return {};
      }
      if (ReliableUDPChannel::Clock::now() >= deadline) {
        ADD_FAILURE() << "Timed out waiting for local datagram";
        return {};
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
  }
  void Ack(ReliableUDPChannel& channel, const std::vector<uint8_t>& packet) {
    ASSERT_GE(packet.size(), kReliableUDP_HeaderSize);
    std::array<uint8_t, kReliableUDP_AckSize> ack{kReliableUDP_Ack};
    std::copy_n(packet.data() + 1, 4, ack.data() + 1);
    receiver.send_to(asio::buffer(ack), sender.local_endpoint());
    const auto arrived = Receive(sender);
    ASSERT_TRUE(channel.HandleReceived(arrived.data(), arrived.size()));
  }
  static uint32_t Sequence(const std::vector<uint8_t>& packet) {
    uint32_t seq = 0;
    for (unsigned i = 0; i < 4; ++i) seq |= uint32_t(packet.at(i + 1)) << (8 * i);
    return seq;
  }
};

TEST_F(DatagramTest, ConstructorValidatesBudgetBeforeUse) {
  EXPECT_THROW(DatagramBudget(0, 100), std::invalid_argument);
  EXPECT_THROW(DatagramBudget(1025, 100), std::invalid_argument);
  EXPECT_THROW(DatagramBudget(1, 0), std::invalid_argument);
  EXPECT_THROW(DatagramBudget(1, std::numeric_limits<size_t>::max()), std::invalid_argument);
  DatagramBudget changed;
  changed.packet_limit = 0;
  EXPECT_THROW(ReliableUDPChannel(sender, receiver.local_endpoint(), {}, changed),
               std::invalid_argument);
  EXPECT_THROW(ReliableUDPChannel(sender, receiver.local_endpoint(), {}, DatagramBudget{}, {}),
               std::invalid_argument);
}

TEST_F(DatagramTest, PacketCapRejectsBeforeSequenceAndRecoversAfterAck) {
  ReliableUDPChannel channel(sender, receiver.local_endpoint(), {}, DatagramBudget(2, 100),
                            [this] { return now; });
  const char payload[] = "ab";
  ASSERT_TRUE(channel.Send(payload, 2));
  auto first = Receive(receiver);
  ASSERT_TRUE(channel.Send(payload, 2));
  auto second = Receive(receiver);
  EXPECT_EQ(Sequence(first), 0u);
  EXPECT_EQ(Sequence(second), 1u);
  EXPECT_EQ(channel.pending_count(), 2u);
  EXPECT_EQ(channel.pending_bytes(), 18u);
  EXPECT_FALSE(channel.Send(payload, 2));
  EXPECT_EQ(channel.status(), UDPChannelStatus::Capacity);
  EXPECT_EQ(receiver.available(), 0u);
  now += std::chrono::milliseconds(25);
  Ack(channel, first);
  EXPECT_EQ(channel.pending_bytes(), 9u);
  EXPECT_EQ(channel.GetSmoothedRTT(), std::chrono::milliseconds(25));
  ASSERT_TRUE(channel.Send(payload, 2));
  auto third = Receive(receiver);
  EXPECT_EQ(Sequence(third), 2u);
  EXPECT_EQ(channel.status(), UDPChannelStatus::Ready);
  Ack(channel, second);
  Ack(channel, third);
  EXPECT_EQ(channel.pending_count(), 0u);
  EXPECT_EQ(channel.pending_bytes(), 0u);
}

TEST_F(DatagramTest, ByteCapIsIndependentOfPacketCountAndSurvivesRepeatedDrain) {
  ReliableUDPChannel channel(sender, receiver.local_endpoint(), {}, DatagramBudget(100, 20));
  std::array<uint8_t, 3> payload{1, 2, 3};
  for (unsigned cycle = 0; cycle < 100; ++cycle) {
    ASSERT_TRUE(channel.Send(payload.data(), payload.size()));
    auto first = Receive(receiver);
    ASSERT_TRUE(channel.Send(payload.data(), payload.size()));
    auto second = Receive(receiver);
    EXPECT_EQ(channel.pending_count(), 2u);
    EXPECT_EQ(channel.pending_bytes(), 20u);
    EXPECT_FALSE(channel.Send(nullptr, 0));
    EXPECT_EQ(channel.status(), UDPChannelStatus::Capacity);
    Ack(channel, second);
    Ack(channel, first);
    EXPECT_EQ(channel.pending_bytes(), 0u);
    EXPECT_EQ(channel.pending_count(), 0u);
  }
}

TEST_F(DatagramTest, InvalidLengthsNeverAllocateOrConsumeSequence) {
  ReliableUDPChannel channel(sender, receiver.local_endpoint(), {});
  uint8_t value = 1;
  EXPECT_FALSE(channel.Send(nullptr, 1));
  EXPECT_FALSE(channel.Send(&value, std::numeric_limits<size_t>::max()));
  EXPECT_FALSE(channel.Send(&value, kReliableUDP_MaxPayload + 1));
  EXPECT_EQ(channel.status(), UDPChannelStatus::InvalidPayload);
  EXPECT_EQ(channel.pending_bytes(), 0u);
  EXPECT_EQ(receiver.available(), 0u);
  std::vector<uint8_t> payload(kReliableUDP_MaxPayload, 0xAB);
  ASSERT_TRUE(channel.Send(payload.data(), payload.size()));
  auto packet = Receive(receiver);
  ASSERT_EQ(packet.size(), kReliableUDP_MaxPacketSize);
  EXPECT_EQ(Sequence(packet), 0u);
  EXPECT_TRUE(std::equal(payload.begin(), payload.end(), packet.begin() + kReliableUDP_HeaderSize));
  Ack(channel, packet);
  EXPECT_EQ(channel.pending_bytes(), 0u);
  ASSERT_TRUE(channel.Send(nullptr, 0));
  packet = Receive(receiver);
  EXPECT_EQ(packet.size(), kReliableUDP_HeaderSize);
  Ack(channel, packet);
}

TEST_F(DatagramTest, RetryExhaustionIsTerminalAndReleasesAllPackets) {
  ReliableUDPChannel channel(sender, receiver.local_endpoint(), {}, DatagramBudget{},
                            [this] { return now; });
  ASSERT_TRUE(channel.Send("a", 1));
  auto original = Receive(receiver);
  for (int retry = 0; retry < kReliableUDP_MaxRetries; ++retry) {
    now += std::chrono::seconds(2);
    ASSERT_TRUE(channel.TickRetransmit());
    EXPECT_EQ(Receive(receiver), original);
    EXPECT_EQ(channel.pending_bytes(), 8u);
  }
  ASSERT_TRUE(channel.Send("b", 1));
  Receive(receiver);
  now += std::chrono::seconds(2);
  EXPECT_FALSE(channel.TickRetransmit());
  EXPECT_EQ(channel.status(), UDPChannelStatus::RetriesExhausted);
  EXPECT_EQ(channel.pending_count(), 0u);
  EXPECT_EQ(channel.pending_bytes(), 0u);
  EXPECT_FALSE(channel.Send("c", 1));
  EXPECT_FALSE(channel.TickRetransmit());
  channel.Close();
  EXPECT_EQ(channel.status(), UDPChannelStatus::RetriesExhausted);
  EXPECT_EQ(receiver.available(), 0u);
}

TEST_F(DatagramTest, AckAfterRetransmitDoesNotDistortRttAndFreesCapacity) {
  ReliableUDPChannel channel(sender, receiver.local_endpoint(), {}, DatagramBudget(1, 8),
                            [this] { return now; });
  ASSERT_TRUE(channel.Send("a", 1));
  Receive(receiver);
  now += std::chrono::seconds(2);
  ASSERT_TRUE(channel.TickRetransmit());
  auto retried = Receive(receiver);
  now += std::chrono::milliseconds(5);
  Ack(channel, retried);
  EXPECT_EQ(channel.GetSmoothedRTT(), std::chrono::milliseconds(100));
  ASSERT_TRUE(channel.Send("b", 1));
  Ack(channel, Receive(receiver));
  EXPECT_EQ(channel.pending_bytes(), 0u);
}

TEST_F(DatagramTest, SendAndRetransmitSocketFailuresReleasePendingStorage) {
  for (bool retry : {false, true}) {
    udp::socket local(io, udp::endpoint(asio::ip::address_v4::loopback(), 0));
    ReliableUDPChannel channel(local, receiver.local_endpoint(), {}, DatagramBudget{},
                              [this] { return now; });
    ASSERT_TRUE(channel.Send("a", 1));
    Receive(receiver);
    local.close();
    now += std::chrono::seconds(2);
    EXPECT_FALSE(retry ? channel.TickRetransmit() : channel.Send("b", 1));
    EXPECT_EQ(channel.status(), UDPChannelStatus::SocketError);
    EXPECT_EQ(channel.pending_bytes(), 0u);
    EXPECT_EQ(channel.pending_count(), 0u);
  }
}

TEST_F(DatagramTest, MalformedDataAndUnknownAcksDoNotChangePendingOrDeliver) {
  size_t delivered = 0;
  ReliableUDPChannel channel(sender, receiver.local_endpoint(),
                            [&](const uint8_t*, size_t) { ++delivered; });
  ASSERT_TRUE(channel.Send("a", 1));
  auto packet = Receive(receiver);
  ASSERT_TRUE(channel.HandleReceived(nullptr, 1));
  ASSERT_TRUE(channel.HandleReceived(packet.data(), kReliableUDP_MaxPacketSize + 1));
  for (size_t size = 0; size < packet.size(); ++size)
    ASSERT_TRUE(channel.HandleReceived(packet.data(), size));
  packet.push_back(1);
  ASSERT_TRUE(channel.HandleReceived(packet.data(), packet.size()));
  std::array<uint8_t, 6> ack{kReliableUDP_Ack, 0, 0, 0, 0, 1};
  ASSERT_TRUE(channel.HandleReceived(ack.data(), ack.size()));
  ack[4] = 0xFF;
  ASSERT_TRUE(channel.HandleReceived(ack.data(), 5));
  EXPECT_EQ(channel.pending_count(), 1u);
  EXPECT_EQ(channel.pending_bytes(), 8u);
  EXPECT_EQ(delivered, 0u);
  EXPECT_EQ(receiver.available(), 0u);
}

TEST_F(DatagramTest, RealReceiverAcknowledgesAndCallbackCanSendAndClose) {
  ReliableUDPChannel outgoing(sender, receiver.local_endpoint(), {});
  ReliableUDPChannel* callback_channel = nullptr;
  std::vector<uint8_t> delivered;
  ReliableUDPChannel incoming(receiver, sender.local_endpoint(), [&](const uint8_t* data, size_t length) {
    delivered.assign(data, data + length);
    EXPECT_TRUE(callback_channel->Send("reply", 5));
    callback_channel->Close();
  });
  callback_channel = &incoming;
  ASSERT_TRUE(outgoing.Send("hello", 5));
  auto packet = Receive(receiver);
  ASSERT_TRUE(incoming.HandleReceived(packet.data(), packet.size()));
  EXPECT_EQ(std::string(delivered.begin(), delivered.end()), "hello");
  auto ack = Receive(sender);
  ASSERT_TRUE(outgoing.HandleReceived(ack.data(), ack.size()));
  EXPECT_EQ(outgoing.pending_bytes(), 0u);
  auto reply = Receive(sender);
  EXPECT_EQ(std::string(reply.begin() + kReliableUDP_HeaderSize, reply.end()), "reply");
  EXPECT_EQ(incoming.pending_bytes(), 0u);
  EXPECT_EQ(incoming.status(), UDPChannelStatus::Closed);
  EXPECT_TRUE(receiver.is_open());
}

TEST_F(DatagramTest, AckSendFailureDoesNotDeliverAndClosePreservesSharedSocket) {
  ReliableUDPChannel outgoing(sender, receiver.local_endpoint(), {});
  unsigned delivered = 0;
  ReliableUDPChannel incoming(receiver, sender.local_endpoint(),
                            [&](const uint8_t*, size_t) { ++delivered; });
  ASSERT_TRUE(outgoing.Send("a", 1));
  auto packet = Receive(receiver);
  receiver.close();
  EXPECT_FALSE(incoming.HandleReceived(packet.data(), packet.size()));
  EXPECT_EQ(incoming.status(), UDPChannelStatus::SocketError);
  EXPECT_EQ(delivered, 0u);
  outgoing.Close();
  outgoing.Close();
  EXPECT_EQ(outgoing.pending_bytes(), 0u);
  EXPECT_TRUE(sender.is_open());
}

TEST_F(DatagramTest, ConcurrentSendsCannotExceedBudget) {
  ReliableUDPChannel channel(sender, receiver.local_endpoint(), {}, DatagramBudget(32, 256));
  std::atomic<unsigned> accepted{0};
  std::vector<std::thread> writers;
  for (unsigned i = 0; i < 4; ++i) writers.emplace_back([&] {
    for (unsigned n = 0; n < 32; ++n) {
      if (channel.Send("a", 1)) ++accepted;
      EXPECT_LE(channel.pending_count(), 32u);
      EXPECT_LE(channel.pending_bytes(), 256u);
      EXPECT_GE(channel.GetSmoothedRTT().count(), 0);
      (void)channel.GetBandwidthBPS();
    }
  });
  for (auto& thread : writers) thread.join();
  EXPECT_EQ(accepted, 32u);
  EXPECT_EQ(channel.pending_count(), 32u);
  EXPECT_EQ(channel.pending_bytes(), 256u);
  for (unsigned i = 0; i < 32; ++i) Ack(channel, Receive(receiver));
  EXPECT_EQ(channel.pending_bytes(), 0u);
}

// 2026-09-13: real datagrams cover duplicate/ordered delivery, receive capacity and callback ownership.
// TEST(RTTBudget, ExtremeDurationsAndDeviationRemainBoundedInMilliseconds) {
TEST_F(DatagramTest, ReorderedDatagramsDeliverExactlyOnceAndInSequence) {
  ReliableUDPChannel outgoing(sender, receiver.local_endpoint(), {});
  std::string delivered;
  ReliableUDPChannel incoming(receiver, sender.local_endpoint(),
      [&](const uint8_t* data, size_t length) { delivered.append(reinterpret_cast<const char*>(data), length); });
  ASSERT_TRUE(outgoing.Send("a", 1)); const auto first = Receive(receiver);
  ASSERT_TRUE(outgoing.Send("b", 1)); const auto second = Receive(receiver);
  ASSERT_TRUE(incoming.HandleReceived(second.data(), second.size()));
  auto ack = Receive(sender); ASSERT_TRUE(outgoing.HandleReceived(ack.data(), ack.size()));
  EXPECT_TRUE(delivered.empty());
  EXPECT_EQ(incoming.received_count(), 1u);
  EXPECT_EQ(incoming.received_bytes(), second.size());
  ASSERT_TRUE(incoming.HandleReceived(second.data(), second.size()));
  Receive(sender);
  EXPECT_TRUE(delivered.empty());
  ASSERT_TRUE(incoming.HandleReceived(first.data(), first.size()));
  ack = Receive(sender); ASSERT_TRUE(outgoing.HandleReceived(ack.data(), ack.size()));
  EXPECT_EQ(delivered, "ab");
  EXPECT_EQ(incoming.received_count(), 0u);
  EXPECT_EQ(incoming.received_bytes(), 0u);
  for (const auto* packet : {&first, &second, &first}) {
    ASSERT_TRUE(incoming.HandleReceived(packet->data(), packet->size()));
    Receive(sender);
    EXPECT_EQ(delivered, "ab");
  }
}
TEST_F(DatagramTest, ConflictingFutureDatagramFailsBeforeApplicationDelivery) {
  ReliableUDPChannel outgoing(sender, receiver.local_endpoint(), {});
  unsigned delivered = 0;
  ReliableUDPChannel incoming(receiver, sender.local_endpoint(),
      [&](const uint8_t*, size_t) { ++delivered; });
  ASSERT_TRUE(outgoing.Send("a", 1)); Receive(receiver);
  ASSERT_TRUE(outgoing.Send("b", 1)); auto future = Receive(receiver);
  ASSERT_TRUE(incoming.HandleReceived(future.data(), future.size())); Receive(sender);
  future.back() = 'c';
  EXPECT_FALSE(incoming.HandleReceived(future.data(), future.size()));
  EXPECT_EQ(delivered, 0u);
  EXPECT_EQ(incoming.status(), UDPChannelStatus::InvalidPayload);
  EXPECT_EQ(incoming.received_bytes(), 0u);
  EXPECT_EQ(sender.available(), 0u);
}
TEST_F(DatagramTest, ReceiveCapacityCountsInFlightCallbacksAndRetainedFuturePackets) {
  ReliableUDPChannel outgoing(sender, receiver.local_endpoint(), {});
  ASSERT_TRUE(outgoing.Send("a", 1)); const auto first = Receive(receiver);
  ASSERT_TRUE(outgoing.Send("b", 1)); const auto second = Receive(receiver);
  ReliableUDPChannel* active = nullptr;
  unsigned delivered = 0;
  ReliableUDPChannel incoming(receiver, sender.local_endpoint(), [&](const uint8_t*, size_t) {
    ++delivered;
    EXPECT_EQ(active->received_count(), 1u);
    EXPECT_EQ(active->received_bytes(), 8u);
    // Even during the callback, the first packet still owns the sole budget slot.
    EXPECT_FALSE(active->HandleReceived(second.data(), second.size()));
    EXPECT_EQ(active->status(), UDPChannelStatus::Capacity);
  }, DatagramBudget(1, 8));
  active = &incoming;
  ASSERT_TRUE(incoming.HandleReceived(first.data(), first.size())); Receive(sender);
  EXPECT_EQ(delivered, 1u);
  EXPECT_EQ(incoming.received_count(), 0u);
  EXPECT_EQ(incoming.received_bytes(), 0u);
}
TEST_F(DatagramTest, ReentrantReceiveQueuesBehindCurrentCallbackWithoutDeadlock) {
  ReliableUDPChannel outgoing(sender, receiver.local_endpoint(), {});
  ASSERT_TRUE(outgoing.Send("a", 1)); const auto first = Receive(receiver);
  ASSERT_TRUE(outgoing.Send("b", 1)); const auto second = Receive(receiver);
  ReliableUDPChannel* active = nullptr;
  std::string delivered;
  ReliableUDPChannel incoming(receiver, sender.local_endpoint(), [&](const uint8_t* data, size_t length) {
    delivered.append(reinterpret_cast<const char*>(data), length);
    if (delivered == "a") {
      ASSERT_TRUE(active->HandleReceived(second.data(), second.size()));
      EXPECT_EQ(delivered, "a");
      EXPECT_EQ(active->received_bytes(), 16u);
    }
  }, DatagramBudget(2, 16));
  active = &incoming;
  ASSERT_TRUE(incoming.HandleReceived(first.data(), first.size()));
  Receive(sender); Receive(sender);
  EXPECT_EQ(delivered, "ab");
  EXPECT_EQ(incoming.received_bytes(), 0u);
}
TEST_F(DatagramTest, ThrowingReceiveCallbackReleasesBothDirectionsAndRejectsFurtherWork) {
  ReliableUDPChannel outgoing(sender, receiver.local_endpoint(), {});
  ASSERT_TRUE(outgoing.Send("a", 1)); const auto packet = Receive(receiver);
  ReliableUDPChannel incoming(receiver, sender.local_endpoint(),
      [](const uint8_t*, size_t) { throw std::runtime_error("injected callback failure"); });
  ASSERT_TRUE(incoming.Send("pending", 7)); Receive(sender);
// 2026-09-13: the injected exception test intentionally discards a nodiscard success value.
//   EXPECT_THROW(incoming.HandleReceived(packet.data(), packet.size()), std::runtime_error);
  EXPECT_THROW((void)incoming.HandleReceived(packet.data(), packet.size()), std::runtime_error);
  Receive(sender);
  EXPECT_EQ(incoming.received_bytes(), 0u);
  EXPECT_EQ(incoming.pending_bytes(), 0u);
  EXPECT_FALSE(incoming.Send("more", 4));
  EXPECT_TRUE(receiver.is_open());
}

// 2026-09-13: receive byte admission and the sequence window have independent limits.
// TEST(RTTBudget, ExtremeDurationsAndDeviationRemainBoundedInMilliseconds) {
TEST_F(DatagramTest, ReceiveByteLimitAndSequenceWindowRejectBeforeAck) {
  ReliableUDPChannel outgoing(sender, receiver.local_endpoint(), {});
  ASSERT_TRUE(outgoing.Send("a", 1)); Receive(receiver);
  ASSERT_TRUE(outgoing.Send("b", 1)); const auto second = Receive(receiver);
  ASSERT_TRUE(outgoing.Send("c", 1)); const auto third = Receive(receiver);
  unsigned delivered = 0;
  ReliableUDPChannel incoming(receiver, sender.local_endpoint(),
      [&](const uint8_t*, size_t) { ++delivered; }, DatagramBudget(4, 15));
  ASSERT_TRUE(incoming.HandleReceived(second.data(), second.size())); Receive(sender);
  EXPECT_FALSE(incoming.HandleReceived(third.data(), third.size()));
  EXPECT_EQ(incoming.status(), UDPChannelStatus::Capacity);
  EXPECT_EQ(incoming.received_bytes(), 0u);
  EXPECT_EQ(delivered, 0u);
  EXPECT_EQ(sender.available(), 0u);
  ReliableUDPChannel window(receiver, sender.local_endpoint(), {}, DatagramBudget(1, 100));
  EXPECT_FALSE(window.HandleReceived(second.data(), second.size()));
  EXPECT_EQ(window.status(), UDPChannelStatus::InvalidPayload);
  EXPECT_EQ(window.received_count(), 0u);
  EXPECT_EQ(sender.available(), 0u);
}

TEST(RTTBudget, ExtremeDurationsAndDeviationRemainBoundedInMilliseconds) {
  RTTTracker tracker;
  tracker.RecordSample(std::chrono::milliseconds(-1));
  EXPECT_EQ(tracker.GetSmoothedRTT(), std::chrono::milliseconds(100));
  for (unsigned i = 0; i < 1000; ++i)
    tracker.RecordSample(std::chrono::milliseconds::max());
  EXPECT_EQ(tracker.GetSmoothedRTT(), std::chrono::milliseconds(60000));
  EXPECT_EQ(tracker.GetRTTVar(), std::chrono::milliseconds(0));
  tracker.Reset();
  tracker.RecordSample(std::chrono::milliseconds(10));
  tracker.RecordSample(std::chrono::milliseconds(30));
  EXPECT_EQ(tracker.GetSmoothedRTT(), std::chrono::milliseconds(20));
  EXPECT_EQ(tracker.GetRTTVar(), std::chrono::milliseconds(10));
}
}  // namespace
}  // namespace frame_sync
