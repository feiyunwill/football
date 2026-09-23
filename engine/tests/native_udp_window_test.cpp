// 2026-09-15: real loopback datagrams across destroyed/recreated channels.
// The two generation witnesses run unchanged against the previous header.
#include "fixtures/native_udp/window/legacy.inc"
#include <stdexcept>
#ifndef EXPECT_GENERATIONS
#define EXPECT_GENERATIONS 1
#endif
namespace frame_sync {
namespace {
using Connection = std::array<uint8_t,16>;
class GenerationDatagramTest : public DatagramTest {
 public:
  GenerationDatagramTest() = default;
  ~GenerationDatagramTest() override = default;
  GenerationDatagramTest(const GenerationDatagramTest&) = delete;
  GenerationDatagramTest& operator=(const GenerationDatagramTest&) = delete;
  GenerationDatagramTest(GenerationDatagramTest&&) = delete;
  GenerationDatagramTest& operator=(GenerationDatagramTest&&) = delete;
 protected:
  static Connection Id(uint8_t value) {
    Connection result{};
    result[0]=value; result[15]=static_cast<uint8_t>(value+1);
    return result;
  }
  std::unique_ptr<ReliableUDPChannel> Channel(
      bool left, Connection id, ReliableUDPChannel::OnDataFn callback={},
      DatagramBudget budget=DatagramBudget{}) {
    auto& socket=left ? sender : receiver;
    const auto remote=left ? receiver.local_endpoint() : sender.local_endpoint();
#if EXPECT_GENERATIONS
    return std::make_unique<ReliableUDPChannel>(
        socket,remote,std::move(callback),budget,[this]{return now;},id);
#else
    (void)id;
    return std::make_unique<ReliableUDPChannel>(
        socket,remote,std::move(callback),budget,[this]{return now;});
#endif
  }
  bool Deliver(ReliableUDPChannel& channel,const std::vector<uint8_t>& packet) {
    return channel.HandleReceived(packet.data(),packet.size());
  }
  bool Inject(bool from_left,ReliableUDPChannel& target,const std::vector<uint8_t>& packet) {
    auto& source=from_left ? sender : receiver;
    auto& destination=from_left ? receiver : sender;
    source.send_to(asio::buffer(packet),destination.local_endpoint());
    return Deliver(target,Receive(destination));
  }
  void DrainAck(ReliableUDPChannel& target) {
    ASSERT_TRUE(Deliver(target,Receive(sender)));
  }
  // 2026-09-15: retain an actual missing packet while selectively ACKing
  // later packets, in both legacy and scoped wire formats.
  void MissingPacketWindow(unsigned missing) {
    constexpr unsigned window=4;
    for(bool scoped:{false,true}) {
      SCOPED_TRACE(scoped ? "scoped" : "legacy");
      const auto identity=scoped ? std::optional<ReliableUDPConnection>(Id(9)) : std::nullopt;
      std::string delivered,expected;std::vector<uint8_t> lost;
      ReliableUDPChannel left(sender,receiver.local_endpoint(),{},DatagramBudget(window,window*64),
                              [this]{return now;},identity);
      ReliableUDPChannel right(receiver,sender.local_endpoint(),
        [&](const uint8_t* p,size_t n){delivered.append(reinterpret_cast<const char*>(p),n);},
        DatagramBudget(window,window*64),[this]{return now;},identity);
      for(unsigned i=0;i<window+missing;++i) {
        const char value=static_cast<char>('a'+i);expected+=value;
        ASSERT_TRUE(left.Send(&value,1));auto packet=Receive(receiver);
        if(i==missing){lost=std::move(packet);continue;}
        ASSERT_TRUE(Deliver(right,packet));DrainAck(left);
      }
      ASSERT_EQ(left.pending_count(),1u);ASSERT_EQ(right.received_count(),window-1);
      ASSERT_EQ(delivered,expected.substr(0,missing));
      const char extra=static_cast<char>('a'+window+missing);
      const bool advanced=left.Send(&extra,1);
      EXPECT_FALSE(advanced)<<"Selective ACKs must not overrun the missing receive sequence";
      if(advanced) {
        const auto outside=Receive(receiver);
        EXPECT_TRUE(Deliver(right,outside))<<"Old sender's valid next packet closes its peer";
        EXPECT_EQ(right.status(),UDPChannelStatus::Ready);
        left.Close();right.Close();continue;
      }
      EXPECT_EQ(left.status(),UDPChannelStatus::Capacity);EXPECT_EQ(receiver.available(),0u);
      now+=std::chrono::milliseconds(1001);
      ASSERT_TRUE(left.TickRetransmit());const auto retry=Receive(receiver);EXPECT_EQ(retry,lost);
      ASSERT_TRUE(Deliver(right,retry));DrainAck(left);
      EXPECT_EQ(delivered,expected);EXPECT_EQ(left.pending_count(),0u);EXPECT_EQ(right.received_count(),0u);
      ASSERT_TRUE(left.Send(&extra,1));auto next=Receive(receiver);
      EXPECT_EQ(scoped ? ScopedSequence(next) : Sequence(next),window+missing);
      ASSERT_TRUE(Deliver(right,next));DrainAck(left);
      EXPECT_EQ(delivered,expected+extra);EXPECT_EQ(left.pending_bytes(),0u);
    }
  }
  static uint32_t ScopedSequence(const std::vector<uint8_t>& packet) {
    uint32_t value=0;
    for(unsigned i=0;i<4;++i)value|=uint32_t(packet.at(17+i))<<(8*i);
    return value;
  }
};

TEST_F(GenerationDatagramTest,LateDataCannotAdvanceNewConnection) {
  auto old_sender=Channel(true,Id(1));
  ASSERT_TRUE(old_sender->Send("old",3));
  const auto stale=Receive(receiver);
  old_sender->Close(); old_sender.reset();
  std::string delivered;
  auto fresh_receiver=Channel(false,Id(2),[&](const uint8_t* p,size_t n){
    delivered.append(reinterpret_cast<const char*>(p),n);
  });
  ASSERT_TRUE(Inject(true,*fresh_receiver,stale));
  ASSERT_TRUE(delivered.empty());
  EXPECT_EQ(fresh_receiver->received_count(),0u);
  EXPECT_EQ(sender.available(),0u);
  auto fresh_sender=Channel(true,Id(2));
  ASSERT_TRUE(fresh_sender->Send("fresh",5));
  ASSERT_TRUE(Deliver(*fresh_receiver,Receive(receiver)));
  EXPECT_EQ(delivered,"fresh");
  DrainAck(*fresh_sender);
  EXPECT_EQ(fresh_sender->pending_count(),0u);
}

TEST_F(GenerationDatagramTest,LateAckCannotClearNewPending) {
  auto old_sender=Channel(true,Id(1));
  auto old_receiver=Channel(false,Id(1));
  ASSERT_TRUE(old_sender->Send("old",3));
  ASSERT_TRUE(Deliver(*old_receiver,Receive(receiver)));
  const auto stale_ack=Receive(sender);
  old_sender->Close();old_receiver->Close();
  old_sender.reset();old_receiver.reset();
  auto fresh_sender=Channel(true,Id(2));
  ASSERT_TRUE(fresh_sender->Send("fresh",5));
  const auto fresh_data=Receive(receiver);
  now+=std::chrono::milliseconds(25);
  ASSERT_TRUE(Inject(false,*fresh_sender,stale_ack));
  ASSERT_EQ(fresh_sender->pending_count(),1u);
  EXPECT_EQ(fresh_sender->GetSmoothedRTT(),std::chrono::milliseconds(100));
  auto fresh_receiver=Channel(false,Id(2));
  ASSERT_TRUE(Deliver(*fresh_receiver,fresh_data));
  DrainAck(*fresh_sender);
  EXPECT_EQ(fresh_sender->pending_count(),0u);
  EXPECT_EQ(fresh_sender->GetSmoothedRTT(),std::chrono::milliseconds(25));
}

#if EXPECT_GENERATIONS
TEST_F(GenerationDatagramTest,HeaderCarriesEveryIdentityByteAndExactMaximum) {
  Connection id{};for(unsigned i=0;i<16;++i)id[i]=static_cast<uint8_t>(i+1);
  auto left=Channel(true,id);
  size_t delivered=0;
  auto right=Channel(false,id,[&](const uint8_t* p,size_t n){
    delivered=n;for(size_t i=0;i<n;++i)EXPECT_EQ(p[i],static_cast<uint8_t>(i));
  });
  EXPECT_EQ(left->max_payload_size(),1177u);
  std::vector<uint8_t> payload(1177);
  for(size_t i=0;i<payload.size();++i)payload[i]=static_cast<uint8_t>(i);
  ASSERT_TRUE(left->Send(payload.data(),payload.size()));
  const auto packet=Receive(receiver);
  ASSERT_EQ(packet.size(),1200u);
  EXPECT_EQ(packet[0],0x01);
  EXPECT_TRUE(std::equal(id.begin(),id.end(),packet.begin()+1));
  EXPECT_EQ(ScopedSequence(packet),0u);
  EXPECT_EQ(uint16_t(packet[21])|(uint16_t(packet[22])<<8),1177);
  EXPECT_EQ(left->pending_bytes(),1200u);
  ASSERT_TRUE(Deliver(*right,packet));
  const auto ack=Receive(sender);
  ASSERT_EQ(ack.size(),21u);
  EXPECT_EQ(ack[0],0xFE);
  EXPECT_TRUE(std::equal(id.begin(),id.end(),ack.begin()+1));
  EXPECT_EQ(ScopedSequence(ack),0u);
  ASSERT_TRUE(Deliver(*left,ack));
  EXPECT_EQ(delivered,1177u);
  EXPECT_EQ(left->pending_bytes(),0u);
}
TEST_F(GenerationDatagramTest,OversizedPayloadDoesNotConsumeSequence) {
  auto left=Channel(true,Id(1));
  uint8_t value=9;
  EXPECT_FALSE(left->Send(&value,1178));
  EXPECT_EQ(left->status(),UDPChannelStatus::InvalidPayload);
  EXPECT_EQ(left->pending_count(),0u);
  EXPECT_EQ(receiver.available(),0u);
  ASSERT_TRUE(left->Send(&value,1));
  EXPECT_EQ(ScopedSequence(Receive(receiver)),0u);
}
TEST_F(GenerationDatagramTest,AllZeroIdentityRejectedWithoutSocketEffects) {
  EXPECT_THROW(Channel(true,Connection{}),std::invalid_argument);
  EXPECT_TRUE(sender.is_open());
  EXPECT_EQ(receiver.available(),0u);
}
TEST_F(GenerationDatagramTest,EveryWrongIdentityByteIsIgnoredBeforeQueueAndAck) {
  auto left=Channel(true,Id(1));
  unsigned deliveries=0;
  auto right=Channel(false,Id(1),[&](const uint8_t*,size_t){++deliveries;});
  ASSERT_TRUE(left->Send("x",1));
  const auto valid=Receive(receiver);
  for(size_t i=1;i<=16;++i) {
    auto stale=valid;stale[i]^=0x80;
    ASSERT_TRUE(Inject(true,*right,stale));
    EXPECT_EQ(deliveries,0u);
    EXPECT_EQ(right->received_count(),0u);
    EXPECT_EQ(right->status(),UDPChannelStatus::Ready);
    EXPECT_EQ(sender.available(),0u);
  }
  ASSERT_TRUE(Inject(true,*right,valid));
  EXPECT_EQ(deliveries,1u);DrainAck(*left);
}
TEST_F(GenerationDatagramTest,TruncatedAndExtendedPrefixesHaveNoStateEffects) {
  auto left=Channel(true,Id(1));
  unsigned deliveries=0;
  auto right=Channel(false,Id(1),[&](const uint8_t*,size_t){++deliveries;});
  ASSERT_TRUE(left->Send("xyz",3));const auto valid=Receive(receiver);
  ASSERT_TRUE(right->HandleReceived(nullptr,1));
  for(size_t n=0;n<valid.size();++n)
    ASSERT_TRUE(right->HandleReceived(valid.data(),n));
  auto too_long=valid;too_long.push_back(0);
  ASSERT_TRUE(Inject(true,*right,too_long));
  too_long.resize(1201);
  ASSERT_TRUE(Deliver(*right,too_long));
  EXPECT_EQ(right->received_count(),0u);
  EXPECT_EQ(deliveries,0u);EXPECT_EQ(sender.available(),0u);
  ASSERT_TRUE(Inject(true,*right,valid));DrainAck(*left);EXPECT_EQ(deliveries,1u);
}
TEST_F(GenerationDatagramTest,WrongMalformedAndUnknownAcksKeepPendingAndRtt) {
  auto left=Channel(true,Id(1));auto right=Channel(false,Id(1));
  ASSERT_TRUE(left->Send("x",1));
  ASSERT_TRUE(Deliver(*right,Receive(receiver)));
  const auto good=Receive(sender);
  for(size_t i=1;i<=16;++i) {
    auto bad=good;bad[i]^=0x80;
    ASSERT_TRUE(Inject(false,*left,bad));EXPECT_EQ(left->pending_count(),1u);
  }
  for(size_t n=0;n<good.size();++n) {
    ASSERT_TRUE(left->HandleReceived(good.data(),n));EXPECT_EQ(left->pending_count(),1u);
  }
  auto extra=good;extra.push_back(0);
  ASSERT_TRUE(Inject(false,*left,extra));
  auto unknown=good;unknown[17]=42;
  ASSERT_TRUE(Inject(false,*left,unknown));
  EXPECT_EQ(left->pending_count(),1u);
  EXPECT_EQ(left->GetSmoothedRTT(),std::chrono::milliseconds(100));
  now+=std::chrono::milliseconds(23);ASSERT_TRUE(Inject(false,*left,good));
  EXPECT_EQ(left->pending_count(),0u);
  EXPECT_EQ(left->GetSmoothedRTT(),std::chrono::milliseconds(23));
}
TEST_F(GenerationDatagramTest,LegacyAndScopedModesDoNotMix) {
  ReliableUDPChannel legacy(sender,receiver.local_endpoint(),{});
  auto scoped=Channel(false,Id(1));
  ASSERT_TRUE(legacy.Send("x",1));auto legacy_packet=Receive(receiver);
  ASSERT_TRUE(Deliver(*scoped,legacy_packet));EXPECT_EQ(sender.available(),0u);
  ASSERT_TRUE(scoped->Send("y",1));auto scoped_packet=Receive(sender);
  ASSERT_TRUE(Deliver(legacy,scoped_packet));EXPECT_EQ(receiver.available(),0u);
  EXPECT_EQ(legacy.pending_count(),1u);EXPECT_EQ(scoped->pending_count(),1u);
  std::array<uint8_t,5> ack{0xFF,0,0,0,0};
  ASSERT_TRUE(scoped->HandleReceived(ack.data(),ack.size()));
  EXPECT_EQ(scoped->pending_count(),1u);
  EXPECT_EQ(legacy.max_payload_size(),1193u);
}
TEST_F(GenerationDatagramTest,ScopedDataReordersAndDeliversExactlyOnce) {
  auto left=Channel(true,Id(1));std::string seen;
  auto right=Channel(false,Id(1),[&](const uint8_t* p,size_t n){
    seen.append(reinterpret_cast<const char*>(p),n);
  });
  ASSERT_TRUE(left->Send("a",1));auto first=Receive(receiver);
  ASSERT_TRUE(left->Send("b",1));auto second=Receive(receiver);
  ASSERT_TRUE(Inject(true,*right,second));DrainAck(*left);
  EXPECT_TRUE(seen.empty());EXPECT_EQ(right->received_bytes(),24u);
  ASSERT_TRUE(Inject(true,*right,second));DrainAck(*left);
  EXPECT_TRUE(seen.empty());
  ASSERT_TRUE(Inject(true,*right,first));DrainAck(*left);
  EXPECT_EQ(seen,"ab");EXPECT_EQ(right->received_bytes(),0u);
  ASSERT_TRUE(Inject(true,*right,first));DrainAck(*left);
  EXPECT_EQ(seen,"ab");
}
TEST_F(GenerationDatagramTest,ScopedSendByteBudgetIncludesIdentityStorage) {
  auto left=Channel(true,Id(1),{},DatagramBudget(8,47));
  auto right=Channel(false,Id(1));
  ASSERT_TRUE(left->Send("x",1));auto first=Receive(receiver);
  EXPECT_EQ(left->pending_bytes(),24u);
  EXPECT_FALSE(left->Send("y",1));EXPECT_EQ(left->status(),UDPChannelStatus::Capacity);
  EXPECT_EQ(receiver.available(),0u);
  ASSERT_TRUE(left->Send(nullptr,0));auto second=Receive(receiver);
  EXPECT_EQ(left->pending_bytes(),47u);EXPECT_EQ(ScopedSequence(second),1u);
  ASSERT_TRUE(Deliver(*right,first));DrainAck(*left);
  ASSERT_TRUE(Deliver(*right,second));DrainAck(*left);
  EXPECT_EQ(left->pending_bytes(),0u);
}
TEST_F(GenerationDatagramTest,ScopedReceiveByteBudgetCountsHeaderBeforeAck) {
  auto left=Channel(true,Id(1));auto right=Channel(false,Id(1),{},DatagramBudget(4,23));
  ASSERT_TRUE(left->Send("x",1));auto first=Receive(receiver);
  EXPECT_FALSE(Deliver(*right,first));
  EXPECT_EQ(right->status(),UDPChannelStatus::Capacity);
  EXPECT_EQ(right->received_bytes(),0u);EXPECT_EQ(sender.available(),0u);
  EXPECT_TRUE(receiver.is_open());
}
TEST_F(GenerationDatagramTest,WrongGenerationExtremeSequenceCannotCloseCurrentWindow) {
  auto left=Channel(true,Id(1));auto right=Channel(false,Id(2),{},DatagramBudget(2,64));
  ASSERT_TRUE(left->Send("x",1));auto stale=Receive(receiver);
  stale[17]=0xFF;stale[18]=0xFF;stale[19]=0xFF;stale[20]=0x7F;
  ASSERT_TRUE(Inject(true,*right,stale));
  EXPECT_EQ(right->status(),UDPChannelStatus::Ready);EXPECT_EQ(sender.available(),0u);
  EXPECT_EQ(right->received_count(),0u);
}
TEST_F(GenerationDatagramTest,LostAckRetransmitsSameScopedPacketWithoutDuplicateDelivery) {
  auto left=Channel(true,Id(1));unsigned seen=0;
  auto right=Channel(false,Id(1),[&](const uint8_t*,size_t){++seen;});
  ASSERT_TRUE(left->Send("x",1));const auto first=Receive(receiver);
  ASSERT_TRUE(Deliver(*right,first));(void)Receive(sender);
  now+=std::chrono::seconds(1);
  ASSERT_TRUE(left->TickRetransmit());const auto repeated=Receive(receiver);
  EXPECT_EQ(first,repeated);ASSERT_TRUE(Deliver(*right,repeated));DrainAck(*left);
  EXPECT_EQ(seen,1u);EXPECT_EQ(left->pending_count(),0u);
  EXPECT_EQ(left->GetSmoothedRTT(),std::chrono::milliseconds(100));
}
TEST_F(GenerationDatagramTest,ScopedRetryExhaustionReleasesBothQueues) {
  auto left=Channel(true,Id(1));
  ASSERT_TRUE(left->Send("x",1));(void)Receive(receiver);
  for(int i=0;i<kReliableUDP_MaxRetries;++i) {
    now+=std::chrono::seconds(1);
    ASSERT_TRUE(left->TickRetransmit());(void)Receive(receiver);
  }
  now+=std::chrono::seconds(1);
  EXPECT_FALSE(left->TickRetransmit());EXPECT_EQ(left->status(),UDPChannelStatus::RetriesExhausted);
  EXPECT_EQ(left->pending_bytes(),0u);EXPECT_EQ(left->received_bytes(),0u);
  EXPECT_TRUE(sender.is_open());EXPECT_EQ(receiver.available(),0u);
}
TEST_F(GenerationDatagramTest,CallbackCanReplyAndCloseWithIdentityPreserved) {
  auto left=Channel(true,Id(1));
  ReliableUDPChannel* ptr=nullptr;
  auto right=Channel(false,Id(1),[&](const uint8_t*,size_t){
    EXPECT_EQ(ptr->received_bytes(),24u);
    EXPECT_TRUE(ptr->Send("r",1));ptr->Close();
  });
  ptr=right.get();
  ASSERT_TRUE(left->Send("x",1));ASSERT_TRUE(Deliver(*right,Receive(receiver)));
  DrainAck(*left);const auto reply=Receive(sender);
  ASSERT_EQ(reply.size(),24u);EXPECT_EQ(reply[0],0x01);
  EXPECT_EQ(right->received_bytes(),0u);EXPECT_EQ(right->pending_bytes(),0u);
  EXPECT_TRUE(receiver.is_open());
}
TEST_F(GenerationDatagramTest,RepeatedPhysicalGenerationsCannotReusePreviousPackets) {
  std::vector<uint8_t> previous_data,previous_ack;
  for(unsigned cycle=1;cycle<=128;++cycle) {
    auto left=Channel(true,Id(static_cast<uint8_t>(cycle)));
    unsigned deliveries=0;
    auto right=Channel(false,Id(static_cast<uint8_t>(cycle)),
                       [&](const uint8_t*,size_t){++deliveries;});
    uint8_t value=static_cast<uint8_t>(cycle);
    ASSERT_TRUE(left->Send(&value,1));const auto current=Receive(receiver);
    if(!previous_data.empty()) {
      ASSERT_TRUE(Inject(true,*right,previous_data));
      ASSERT_TRUE(Inject(false,*left,previous_ack));
      EXPECT_EQ(deliveries,0u);EXPECT_EQ(left->pending_count(),1u);
      EXPECT_EQ(sender.available(),0u);
    }
    ASSERT_TRUE(Inject(true,*right,current));const auto ack=Receive(sender);
    ASSERT_TRUE(Deliver(*left,ack));
    EXPECT_EQ(deliveries,1u);EXPECT_EQ(left->pending_count(),0u);
    previous_data=current;previous_ack=ack;
  }
}
TEST_F(GenerationDatagramTest,SelectiveAcksCannotAdvancePastLostFirstPacket) {MissingPacketWindow(0);}
TEST_F(GenerationDatagramTest,SelectiveAcksCannotAdvancePastLostMiddlePacket) {MissingPacketWindow(2);}
#endif
} // namespace
} // namespace frame_sync
