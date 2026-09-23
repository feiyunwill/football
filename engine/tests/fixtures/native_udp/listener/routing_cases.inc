
TEST_F(ListenerFixture,LargeActualStreamRoundTripPreservesEveryByte) {
  // 2026-09-16: do not freeze retransmission time during real socket transfer.
  realtime_transfer=true;
  auto accepted=AcceptOne();auto& peer=NewPeer();Connect(peer);Until([&]{return accepted->calls>0;});
  auto source=std::make_shared<std::vector<uint8_t>>(1024*1024);
  for(size_t i=0;i<source->size();++i)(*source)[i]=static_cast<uint8_t>((i*31+i/41)%251);
  auto server=std::make_shared<std::vector<uint8_t>>(source->size());
  auto received=outcome(),sent=outcome();
  asio::async_read(*accepted->socket,asio::buffer(*server),[server,received](Error e,size_t n){finish(received,e,n);});
  asio::async_write(*peer.stream,asio::buffer(*source),[source,sent](Error e,size_t n){finish(sent,e,n);});
  Until([&]{return std::get<0>(*received)>0 && std::get<0>(*sent)>0;});
  // 2026-09-21: preserve the original outgoing failure reason before later close effects.
  // EXPECT_FALSE(std::get<1>(*received));EXPECT_FALSE(std::get<1>(*sent));EXPECT_EQ(*source,*server);
  EXPECT_FALSE(std::get<1>(*received))<<std::get<1>(*received).message();
  EXPECT_FALSE(std::get<1>(*sent))<<std::get<1>(*sent).message()
    <<" client_open="<<peer.stream->is_open()<<" pending="<<peer.stream->control().Stats()->pending_packets;
  EXPECT_EQ(*source,*server);
  auto client=std::make_shared<std::vector<uint8_t>>(source->size());auto echoed=outcome(),written=outcome();
  asio::async_read(*peer.stream,asio::buffer(*client),[client,echoed](Error e,size_t n){finish(echoed,e,n);});
  asio::async_write(*accepted->socket,asio::buffer(*server),[server,written](Error e,size_t n){finish(written,e,n);});
  Until([&]{return std::get<0>(*echoed)>0 && std::get<0>(*written)>0;});
  // 2026-09-16: preserve transport error information on a real-transfer failure.
  // EXPECT_FALSE(std::get<1>(*echoed));EXPECT_FALSE(std::get<1>(*written));EXPECT_EQ(*source,*client);
  EXPECT_FALSE(std::get<1>(*echoed))<<std::get<1>(*echoed).message()
    <<" client_open="<<peer.stream->is_open()<<" receive="<<peer.stream->control().Stats()->receive_bytes
    <<" reorder="<<peer.stream->control().Stats()->reorder_bytes;
  EXPECT_FALSE(std::get<1>(*written))<<std::get<1>(*written).message();
  EXPECT_EQ(*source,*client);
  Until([&]{return listener->stats().pending_bytes==0 && peer.stream->control().Stats()->pending_bytes==0;});
  EXPECT_LE(listener->stats().receive_capacity,128*1024u);
}
TEST_F(ListenerFixture,EndpointAndGenerationAreBothRequiredBeforeApplicationDelivery) {
  auto accepted=AcceptOne();auto& peer=NewPeer();Connect(peer);Until([&]{return accepted->calls>0;});
  auto& stranger=NewPeer();const auto packet=Packet(*peer.attempt->connection(),"valid");
  auto read=ReadSome(*accepted->socket,16);
  // 2026-09-15: wait for the rejected/ignored packet to be processed before asserting no effect.
  //   stranger.Send(packet);Pulse(false);EXPECT_EQ(std::get<0>(*read.second),0);
  const auto ignored=listener->stats().ignored;
  stranger.Send(packet);Until([&]{return listener->stats().ignored>ignored;},false);
  EXPECT_EQ(std::get<0>(*read.second),0);
  EXPECT_EQ(stranger.wire->available(),0u);EXPECT_EQ(peer.wire->available(),0u);
  peer.Send(packet);Until([&]{return std::get<0>(*read.second)>0;});
  EXPECT_EQ(Text(read),"valid");EXPECT_EQ(listener->stats().active,1u);
}
TEST_F(ListenerFixture,ClosingOneStreamPreservesOtherLivePeerAndListener) {
  auto a=AcceptOne();auto& p=NewPeer();Connect(p);Until([&]{return a->calls>0;});
  auto b=AcceptOne();auto& q=NewPeer();Connect(q);Until([&]{return b->calls>0;});
  a->socket->close();Advance(1ms);
  EXPECT_EQ(listener->stats().active,1u);EXPECT_TRUE(listener->is_open());
  auto read=ReadSome(*b->socket,16);auto sent=WriteSome(*q.stream,"still alive");
  Until([&]{return std::get<0>(*read.second)>0;});
  EXPECT_EQ(Text(read),"still alive");EXPECT_FALSE(std::get<1>(*sent));
  EXPECT_TRUE(b->socket->is_open());
}
TEST_F(ListenerFixture,ReusedPhysicalEndpointRejectsOldDataAndConfirmation) {
  auto old=AcceptOne();auto& peer=NewPeer();Connect(peer);Until([&]{return old->calls>0;});
  const auto old_data=Packet(*peer.attempt->connection(),"stale");
  const auto old_confirm=peer.confirm;const auto endpoint=peer.wire->local_endpoint();
  old->socket->close();Advance(1ms);peer.Reset();
  auto fresh=AcceptOne();Connect(peer);Until([&]{return fresh->calls>0;});
  EXPECT_EQ(peer.wire->local_endpoint(),endpoint);
  auto read=ReadSome(*fresh->socket,16);
  // 2026-09-15: wait for the rejected/ignored packet to be processed before asserting no effect.
  //   peer.Send(old_data);peer.Send(old_confirm);Pulse(false);
  const auto ignored=listener->stats().ignored,rejected=listener->stats().rejected;
  peer.Send(old_data);peer.Send(old_confirm);
  Until([&]{return listener->stats().ignored>ignored && listener->stats().rejected>rejected;},false);
  EXPECT_EQ(std::get<0>(*read.second),0);EXPECT_EQ(peer.wire->available(),0u);
  auto sent=WriteSome(*peer.stream,"fresh");Until([&]{return std::get<0>(*read.second)>0;});
  EXPECT_EQ(Text(read),"fresh");EXPECT_EQ(listener->stats().active,1u);
}
TEST_F(ListenerFixture,TimerExhaustionClosesOnlyTimedOutChannelAndFinishesOperations) {
  auto limits=NativeUDPListenerLimits{};limits.stream.datagrams=DatagramBudget(1,64);Open(limits);
  auto accepted=AcceptOne();auto& peer=NewPeer();Connect(peer);Until([&]{return accepted->calls>0;});
  auto first=WriteSome(*accepted->socket,"first");Pulse(false);
  const auto packet=Extract(*peer.wire).second;
  auto read=ReadSome(*accepted->socket,16);auto write=WriteSome(*accepted->socket,"blocked");Pulse(false);
  for(unsigned i=0;i<5;++i) {
    Advance(1001ms,false);ASSERT_TRUE(accepted->socket->is_open());
    EXPECT_EQ(Extract(*peer.wire).second,packet);EXPECT_EQ(std::get<0>(*write),0);
  }
  Advance(1001ms,false);
  EXPECT_EQ(std::get<0>(*read.second),1);EXPECT_EQ(std::get<0>(*write),1);
  EXPECT_EQ(std::get<1>(*read.second),asio::error::timed_out);
  EXPECT_EQ(std::get<1>(*write),asio::error::timed_out);
  EXPECT_FALSE(accepted->socket->is_open());EXPECT_TRUE(listener->is_open());
  EXPECT_EQ(listener->stats().active,0u);EXPECT_EQ(listener->stats().pending_bytes,0u);
}
TEST_F(ListenerFixture,AcceptedChannelOutlivesBootstrapCookieDeadline) {
  auto accepted=AcceptOne();auto& peer=NewPeer();Connect(peer);Until([&]{return accepted->calls>0;});
  Advance(30001ms);
  EXPECT_TRUE(accepted->socket->is_open());EXPECT_EQ(listener->stats().active,1u);
  auto read=ReadSome(*accepted->socket,16);auto sent=WriteSome(*peer.stream,"alive");
  Until([&]{return std::get<0>(*read.second)>0;});EXPECT_EQ(Text(read),"alive");
}
TEST_F(ListenerFixture,LostEstablishedReplyRecoversWithoutAcceptingTwice) {
  auto accepted=AcceptOne();auto& peer=NewPeer();Challenge(peer);
  peer.Send(peer.confirm);Until([&]{return peer.wire->available()>0;},false);
  const auto lost=Extract(*peer.wire).second;
  EXPECT_EQ(peer.attempt->state(),NativeUDPBootstrapAttempt::State::AwaitEstablished);
  EXPECT_EQ(accepted->calls,1);EXPECT_EQ(listener->stats().active,1u);
  Confirm(peer);EXPECT_EQ(listener->stats().duplicates,1u);EXPECT_EQ(accepted->calls,1);
  EXPECT_EQ(lost.size(),64u);
  auto read=ReadSome(*accepted->socket,16);auto sent=WriteSome(*peer.stream,"recovered");
  Until([&]{return std::get<0>(*read.second)>0;});EXPECT_EQ(Text(read),"recovered");
}
