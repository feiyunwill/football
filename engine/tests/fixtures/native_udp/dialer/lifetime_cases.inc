
TEST_F(DialFixture,CancelBeforeDispatchSendsNothingAndCompletesExactlyOnce) {
  auto client=Dial(listener->local_endpoint());dialer->Cancel();
  EXPECT_EQ(client->calls,0);Pulse();EXPECT_EQ(client->calls,1);
  EXPECT_EQ(client->error,asio::error::operation_aborted);
  EXPECT_EQ(listener->stats().challenges,0u);EXPECT_FALSE(dialer->stats().busy);
  for(unsigned i=0;i<100;++i)dialer->Cancel();Pulse();EXPECT_EQ(client->calls,1);
}
TEST_F(DialFixture,CancelCompletesEstablishedPendingReadAndReleasesTheBoundPort) {
  auto accepted=Accept();auto client=Dial(listener->local_endpoint());
  Until([&]{return client->calls>0 && accepted->calls>0;});ASSERT_FALSE(client->error);
  const auto local=dialer->stats().local;ASSERT_TRUE(local);
  auto read=ReadSome(*client->socket,16);dialer->Cancel();Pulse();
  EXPECT_EQ(std::get<0>(*read.second),1);EXPECT_EQ(std::get<1>(*read.second),asio::error::operation_aborted);
  EXPECT_FALSE(client->socket->is_open());EXPECT_FALSE(dialer->stats().busy);
  udp::socket rebound(io);rebound.open(local->protocol());EXPECT_NO_THROW(rebound.bind(*local));
}
TEST_F(DialFixture,DroppingReturnedStreamReleasesDialerIOWithoutExplicitCancel) {
  auto accepted=Accept();auto client=Dial(listener->local_endpoint());
  Until([&]{return client->calls>0 && accepted->calls>0;});ASSERT_FALSE(client->error);
  const auto local=dialer->stats().local;ASSERT_TRUE(local);
  client->socket.reset();Until([&]{return !dialer->stats().busy;});
  EXPECT_FALSE(dialer->stats().local);
  udp::socket rebound(io);rebound.open(local->protocol());EXPECT_NO_THROW(rebound.bind(*local));
}
TEST_F(DialFixture,DestructionCancelsAttemptAndAcceptedStreamWithoutCallbackCycles) {
  auto accepted=Accept();auto client=Dial(listener->local_endpoint());
  Until([&]{return client->calls>0 && accepted->calls>0;});ASSERT_FALSE(client->error);
  const auto local=dialer->stats().local;ASSERT_TRUE(local);
  auto read=ReadSome(*client->socket,16);dialer.reset();Pulse();
  EXPECT_EQ(std::get<0>(*read.second),1);EXPECT_FALSE(client->socket->is_open());
  udp::socket rebound(io);rebound.open(local->protocol());EXPECT_NO_THROW(rebound.bind(*local));
}
TEST_F(DialFixture,AssociatedExecutorPreservesWorkAndOwnsConnectCompletion) {
  asio::io_context callbacks;auto result=std::make_shared<Connected>();auto correct=std::make_shared<bool>(false);
  auto accepted=Accept();
  dialer->async_connect("127.0.0.1",listener->local_endpoint().port(),
    asio::bind_executor(callbacks.get_executor(),[result,correct,&callbacks](Error e,NativeUDPSocket socket) {
      ++result->calls;result->error=e;*correct=callbacks.get_executor().running_in_this_thread();
      if(!e)result->socket=std::make_unique<NativeUDPSocket>(std::move(socket));
    }));
  callbacks.poll();EXPECT_FALSE(callbacks.stopped());
  Until([&]{return dialer->stats().connected;});
  EXPECT_EQ(result->calls,0);callbacks.run();ASSERT_EQ(result->calls,1);
  EXPECT_FALSE(result->error);EXPECT_TRUE(*correct);EXPECT_TRUE(result->socket->is_open());
}
TEST_F(DialFixture,FutureTokenReturnsMoveOnlyStreamAndPropagatesCancellation) {
  auto accepted=Accept();
  auto connected=dialer->async_connect("127.0.0.1",listener->local_endpoint().port(),asio::use_future);
  Until([&]{return connected.wait_for(0ms)==std::future_status::ready;});
  auto socket=connected.get();EXPECT_TRUE(socket.is_open());
  dialer->Cancel();Pulse();EXPECT_FALSE(socket.is_open());
  auto cancelled=dialer->async_connect("127.0.0.1",listener->local_endpoint().port(),asio::use_future);
  dialer->Cancel();Pulse();EXPECT_THROW(cancelled.get(),boost::system::system_error);
}
TEST_F(DialFixture,ConcurrentRepeatedCancelCompletesPendingReadOnce) {
  auto accepted=Accept();auto client=Dial(listener->local_endpoint());
  Until([&]{return client->calls>0 && accepted->calls>0;});ASSERT_FALSE(client->error);
  auto read=ReadSome(*client->socket,16);auto* instance=dialer.get();
  std::jthread closer([instance]{for(unsigned i=0;i<100;++i)instance->Cancel();});
  Until([&]{return std::get<0>(*read.second)>0;});closer.join();Pulse();
  EXPECT_EQ(std::get<0>(*read.second),1);EXPECT_EQ(std::get<1>(*read.second),asio::error::operation_aborted);
  EXPECT_FALSE(dialer->stats().busy);
}
TEST_F(DialFixture,RepeatedPhysicalConnectionsRetireAndReleaseAllClientPorts) {
  for(unsigned i=0;i<64;++i) {
    auto accepted=Accept();auto client=Dial(listener->local_endpoint());
    Until([&]{return client->calls>0 && accepted->calls>0;});ASSERT_FALSE(client->error);
    const auto local=dialer->stats().local;ASSERT_TRUE(local);
    dialer->Cancel();Pulse();EXPECT_FALSE(dialer->stats().busy);
    udp::socket rebound(io);rebound.open(local->protocol());EXPECT_NO_THROW(rebound.bind(*local));
    accepted->socket->close();
  }
  Advance(1ms);EXPECT_EQ(listener->stats().active,0u);
  EXPECT_EQ(listener->stats().retired,64u);EXPECT_EQ(listener->stats().receive_capacity,0u);
}
