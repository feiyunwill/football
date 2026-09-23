
TEST_F(StreamPair,LargeComposedTransferPipelinesWithinWireAndMemoryLimits) {
  auto source=std::make_shared<std::vector<uint8_t>>(1024*1024);
  for(size_t i=0;i<source->size();++i)(*source)[i]=static_cast<uint8_t>((i*31+i/97)%251);
  auto target=std::make_shared<std::vector<uint8_t>>(source->size());
  auto written=outcome(),read=outcome();
  asio::async_read(*right,asio::buffer(*target),[target,read](Error e,size_t n){finish(read,e,n);});
  asio::async_write(*left,asio::buffer(*source),[source,written](Error e,size_t n){finish(written,e,n);});
  EXPECT_EQ(std::get<0>(*written),0);
  Until([&]{return std::get<0>(*written) && std::get<0>(*read);});
  EXPECT_FALSE(std::get<1>(*written));EXPECT_FALSE(std::get<1>(*read));
  EXPECT_EQ(std::get<2>(*written),source->size());EXPECT_EQ(*source,*target);
  EXPECT_GT(peak_pending,1u);EXPECT_LE(peak_pending,64u);
  EXPECT_LE(max_wire,1200u);EXPECT_GT(wire_packets,1000u);
  EXPECT_LE(rc.Stats()->receive_bytes,64*1024u);
  Until([&]{return lc.Stats()->pending_packets==0;});
}
TEST_F(StreamPair,ScatterGatherPreservesEmptyAndPartialBuffers) {
  auto text=std::make_shared<std::string>("abcdefghi");auto result=outcome();
  const std::array<asio::const_buffer,4> pieces{asio::const_buffer{},asio::buffer(text->data(),2),
    asio::const_buffer{},asio::buffer(text->data()+2,7)};
  auto output=std::make_shared<std::vector<uint8_t>>(9);auto read=outcome();
  const std::array<asio::mutable_buffer,3> destinations{asio::mutable_buffer{},asio::buffer(output->data(),3),
    asio::buffer(output->data()+3,6)};
  asio::async_read(*right,destinations,[output,read](Error e,size_t n){finish(read,e,n);});
  asio::async_write(*left,pieces,[text,result](Error e,size_t n){finish(result,e,n);});
  Until([&]{return std::get<0>(*read)>0;});
  EXPECT_FALSE(std::get<1>(*read));EXPECT_EQ(std::get<2>(*read),9u);
  EXPECT_EQ(std::string(output->begin(),output->end()),*text);
  EXPECT_EQ(std::get<0>(*result),1);EXPECT_EQ(std::get<2>(*result),9u);
}
TEST_F(StreamPair,RingWrapPreservesUnreadPrefix) {
  Open({},NativeUDPStreamLimits(DatagramBudget{},8));
  auto first=WriteSome(*left,"abcdef");Until([&]{return rc.Stats()->receive_bytes==6;});
  auto part=ReadSome(*right,4);Pump();EXPECT_EQ(Text(part),"abcd");
  auto second=WriteSome(*left,"ghijkl");Until([&]{return rc.Stats()->receive_bytes==8;});
  auto rest=ReadSome(*right,8);Pump();EXPECT_EQ(Text(rest),"efghijkl");
  EXPECT_EQ(rc.Stats()->receive_bytes,0u);EXPECT_EQ(rc.Stats()->receive_capacity,8u);
}
TEST_F(StreamPair,SmallWireBudgetStillMakesProgress) {
  Open(NativeUDPStreamLimits(DatagramBudget(1,24),16),{});
  auto source=std::make_shared<std::string>("abc");auto write=outcome();
  auto target=std::make_shared<std::vector<uint8_t>>(3);auto read=outcome();
  asio::async_read(*right,asio::buffer(*target),[target,read](Error e,size_t n){finish(read,e,n);});
  asio::async_write(*left,asio::buffer(*source),[source,write](Error e,size_t n){finish(write,e,n);});
  Until([&]{return std::get<0>(*read)>0;});
  EXPECT_EQ(std::string(target->begin(),target->end()),"abc");
  EXPECT_EQ(max_wire,24u);EXPECT_LE(peak_pending,1u);EXPECT_FALSE(std::get<1>(*write));
}
TEST_F(StreamPair,FullReliabilityWindowWaitsForAckWithoutDroppingNextBytes) {
  Open(NativeUDPStreamLimits(DatagramBudget(1,100),128),{});
  auto first=WriteSome(*left,"first");Pump(false);EXPECT_EQ(std::get<0>(*first),1);
  auto second=WriteSome(*left,"second");Pump(false);EXPECT_EQ(std::get<0>(*second),0);
  EXPECT_TRUE(lc.Stats()->writing);EXPECT_EQ(lc.Stats()->pending_packets,1u);
  auto [from,data]=Extract(*wire_right);Deliver(rc,from,std::move(data));
  EXPECT_EQ(std::get<0>(*second),0);
  auto [ack_source,ack]=Extract(*wire_left);Deliver(lc,ack_source,std::move(ack));
  EXPECT_EQ(std::get<0>(*second),1);EXPECT_EQ(std::get<2>(*second),6u);
  Until([&]{return rc.Stats()->receive_bytes==11;});
  auto read=ReadSome(*right,11);Pump();EXPECT_EQ(Text(read),"firstsecond");
}
TEST_F(StreamPair,OutOfOrderPacketsDeliverOnceInOriginalOrder) {
  auto a=WriteSome(*left,"a");Pump(false);auto first=Extract(*wire_right);
  auto b=WriteSome(*left,"b");Pump(false);auto second=Extract(*wire_right);
  Deliver(rc,second.first,second.second);EXPECT_EQ(rc.Stats()->receive_bytes,0u);
  EXPECT_GT(rc.Stats()->reorder_bytes,0u);
  Deliver(rc,second.first,second.second);EXPECT_EQ(rc.Stats()->receive_bytes,0u);
  Deliver(rc,first.first,first.second);EXPECT_EQ(rc.Stats()->receive_bytes,2u);
  EXPECT_EQ(rc.Stats()->reorder_bytes,0u);
  auto read=ReadSome(*right,4);Pump();EXPECT_EQ(Text(read),"ab");
  Deliver(rc,first.first,first.second);EXPECT_EQ(rc.Stats()->receive_bytes,0u);
}
TEST_F(StreamPair,BoundedWriterUsesTheSameSocketCancellationAndBackpressure) {
  BasicBoundedStreamWriter<NativeUDPSocket> writer(left,StreamBudget(2,10000),5s);
  std::string a(3000,'a'),b(3000,'b');
  auto target=std::make_shared<std::vector<uint8_t>>(6000);auto read=outcome();
  asio::async_read(*right,asio::buffer(*target),[target,read](Error e,size_t n){finish(read,e,n);});
  ASSERT_TRUE(writer.TrySend(a.data(),a.size()));ASSERT_TRUE(writer.TrySend(b.data(),b.size()));
  EXPECT_FALSE(writer.TrySend("x",1));EXPECT_EQ(writer.queued_messages(),2u);
  Until([&]{return std::get<0>(*read)>0 && writer.queued_messages()==0;});
  EXPECT_FALSE(std::get<1>(*read));EXPECT_EQ(std::string(target->begin(),target->end()),a+b);
  EXPECT_EQ(writer.queued_bytes(),0u);EXPECT_TRUE(writer.TrySend("x",1));
  writer.Close();Pump();
}

