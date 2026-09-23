
TEST_F(DialFixture,NumericAddressEstablishesOneScopedStreamAsynchronously) {
  auto accepted=Accept();auto client=Dial(listener->local_endpoint());
  EXPECT_EQ(client->calls,0);Until([&]{return client->calls>0 && accepted->calls>0;});
  ASSERT_FALSE(client->error);ASSERT_FALSE(accepted->error);
  EXPECT_TRUE(client->socket->is_open());EXPECT_EQ(client->socket->remote_endpoint(),listener->local_endpoint());
  const auto stats=dialer->stats();EXPECT_TRUE(stats.busy);EXPECT_TRUE(stats.connected);
  EXPECT_EQ(stats.physical_attempts,1u);EXPECT_EQ(stats.resolved_endpoints,1u);
  EXPECT_EQ(listener->stats().accepted,1u);
}
TEST_F(DialFixture,InvalidLimitsAndHostFailWithoutStartingNetworkWork) {
  auto limits=NativeUDPDialLimits{};limits.timeout_ms=0;
  EXPECT_THROW(NativeUDPDialer(io,limits),std::invalid_argument);
  limits.timeout_ms=30001;EXPECT_THROW(NativeUDPDialer(io,limits),std::invalid_argument);
  const auto completion=[](Error,NativeUDPSocket){};
  EXPECT_THROW(dialer->async_connect("",1234,completion),std::invalid_argument);
  EXPECT_THROW(dialer->async_connect("127.0.0.1",0,completion),std::invalid_argument);
  EXPECT_THROW(dialer->async_connect(std::string(256,'a'),1234,completion),std::invalid_argument);
  EXPECT_THROW(dialer->async_connect(std::string("localhost")+char{}+"other",1234,completion),std::invalid_argument);
  EXPECT_FALSE(dialer->stats().busy);EXPECT_EQ(listener->stats().challenges,0u);
}
TEST_F(DialFixture,HostnameResolutionConnectsUsingABoundedEndpointList) {
  auto accepted=Accept();auto client=std::make_shared<Connected>();
  dialer->async_connect("localhost",listener->local_endpoint().port(),[client](Error e,NativeUDPSocket socket) {
    ++client->calls;client->error=e;
    if(!e)client->socket=std::make_unique<NativeUDPSocket>(std::move(socket));
  });
  Until([&]{return client->calls>0;});ASSERT_FALSE(client->error);
  Until([&]{return accepted->calls>0;});
  EXPECT_GE(dialer->stats().resolved_endpoints,1u);
  EXPECT_LE(dialer->stats().resolved_endpoints,NativeUDPEndpoints::kCapacity);
}
TEST_F(DialFixture,MultipleResolvedEndpointsFallbackAndIgnoreOldPhysicalCallbacks) {
  udp::socket blackhole(io,udp::endpoint(asio::ip::make_address("127.0.0.1"),0));
  blackhole.non_blocking(true);
  const std::array<udp::endpoint,2> endpoints{blackhole.local_endpoint(),listener->local_endpoint()};
  auto accepted=Accept();auto client=Dial(NativeUDPEndpoints(endpoints));Pulse();
  // 2026-09-15: one io_context poll does not guarantee actual socket readability.
  // ASSERT_EQ(dialer->stats().physical_attempts,1u);ASSERT_GT(blackhole.available(),0u);
  Until([&]{return blackhole.available()>0;});
  ASSERT_EQ(dialer->stats().physical_attempts,1u);ASSERT_GT(blackhole.available(),0u);
  auto [source,hello]=Relay::Extract(blackhole);
  NativeUDPBootstrapSigner signer(30000);
  auto late=signer.challenge(hello,*native_udp_bootstrap::address(source),1000);ASSERT_TRUE(late);
  blackhole.send_to(asio::buffer(*late),source);
  Advance(1501ms);Until([&]{return client->calls>0 && accepted->calls>0;});
  ASSERT_FALSE(client->error);EXPECT_EQ(dialer->stats().physical_attempts,2u);
  EXPECT_EQ(client->socket->remote_endpoint(),listener->local_endpoint());
  blackhole.send_to(asio::buffer(*late),source);Pulse();
  auto read=ReadSome(*accepted->socket,16);auto sent=WriteSome(*client->socket,"current");
  Until([&]{return std::get<0>(*read.second)>0;});EXPECT_EQ(Text(read),"current");
  EXPECT_EQ(client->calls,1);
}
TEST_F(DialFixture,HandshakeRetriesCannotExtendTheAbsoluteConnectionDeadline) {
  auto limits=NativeUDPDialLimits{};limits.timeout_ms=450;ResetDialer(limits);
  udp::socket blackhole(io,udp::endpoint(asio::ip::make_address("127.0.0.1"),0));
  auto client=Dial(blackhole.local_endpoint());Pulse();const auto deadline=dialer->stats().deadline_ms;
  Advance(110ms);Advance(110ms);
  EXPECT_EQ(client->calls,0);EXPECT_EQ(dialer->stats().deadline_ms,deadline);
  EXPECT_GE(dialer->stats().handshake_packets,3u);
  Advance(500ms);Until([&]{return client->calls>0;});
  EXPECT_EQ(client->error,asio::error::timed_out);EXPECT_EQ(client->calls,1);
  EXPECT_FALSE(dialer->stats().busy);EXPECT_FALSE(dialer->stats().connected);
}
TEST_F(DialFixture,OverlappingDialRejectsSecondAndAllowsReuseAfterCancellation) {
  udp::socket blackhole(io,udp::endpoint(asio::ip::make_address("127.0.0.1"),0));
  auto first=Dial(blackhole.local_endpoint()),second=Dial(listener->local_endpoint());
  EXPECT_EQ(second->calls,0);Pulse();
  EXPECT_EQ(first->calls,0);EXPECT_EQ(second->calls,1);EXPECT_EQ(second->error,asio::error::already_started);
  dialer->Cancel();Pulse();EXPECT_EQ(first->calls,1);EXPECT_EQ(first->error,asio::error::operation_aborted);
  auto accepted=Accept();auto fresh=Dial(listener->local_endpoint());
  Until([&]{return fresh->calls>0 && accepted->calls>0;});EXPECT_FALSE(fresh->error);
}
TEST_F(DialFixture,UnavailableEntropyFailsClosedBeforeSendingHello) {
  dialer->Cancel();Pulse();dialer.reset();Pulse();
  auto failed=[](std::span<uint8_t>) noexcept {return false;};
  dialer=std::make_unique<NativeUDPDialer>(io,NativeUDPDialLimits{},[this]{return Now();},failed);
  auto result=Dial(listener->local_endpoint());Until([&]{return result->calls>0;});
  EXPECT_TRUE(result->error);EXPECT_EQ(result->calls,1);
  EXPECT_EQ(listener->stats().challenges,0u);EXPECT_EQ(listener->stats().active,0u);
  EXPECT_FALSE(dialer->stats().busy);
}
TEST_F(DialFixture,EveryHandshakeDatagramCanBeLostOnceWithoutDuplicateAcceptance) {
  relay=std::make_unique<Relay>(io,listener->local_endpoint());
  relay->drop_bootstrap_once=(1u<<1)|(1u<<2)|(1u<<3)|(1u<<4);
  auto accepted=Accept();auto client=Dial(relay->down.local_endpoint());
  Until([&]{return client->calls>0 && accepted->calls>0;});
  ASSERT_FALSE(client->error);EXPECT_EQ(relay->dropped,4u);EXPECT_EQ(relay->drop_bootstrap_once,0u);
  EXPECT_EQ(accepted->calls,1);EXPECT_EQ(listener->stats().active,1u);
  EXPECT_GE(dialer->stats().handshake_packets,6u);
}
TEST_F(DialFixture,ServerClockEpochIsOpaqueToClientHandshake) {
  server_epoch=500000;
  auto accepted=Accept();auto client=Dial(listener->local_endpoint());
  Until([&]{return client->calls>0 && accepted->calls>0;});
  EXPECT_FALSE(client->error);EXPECT_TRUE(dialer->stats().connected);
}
TEST_F(DialFixture,MutatedResolvedEndpointCountCannotOverflowFixedStorage) {
  NativeUDPEndpoints bad;bad.count=std::numeric_limits<size_t>::max();
  const auto endpoint=listener->local_endpoint();bad.Add(endpoint);
  EXPECT_EQ(bad.count,std::numeric_limits<size_t>::max());
  EXPECT_THROW(Dial(bad),std::invalid_argument);
  bad={};bad.count=1;EXPECT_THROW(Dial(bad),std::invalid_argument);
  EXPECT_FALSE(dialer->stats().busy);
}
TEST_F(DialFixture,ResolverCancellationCompletesOnceBeforeAnEndpointCanBeInstalled) {
  auto result=std::make_shared<Connected>();
  dialer->async_connect("localhost",listener->local_endpoint().port(),[result](Error e,NativeUDPSocket socket) {
    ++result->calls;result->error=e;
    if(!e)result->socket=std::make_unique<NativeUDPSocket>(std::move(socket));
  });
  auto* instance=dialer.get();asio::post(dialer->get_executor(),[instance]{instance->Cancel();});
  Until([&]{return result->calls>0;});
  EXPECT_EQ(result->calls,1);EXPECT_EQ(result->error,asio::error::operation_aborted);
  EXPECT_EQ(listener->stats().active,0u);EXPECT_FALSE(dialer->stats().busy);
}
