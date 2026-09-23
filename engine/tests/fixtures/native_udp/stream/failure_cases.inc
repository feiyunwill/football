
TEST_F(StreamPair,InvalidLimitsAndIdentityFailBeforeAffectingSharedSocket) {
  EXPECT_THROW(NativeUDPStreamLimits(DatagramBudget{},0),std::invalid_argument);
  EXPECT_THROW(NativeUDPStreamLimits(DatagramBudget{},1024*1024+1),std::invalid_argument);
  auto invalid=NativeUDPStreamLimits{};invalid.datagrams.packet_limit=0;
  EXPECT_THROW(NativeUDPSocket(wire_left,wire_right->local_endpoint(),owner,Id(1),invalid),std::invalid_argument);
  EXPECT_THROW(NativeUDPSocket(wire_left,wire_right->local_endpoint(),owner,Id(0)),std::invalid_argument);
  EXPECT_THROW(NativeUDPSocket(wire_left,wire_right->local_endpoint(),owner,Id(1),
    NativeUDPStreamLimits(DatagramBudget(1,23),8)),std::invalid_argument);
  EXPECT_THROW(NativeUDPSocket(wire_left,udp::endpoint{},owner,Id(1)),std::invalid_argument);
  EXPECT_TRUE(wire_left->is_open());EXPECT_TRUE(left->is_open());EXPECT_EQ(wire_right->available(),0u);
}
TEST_F(StreamPair,ReceiveOverflowClosesOnlyTheOverloadedStream) {
  Open({},NativeUDPStreamLimits(DatagramBudget{},8));
  auto sent=WriteSome(*left,"123456789");
  Until([&]{return !right->is_open();});
  EXPECT_TRUE(wire_right->is_open());EXPECT_TRUE(wire_left->is_open());
  EXPECT_EQ(rc.Stats()->receive_capacity,0u);EXPECT_EQ(rc.Stats()->reorder_bytes,0u);
  auto read=ReadSome(*right,4);Pump(false);EXPECT_EQ(std::get<1>(*read.second),asio::error::operation_aborted);
  Open({}, {},2);auto fresh=ReadSome(*right,4);auto write=WriteSome(*left,"next");
  Until([&]{return std::get<0>(*fresh.second)>0;});EXPECT_EQ(Text(fresh),"next");
}
TEST_F(StreamPair,RetransmissionExhaustionFailsBlockedReadAndWriteOnce) {
  Open(NativeUDPStreamLimits(DatagramBudget(1,64),128),{});
  auto first=WriteSome(*left,"first");Pump(false);auto original=Extract(*wire_right).second;
  auto read=ReadSome(*left,8);auto next=WriteSome(*left,"next");Pump(false);
  for(unsigned i=0;i<5;++i) {
    Advance(1001ms);ASSERT_TRUE(left->is_open());
    auto resent=Extract(*wire_right).second;EXPECT_EQ(resent,original);
    EXPECT_EQ(std::get<0>(*next),0);
  }
  Advance(1001ms);
  EXPECT_FALSE(left->is_open());EXPECT_EQ(std::get<0>(*read.second),1);EXPECT_EQ(std::get<0>(*next),1);
  EXPECT_EQ(std::get<1>(*read.second),asio::error::timed_out);EXPECT_EQ(std::get<1>(*next),asio::error::timed_out);
  EXPECT_EQ(lc.Stats()->pending_bytes,0u);EXPECT_EQ(lc.Stats()->receive_capacity,0u);
  EXPECT_TRUE(wire_left->is_open());Advance(1001ms);EXPECT_EQ(std::get<0>(*next),1);
}
TEST_F(StreamPair,ForeignEndpointCannotDeliverValidIdentityOrEmitAck) {
  auto sent=WriteSome(*left,"valid");Pump(false);auto packet=Extract(*wire_right);
  udp::socket stranger(io,udp::endpoint(asio::ip::make_address("127.0.0.1"),0));
  stranger.send_to(asio::buffer(packet.second),wire_right->local_endpoint());
  auto forged=Extract(*wire_right);Deliver(rc,forged.first,forged.second);
  EXPECT_EQ(rc.Stats()->receive_bytes,0u);EXPECT_EQ(wire_left->available(),0u);
  Deliver(rc,packet.first,packet.second);
  auto read=ReadSome(*right,8);Pump();EXPECT_EQ(Text(read),"valid");
}
TEST_F(StreamPair,OldGenerationDataAckAndWeakCallbackCannotChangeFreshStream) {
  auto old_control=lc;
  auto first=WriteSome(*left,"old");Pump(false);auto old_data=Extract(*wire_right);
  Deliver(rc,old_data.first,old_data.second);auto old_ack=Extract(*wire_left);
  Open({}, {},2);
  auto current=WriteSome(*left,"new");Pump(false);auto new_data=Extract(*wire_right);
  Deliver(lc,old_ack.first,old_ack.second);EXPECT_EQ(lc.Stats()->pending_packets,1u);
  Deliver(rc,old_data.first,old_data.second);EXPECT_EQ(rc.Stats()->receive_bytes,0u);EXPECT_EQ(wire_left->available(),0u);
  EXPECT_FALSE(old_control.Stats());
  Deliver(old_control,new_data.first,new_data.second);EXPECT_EQ(lc.Stats()->pending_packets,1u);
  // 2026-09-15: a poll after application delivery need not include the later wire ACK.
  // Deliver(rc,new_data.first,new_data.second);auto received=ReadSome(*right,8);Pump();
  // EXPECT_EQ(Text(received),"new");EXPECT_EQ(lc.Stats()->pending_packets,0u);
  Deliver(rc,new_data.first,new_data.second);
  auto new_ack=Extract(*wire_left);
  EXPECT_NE(new_ack.second,old_ack.second);
  Deliver(lc,new_ack.first,new_ack.second);
  auto received=ReadSome(*right,8);Pump(false);
  EXPECT_EQ(Text(received),"new");EXPECT_EQ(lc.Stats()->pending_packets,0u);
}
TEST_F(StreamPair,TruncatedDatagramsDoNotMutateStreamOrPendingWrites) {
  auto sent=WriteSome(*left,"packet");Pump(false);auto packet=Extract(*wire_right);
  for(size_t n=0;n<packet.second.size();++n)
    Deliver(rc,packet.first,std::vector<uint8_t>(packet.second.begin(),packet.second.begin()+n));
  EXPECT_TRUE(right->is_open());EXPECT_EQ(rc.Stats()->receive_bytes,0u);
  EXPECT_EQ(wire_left->available(),0u);EXPECT_EQ(lc.Stats()->pending_packets,1u);
  Deliver(rc,packet.first,packet.second);auto read=ReadSome(*right,8);Pump();EXPECT_EQ(Text(read),"packet");
}
TEST_F(StreamPair,ActualSharedSocketFailureReleasesAllPendingOperations) {
  auto read=ReadSome(*left,8);wire_left->close();auto sent=WriteSome(*left,"x");Pump(false);
  EXPECT_FALSE(left->is_open());
  EXPECT_EQ(std::get<0>(*read.second),1);EXPECT_EQ(std::get<0>(*sent),1);
  EXPECT_TRUE(std::get<1>(*read.second));EXPECT_TRUE(std::get<1>(*sent));
  EXPECT_EQ(lc.Stats()->receive_capacity,0u);EXPECT_EQ(lc.Stats()->pending_bytes,0u);
  EXPECT_TRUE(right->is_open());
}
TEST_F(StreamPair,DatagramAndRetransmitCallsRequireListenerExecutor) {
  EXPECT_THROW(lc.Deliver(wire_right->local_endpoint(),{}),std::logic_error);
  EXPECT_THROW(lc.Tick(),std::logic_error);
  EXPECT_TRUE(left->is_open());EXPECT_EQ(lc.Stats()->pending_packets,0u);
}