TEST_F(StreamPair,FullReorderedWindowFitsDefaultReceiveRingWhileReadCompletionIsPosted) {
  constexpr size_t fragment=kReliableUDP_MaxPacketSize-kReliableUDP_SessionHeaderSize;
  auto target=std::make_shared<std::vector<uint8_t>>(64*fragment);auto received=outcome();
  asio::async_read(*right,asio::buffer(*target),[target,received](Error e,size_t n){finish(received,e,n);});
  std::vector<std::pair<udp::endpoint,std::vector<uint8_t>>> packets;
  std::string expected;
  for(unsigned i=0;i<64;++i) {
    std::string payload(fragment,static_cast<char>('a'+i%26));expected+=payload;
    auto sent=WriteSome(*left,payload);Pump(false);
    ASSERT_EQ(std::get<0>(*sent),1);ASSERT_FALSE(std::get<1>(*sent));
    packets.push_back(Extract(*wire_right));
  }
  EXPECT_EQ(lc.Stats()->pending_packets,64u);
  for(size_t i=packets.size();i-->0;)Deliver(rc,packets[i].first,packets[i].second);
  Until([&]{return std::get<0>(*received)>0;});
  EXPECT_FALSE(std::get<1>(*received));EXPECT_TRUE(right->is_open());
  EXPECT_EQ(std::get<2>(*received),expected.size());
  EXPECT_EQ(std::string(target->begin(),target->end()),expected);
  EXPECT_LE(rc.Stats()->receive_capacity,128*1024u);
  Until([&]{return lc.Stats()->pending_packets==0;});
}
TEST_F(StreamPair,ActualDataAndAckLossRecoverWithoutDuplicateApplicationBytes) {
  auto sent=WriteSome(*left,"recover");Pump(false);
  auto lost_data=Extract(*wire_right);
  Advance(1001ms);auto retry=Extract(*wire_right);EXPECT_EQ(retry.second,lost_data.second);
  Deliver(rc,retry.first,retry.second);auto lost_ack=Extract(*wire_left);
  auto received=ReadSome(*right,16);Pump(false);EXPECT_EQ(Text(received),"recover");
  auto pending=ReadSome(*right,16);
  Advance(1001ms);auto duplicate=Extract(*wire_right);EXPECT_EQ(duplicate.second,retry.second);
  Deliver(rc,duplicate.first,duplicate.second);
  auto ack=Extract(*wire_left);EXPECT_EQ(ack.second,lost_ack.second);
  Deliver(lc,ack.first,ack.second);
  EXPECT_EQ(lc.Stats()->pending_packets,0u);EXPECT_EQ(rc.Stats()->receive_bytes,0u);
  EXPECT_EQ(std::get<0>(*pending.second),0);
  auto next=WriteSome(*left,"next");Until([&]{return std::get<0>(*pending.second)>0;});
  EXPECT_EQ(Text(pending),"next");EXPECT_TRUE(left->is_open());EXPECT_TRUE(right->is_open());
}

