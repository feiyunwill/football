
TEST_F(ListenerFixture,InvalidLimitsOrUnavailableEntropyCannotOpenListener) {
  auto limits=NativeUDPListenerLimits{};limits.connections=0;
  const auto endpoint=udp::endpoint(asio::ip::make_address("127.0.0.1"),0);
  EXPECT_THROW(NativeUDPAcceptor(io,endpoint,limits),std::invalid_argument);
  limits.connections=129;EXPECT_THROW(NativeUDPAcceptor(io,endpoint,limits),std::invalid_argument);
  limits={};limits.stream.datagrams.byte_limit=23;
  EXPECT_THROW(NativeUDPAcceptor(io,endpoint,limits),std::invalid_argument);
  // 2026-09-15: Entropy is bool(*)(span<uint8_t>) noexcept; prior test callback:
  // auto failed=[](std::span<uint8_t>){return false;};
  auto failed=[](std::span<uint8_t>) noexcept {return false;};
  EXPECT_THROW(NativeUDPAcceptor(io,endpoint,{},ReliableUDPChannel::Clock::now,failed),std::runtime_error);
  EXPECT_TRUE(listener->is_open());EXPECT_EQ(listener->stats().active,0u);
}
TEST_F(ListenerFixture,HelloFloodHasFixedReplySizeAndAllocatesNoChannel) {
  auto& peer=NewPeer();auto hello=*peer.attempt->next_packet(0);
  for(unsigned i=0;i<1024;++i) {
    peer.Send(hello);Until([&]{return peer.wire->available()>0;},false);
    const auto packet=Extract(*peer.wire).second;EXPECT_EQ(packet.size(),64u);
    const auto stats=listener->stats();EXPECT_EQ(stats.active,0u);
    EXPECT_EQ(stats.unaccepted,0u);EXPECT_EQ(stats.pending_bytes,0u);EXPECT_EQ(stats.receive_capacity,0u);
  }
  EXPECT_EQ(listener->stats().challenges,1024u);EXPECT_EQ(listener->stats().accepted,0u);
}
TEST_F(ListenerFixture,MalformedAndUnprovenTrafficCannotAllocateOrPoisonNextHandshake) {
  // 2026-09-15: raw loopback diagnostic receives 1201 bytes but never 4096.
  // Keep the exact protocol boundary assertion on a physically deliverable packet.
  // auto& peer=NewPeer();std::vector<uint8_t> oversized(4096,0);
  auto& peer=NewPeer();
  std::vector<uint8_t> oversized(kReliableUDP_MaxPacketSize+1,0);
  // 2026-09-15: wait for the rejected/ignored packet to be processed before asserting no effect.
  //   peer.Send(oversized);Pulse(false);
  auto ignored=listener->stats().ignored;
  peer.Send(oversized);Until([&]{return listener->stats().ignored>ignored;},false);
  for(size_t n=0;n<64;++n) {
    SCOPED_TRACE("truncated Hello bytes="+std::to_string(n));
  // 2026-09-15: wait for the rejected/ignored packet to be processed before asserting no effect.
  //     const auto hello=*peer.attempt->next_packet(0);peer.Send(std::span(hello.data(),n));Pulse(false);
    const auto hello=*peer.attempt->next_packet(0);ignored=listener->stats().ignored;
    peer.Send(std::span(hello.data(),n));Until([&]{return listener->stats().ignored>ignored;},false);
  }
  auto forged=native_udp_bootstrap::decode(*peer.attempt->next_packet(0));ASSERT_TRUE(forged);
  forged->kind=NativeUDPBootstrapKind::Confirm;forged->expires=10000;forged->cookie.fill(7);
  // 2026-09-15: wait for the rejected/ignored packet to be processed before asserting no effect.
  //   peer.Send(native_udp_bootstrap::encode(*forged));Pulse(false);
  const auto rejected=listener->stats().rejected;
  peer.Send(native_udp_bootstrap::encode(*forged));Until([&]{return listener->stats().rejected>rejected;},false);
  EXPECT_EQ(listener->stats().active,0u);EXPECT_EQ(peer.wire->available(),0u);
  auto accepted=AcceptOne();Connect(peer);Until([&]{return accepted->calls>0;});
  EXPECT_FALSE(accepted->error);EXPECT_TRUE(accepted->socket->is_open());
}
TEST_F(ListenerFixture,PendingAcceptCompletesOnlyAfterReturnRouteProof) {
  auto accepted=AcceptOne();auto& peer=NewPeer();
  Challenge(peer);EXPECT_EQ(accepted->calls,0);EXPECT_EQ(listener->stats().active,0u);
  Confirm(peer);Until([&]{return accepted->calls>0;});
  EXPECT_EQ(accepted->calls,1);EXPECT_FALSE(accepted->error);
  EXPECT_EQ(listener->stats().active,1u);EXPECT_EQ(listener->stats().unaccepted,0u);
  EXPECT_EQ(accepted->socket->remote_endpoint(),peer.wire->local_endpoint());
}
TEST_F(ListenerFixture,CompletedHandshakeWaitsWithinBoundedAcceptBacklog) {
  auto& peer=NewPeer();Connect(peer);
  EXPECT_EQ(listener->stats().active,1u);EXPECT_EQ(listener->stats().unaccepted,1u);
  auto accepted=AcceptOne();EXPECT_EQ(accepted->calls,0);
  Pulse();ASSERT_EQ(accepted->calls,1);EXPECT_FALSE(accepted->error);
  EXPECT_EQ(listener->stats().unaccepted,0u);EXPECT_TRUE(accepted->socket->is_open());
}
TEST_F(ListenerFixture,DuplicateConfirmationDoesNotCreateASecondAcceptedStream) {
  auto accepted=AcceptOne();auto& peer=NewPeer();Connect(peer);Until([&]{return accepted->calls>0;});
  auto another=AcceptOne();peer.Send(peer.confirm);
  Until([&]{return peer.wire->available()>0;},false);
  const auto duplicate=Extract(*peer.wire).second;
  EXPECT_FALSE(peer.attempt->receive(duplicate,*native_udp_bootstrap::address(peer.server),0));
  EXPECT_EQ(listener->stats().duplicates,1u);EXPECT_EQ(listener->stats().active,1u);
  EXPECT_EQ(another->calls,0);EXPECT_EQ(accepted->calls,1);
  auto read=ReadSome(*accepted->socket,16);auto write=WriteSome(*peer.stream,"preserved");
  Until([&]{return std::get<0>(*read.second)>0;});EXPECT_EQ(Text(read),"preserved");
}
TEST_F(ListenerFixture,RetiredConnectionsRemainCapacityBoundedUntilCookieExpiry) {
  auto limits=NativeUDPListenerLimits{};limits.connections=2;Open(limits);
  auto a=AcceptOne();auto& p=NewPeer();Connect(p);Until([&]{return a->calls>0;});
  auto b=AcceptOne();auto& q=NewPeer();Connect(q);Until([&]{return b->calls>0;});
  a->socket->close();b->socket->close();Advance(1ms);
  EXPECT_EQ(listener->stats().active,0u);EXPECT_EQ(listener->stats().retired,2u);
  auto& r=NewPeer();Challenge(r);auto rejected_before=listener->stats().rejected;r.Send(r.confirm);
  Until([&]{return listener->stats().rejected>rejected_before;},false);
  EXPECT_EQ(r.wire->available(),0u);EXPECT_EQ(listener->stats().retired,2u);
  Advance(30001ms);r.Reset();auto fresh=AcceptOne();Connect(r);Until([&]{return fresh->calls>0;});
  EXPECT_FALSE(fresh->error);EXPECT_EQ(listener->stats().retired,0u);
}
TEST_F(ListenerFixture,UnacceptedTimeoutRetiresConnectionWithoutRevivingOnConfirmReplay) {
  auto limits=NativeUDPListenerLimits{};limits.unaccepted_timeout_ms=50;Open(limits);
  auto& peer=NewPeer();Connect(peer);EXPECT_EQ(listener->stats().unaccepted,1u);
  Advance(51ms);EXPECT_EQ(listener->stats().active,0u);EXPECT_EQ(listener->stats().retired,1u);
  EXPECT_EQ(listener->stats().receive_capacity,0u);
  // 2026-09-15: wait for the rejected/ignored packet to be processed before asserting no effect.
  //   peer.Send(peer.confirm);Pulse(false);EXPECT_EQ(peer.wire->available(),0u);
  const auto rejected=listener->stats().rejected;
  peer.Send(peer.confirm);Until([&]{return listener->stats().rejected>rejected;},false);
  EXPECT_EQ(peer.wire->available(),0u);
  EXPECT_EQ(listener->stats().active,0u);
}
