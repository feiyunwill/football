
TEST_F(StreamPair,CloseBeforeDispatchCompletesEachOperationOnceWithoutSending) {
  auto read=ReadSome(*left,8);auto write=WriteSome(*left,"unsent");
  EXPECT_EQ(std::get<0>(*read.second),0);EXPECT_EQ(std::get<0>(*write),0);
  left->close();EXPECT_FALSE(left->is_open());Pump(false);
  EXPECT_EQ(std::get<0>(*read.second),1);EXPECT_EQ(std::get<1>(*read.second),asio::error::operation_aborted);
  EXPECT_EQ(std::get<0>(*write),1);EXPECT_EQ(std::get<1>(*write),asio::error::operation_aborted);
  EXPECT_EQ(wire_right->available(),0u);EXPECT_TRUE(wire_left->is_open());
  EXPECT_EQ(lc.Stats()->pending_bytes,0u);EXPECT_EQ(lc.Stats()->receive_capacity,0u);
  left->close();Pump(false);EXPECT_EQ(std::get<0>(*write),1);
}
TEST_F(StreamPair,OverlappingOperationsRejectOnlyTheSecondRequest) {
  auto read=ReadSome(*right,4),duplicate_read=ReadSome(*right,4);
  auto write=WriteSome(*left,"x"),duplicate_write=WriteSome(*left,"y");
  EXPECT_EQ(std::get<0>(*duplicate_write),0);
  Until([&]{return std::get<0>(*read.second)>0;});
  EXPECT_EQ(Text(read),"x");EXPECT_FALSE(std::get<1>(*read.second));
  EXPECT_EQ(std::get<1>(*duplicate_read.second),asio::error::already_started);
  EXPECT_EQ(std::get<1>(*duplicate_write),asio::error::already_started);
  EXPECT_EQ(std::get<0>(*write),1);EXPECT_FALSE(std::get<1>(*write));
  EXPECT_TRUE(left->is_open());EXPECT_TRUE(right->is_open());
}
TEST_F(StreamPair,DestructionAbortsPendingOperationsAndExpiresWeakControl) {
  auto read=ReadSome(*left,8);auto write=WriteSome(*left,"unsent");
  auto weak=left->control();left.reset();Pump(false);
  EXPECT_EQ(std::get<1>(*read.second),asio::error::operation_aborted);
  EXPECT_EQ(std::get<1>(*write),asio::error::operation_aborted);
  EXPECT_EQ(std::get<0>(*read.second),1);EXPECT_EQ(std::get<0>(*write),1);
  EXPECT_FALSE(weak.Stats());EXPECT_TRUE(wire_left->is_open());EXPECT_TRUE(right->is_open());
}
TEST_F(StreamPair,MoveTransfersConnectionAndAssignmentCancelsReplacedState) {
  NativeUDPSocket destination(wire_left,wire_right->local_endpoint(),owner,Id(2));
  auto cancelled=ReadSome(destination,4);
  destination=std::move(*left);Pump(false);
  EXPECT_EQ(std::get<1>(*cancelled.second),asio::error::operation_aborted);
  EXPECT_FALSE(left->is_open());EXPECT_TRUE(destination.is_open());
  auto invalid=WriteSome(*left,"bad");Pump(false);EXPECT_EQ(std::get<1>(*invalid),asio::error::bad_descriptor);
  auto received=ReadSome(*right,8);auto sent=WriteSome(destination,"moved");
  Until([&]{return std::get<0>(*received.second)>0;});
  EXPECT_EQ(Text(received),"moved");EXPECT_FALSE(std::get<1>(*sent));EXPECT_TRUE(wire_left->is_open());
}
TEST_F(StreamPair,EmptyOperationsAreAsynchronousAndDoNotConsumeWireSequence) {
  auto read=ReadSome(*right,0);auto sent=WriteSome(*left,"");
  EXPECT_EQ(std::get<0>(*read.second),0);EXPECT_EQ(std::get<0>(*sent),0);
  Pump(false);EXPECT_EQ(std::get<0>(*read.second),1);EXPECT_EQ(std::get<0>(*sent),1);
  EXPECT_FALSE(std::get<1>(*read.second));EXPECT_FALSE(std::get<1>(*sent));
  EXPECT_EQ(wire_right->available(),0u);
  auto one=WriteSome(*left,"a");Pump(false);
  auto [source,packet]=Extract(*wire_right);ASSERT_GE(packet.size(),23u);
  EXPECT_EQ(packet[17],0);EXPECT_EQ(packet[18],0);EXPECT_EQ(packet[19],0);EXPECT_EQ(packet[20],0);
}
TEST_F(StreamPair,AssociatedExecutorAndWorkLifetimeSurvivePendingRead) {
  asio::io_context callbacks;auto result=std::make_shared<std::promise<bool>>();auto ready=result->get_future();
  auto buffer=std::make_shared<std::vector<uint8_t>>(1);
  right->async_read_some(asio::buffer(*buffer),asio::bind_executor(callbacks.get_executor(),
    [result,buffer,&callbacks](Error e,size_t n) {
      result->set_value(!e && n==1 && (*buffer)[0]=='q' && callbacks.get_executor().running_in_this_thread());
    }));
  callbacks.poll();EXPECT_FALSE(callbacks.stopped());
  auto sent=WriteSome(*left,"q");
  Until([&]{return !rc.Stats()->reading;});
  EXPECT_EQ(ready.wait_for(0ms),std::future_status::timeout);
  callbacks.run();EXPECT_TRUE(ready.get());EXPECT_TRUE(std::get<0>(*sent));
}
TEST_F(StreamPair,FutureTokensAndCloseErrorsFollowAsioCompletionContract) {
  auto data=std::make_shared<std::vector<uint8_t>>(4);
  auto received=right->async_read_some(asio::buffer(*data),asio::use_future);
  const std::string text="test";auto sent=left->async_write_some(asio::buffer(text),asio::use_future);
  Until([&]{return received.wait_for(0ms)==std::future_status::ready;});
  EXPECT_EQ(sent.get(),4u);EXPECT_EQ(received.get(),4u);EXPECT_EQ(std::string(data->begin(),data->end()),text);
  auto cancelled=right->async_read_some(asio::buffer(*data),asio::use_future);
  right->close();Pump(false);
  EXPECT_THROW(cancelled.get(),boost::system::system_error);
}
TEST_F(StreamPair,BoundedWriterDeadlineCancelsBlockedFragmentAndRetainedBytes) {
  Open(NativeUDPStreamLimits(DatagramBudget(1,64),128),{});
  BasicBoundedStreamWriter<NativeUDPSocket> writer(left,StreamBudget(2,4096),10ms);
  const std::string data(2048,'x');ASSERT_TRUE(writer.TrySend(data.data(),data.size()));
  Until([&]{return writer.is_closed() && writer.queued_messages()==0;},false);
  EXPECT_EQ(writer.status(),StreamStatus::WriteTimeout);EXPECT_EQ(writer.queued_bytes(),0u);
  EXPECT_FALSE(left->is_open());EXPECT_TRUE(wire_left->is_open());
  EXPECT_EQ(lc.Stats()->pending_bytes,0u);EXPECT_FALSE(lc.Stats()->writing);
}

TEST_F(StreamPair,CloseFromAnotherThreadSerializesWithPendingOperations) {
  Open(NativeUDPStreamLimits(DatagramBudget(1,64),128),{});
  auto first=WriteSome(*left,"first");Pump(false);Extract(*wire_right);
  auto read=ReadSome(*left,8);auto write=WriteSome(*left,"blocked");Pump(false);
  EXPECT_EQ(std::get<0>(*write),0);
  auto stream=left;
  std::jthread closer([stream] {for(unsigned i=0;i<100;++i)stream->close();});
  Until([&]{return std::get<0>(*read.second)>0 && std::get<0>(*write)>0;},false);
  closer.join();Pump(false);
  EXPECT_EQ(std::get<0>(*read.second),1);EXPECT_EQ(std::get<0>(*write),1);
  EXPECT_EQ(std::get<1>(*read.second),asio::error::operation_aborted);
  EXPECT_EQ(std::get<1>(*write),asio::error::operation_aborted);
  EXPECT_FALSE(lc.Stats()->open);EXPECT_EQ(lc.Stats()->pending_bytes,0u);
  EXPECT_TRUE(wire_left->is_open());EXPECT_TRUE(right->is_open());
}