// 2026-09-16: selective ACK capacity must keep the asynchronous fifth write
// pending until the missing first sequence is recovered and acknowledged.
TEST_F(StreamPair,SelectiveAckWindowBackpressureResumesAfterMissingFirstPacket) {
  Open(NativeUDPStreamLimits(DatagramBudget(4,256),128),
       NativeUDPStreamLimits(DatagramBudget(4,256),128));
  std::vector<uint8_t> missing;udp::endpoint source;
  for(unsigned i=0;i<4;++i) {
    auto sent=WriteSome(*left,std::string(1,static_cast<char>('a'+i)));Pump(false);
    ASSERT_EQ(std::get<0>(*sent),1);ASSERT_FALSE(std::get<1>(*sent));
    auto packet=Extract(*wire_right);
    if(i==0){source=packet.first;missing=std::move(packet.second);continue;}
    Deliver(rc,packet.first,packet.second);
    auto ack=Extract(*wire_left);Deliver(lc,ack.first,ack.second);
  }
  ASSERT_EQ(lc.Stats()->pending_packets,1u);ASSERT_EQ(rc.Stats()->receive_bytes,0u);
  auto fifth=WriteSome(*left,"z");Pump(false);
  EXPECT_EQ(std::get<0>(*fifth),0);EXPECT_TRUE(lc.Stats()->writing);
  EXPECT_EQ(wire_right->available(),0u);
  Advance(1001ms);auto retry=Extract(*wire_right);EXPECT_EQ(retry.second,missing);
  Deliver(rc,retry.first,retry.second);EXPECT_EQ(rc.Stats()->receive_bytes,4u);
  auto ack=Extract(*wire_left);Deliver(lc,ack.first,ack.second);
  EXPECT_EQ(std::get<0>(*fifth),1);EXPECT_FALSE(std::get<1>(*fifth));
  auto last=Extract(*wire_right);Deliver(rc,last.first,last.second);
  ack=Extract(*wire_left);Deliver(lc,ack.first,ack.second);
  auto read=ReadSome(*right,16);Pump(false);EXPECT_EQ(Text(read),"abcdz");
  EXPECT_EQ(lc.Stats()->pending_packets,0u);EXPECT_TRUE(left->is_open());EXPECT_TRUE(right->is_open());
}
