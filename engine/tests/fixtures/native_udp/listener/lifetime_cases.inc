
TEST_F(ListenerFixture,CloseBeforeAcceptCompletesAsynchronouslyExactlyOnce) {
  auto accepted=AcceptOne();EXPECT_EQ(accepted->calls,0);
  listener->close();EXPECT_FALSE(listener->is_open());EXPECT_EQ(accepted->calls,0);
  Pulse(false);EXPECT_EQ(accepted->calls,1);EXPECT_EQ(accepted->error,asio::error::operation_aborted);
  listener->close();Pulse(false);EXPECT_EQ(accepted->calls,1);
  auto rejected=AcceptOne();EXPECT_EQ(rejected->calls,0);Pulse(false);
  EXPECT_EQ(rejected->calls,1);EXPECT_EQ(rejected->error,asio::error::operation_aborted);
}
TEST_F(ListenerFixture,AcceptUsesAssociatedExecutorAndKeepsItAliveUntilCompletion) {
  asio::io_context callbacks;auto accepted=std::make_shared<Accepted>();auto on_target=std::make_shared<bool>(false);
  listener->async_accept(asio::bind_executor(callbacks.get_executor(),
    [accepted,on_target,&callbacks](Error e,NativeUDPSocket socket) {
      ++accepted->calls;accepted->error=e;
      *on_target=callbacks.get_executor().running_in_this_thread();
      if(!e)accepted->socket=std::make_unique<NativeUDPSocket>(std::move(socket));
    }));
  callbacks.poll();EXPECT_FALSE(callbacks.stopped());
  auto& peer=NewPeer();Connect(peer);
  EXPECT_EQ(accepted->calls,0);callbacks.run();
  ASSERT_EQ(accepted->calls,1);EXPECT_FALSE(accepted->error);EXPECT_TRUE(*on_target);
  EXPECT_TRUE(accepted->socket->is_open());
}
TEST_F(ListenerFixture,OverlappingAcceptRejectsOnlySecondRequest) {
  auto first=AcceptOne(),second=AcceptOne();
  EXPECT_EQ(first->calls,0);EXPECT_EQ(second->calls,0);Pulse(false);
  EXPECT_EQ(first->calls,0);EXPECT_EQ(second->calls,1);EXPECT_EQ(second->error,asio::error::already_started);
  auto& peer=NewPeer();Connect(peer);Until([&]{return first->calls>0;});
  EXPECT_FALSE(first->error);EXPECT_TRUE(first->socket->is_open());
}
TEST_F(ListenerFixture,DestructionCancelsAcceptedStreamAndPendingAcceptWithoutOwnerCycle) {
  auto accepted=AcceptOne();auto& peer=NewPeer();Connect(peer);Until([&]{return accepted->calls>0;});
  auto read=ReadSome(*accepted->socket,16);auto pending=AcceptOne();
  const auto endpoint=listener->local_endpoint();
  listener.reset();Pulse(false);
  EXPECT_FALSE(accepted->socket->is_open());
  EXPECT_EQ(std::get<0>(*read.second),1);EXPECT_EQ(std::get<1>(*read.second),asio::error::operation_aborted);
  EXPECT_EQ(pending->calls,1);EXPECT_EQ(pending->error,asio::error::operation_aborted);
  udp::socket rebound(io);rebound.open(endpoint.protocol());
  EXPECT_NO_THROW(rebound.bind(endpoint));
  accepted->socket.reset();Pulse(false);
}
TEST_F(ListenerFixture,CloseFromAnotherThreadClosesWireOnItsExecutor) {
  auto accepted=AcceptOne();auto& peer=NewPeer();Connect(peer);Until([&]{return accepted->calls>0;});
  auto read=ReadSome(*accepted->socket,16);const auto endpoint=listener->local_endpoint();
  auto* instance=listener.get();
  std::jthread closer([instance]{for(unsigned i=0;i<100;++i)instance->close();});
  Until([&]{return std::get<0>(*read.second)>0;},false);closer.join();Pulse(false);
  EXPECT_EQ(std::get<0>(*read.second),1);EXPECT_FALSE(listener->is_open());
  udp::socket rebound(io);rebound.open(endpoint.protocol());EXPECT_NO_THROW(rebound.bind(endpoint));
}
