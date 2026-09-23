
TEST_F(DialFixture,LargeBidirectionalTransferRunsWithActualClientAndListenerIOOwners) {
  relay=std::make_unique<Relay>(io,listener->local_endpoint());
  auto accepted=Accept();auto client=Dial(relay->down.local_endpoint());
  Until([&]{return client->calls>0 && accepted->calls>0;});ASSERT_FALSE(client->error);
  auto source=std::make_shared<std::vector<uint8_t>>(1024*1024);
  for(size_t i=0;i<source->size();++i)(*source)[i]=static_cast<uint8_t>((i*19+i/53)%251);
  auto server=std::make_shared<std::vector<uint8_t>>(source->size());auto receive=outcome(),send=outcome();
  asio::async_read(*accepted->socket,asio::buffer(*server),[server,receive](Error e,size_t n){finish(receive,e,n);});
  asio::async_write(*client->socket,asio::buffer(*source),[source,send](Error e,size_t n){finish(send,e,n);});
  Until([&]{return std::get<0>(*receive)>0 && std::get<0>(*send)>0;});
  EXPECT_FALSE(std::get<1>(*receive));EXPECT_FALSE(std::get<1>(*send));EXPECT_EQ(*source,*server);
  auto target=std::make_shared<std::vector<uint8_t>>(source->size());auto got=outcome(),sent=outcome();
  asio::async_read(*client->socket,asio::buffer(*target),[target,got](Error e,size_t n){finish(got,e,n);});
  asio::async_write(*accepted->socket,asio::buffer(*server),[server,sent](Error e,size_t n){finish(sent,e,n);});
  Until([&]{return std::get<0>(*got)>0 && std::get<0>(*sent)>0;});
  EXPECT_FALSE(std::get<1>(*got));EXPECT_FALSE(std::get<1>(*sent));EXPECT_EQ(*source,*target);
  Until([&]{return listener->stats().pending_bytes==0 && dialer->stats().stream->pending_bytes==0;});
  EXPECT_LE(relay->max_wire,1200u);EXPECT_LE(dialer->stats().stream->receive_capacity,128*1024u);
}
TEST_F(DialFixture,ClientDataAndServerAckLossRecoverWithoutDuplicateBytes) {
  relay=std::make_unique<Relay>(io,listener->local_endpoint());
  auto accepted=Accept();auto client=Dial(relay->down.local_endpoint());
  Until([&]{return client->calls>0 && accepted->calls>0;});ASSERT_FALSE(client->error);
  relay->drop_client_data=true;relay->drop_server_ack=true;
  auto received=ReadSome(*accepted->socket,16);auto sent=WriteSome(*client->socket,"recover");
  Until([&]{return std::get<0>(*received.second)>0;});EXPECT_EQ(Text(received),"recover");
  Until([&]{return dialer->stats().stream->pending_packets==0;});
  EXPECT_EQ(relay->dropped,2u);
  auto next=ReadSome(*accepted->socket,16);Pulse();EXPECT_EQ(std::get<0>(*next.second),0);
  auto second=WriteSome(*client->socket,"next");Until([&]{return std::get<0>(*next.second)>0;});
  EXPECT_EQ(Text(next),"next");EXPECT_FALSE(std::get<1>(*second));
}
TEST_F(DialFixture,ForeignEndpointCannotDeliverCapturedValidServerPacket) {
  relay=std::make_unique<Relay>(io,listener->local_endpoint());
  auto accepted=Accept();auto client=Dial(relay->down.local_endpoint());
  Until([&]{return client->calls>0 && accepted->calls>0;});ASSERT_FALSE(client->error);
  relay->hold_server_data=true;
  auto read=ReadSome(*client->socket,16);auto sent=WriteSome(*accepted->socket,"authentic");
  Until([&]{return !relay->held_server_data.empty();});ASSERT_TRUE(relay->client);
  udp::socket stranger(io,udp::endpoint(asio::ip::make_address("127.0.0.1"),0));
  const auto ignored=dialer->stats().ignored_packets;
  stranger.send_to(asio::buffer(relay->held_server_data),*relay->client);
  Until([&]{return dialer->stats().ignored_packets>ignored;});
  EXPECT_EQ(std::get<0>(*read.second),0);
  relay->down.send_to(asio::buffer(relay->held_server_data),*relay->client);
  relay->hold_server_data=false;
  Until([&]{return std::get<0>(*read.second)>0;});EXPECT_EQ(Text(read),"authentic");
}
TEST_F(DialFixture,GenericWriterDeadlineClosesClientPhysicalSocketAfterBlockedFragment) {
  auto limits=NativeUDPDialLimits{};limits.stream.datagrams=DatagramBudget(1,64);ResetDialer(limits);
  relay=std::make_unique<Relay>(io,listener->local_endpoint());
  auto accepted=Accept();auto client=Dial(relay->down.local_endpoint());
  Until([&]{return client->calls>0 && accepted->calls>0;});ASSERT_FALSE(client->error);
  relay->drop_client_data=true;
  auto socket=std::shared_ptr<NativeUDPSocket>(std::move(client->socket));
  BasicBoundedStreamWriter<NativeUDPSocket> writer(socket,StreamBudget(2,4096),5ms);
  const std::string payload(2048,'x');ASSERT_TRUE(writer.TrySend(payload.data(),payload.size()));
  Until([&]{return writer.is_closed() && writer.queued_messages()==0 && !dialer->stats().busy;});
  EXPECT_EQ(writer.status(),StreamStatus::WriteTimeout);EXPECT_EQ(writer.queued_bytes(),0u);
  EXPECT_FALSE(socket->is_open());EXPECT_FALSE(dialer->stats().local);
}
TEST_F(DialFixture,EstablishedStreamOutlivesTheOriginalDialDeadline) {
  auto accepted=Accept();auto client=Dial(listener->local_endpoint());
  Until([&]{return client->calls>0 && accepted->calls>0;});ASSERT_FALSE(client->error);
  Advance(10001ms);EXPECT_TRUE(dialer->stats().busy);EXPECT_TRUE(client->socket->is_open());
  auto read=ReadSome(*accepted->socket,16);auto sent=WriteSome(*client->socket,"still alive");
  Until([&]{return std::get<0>(*read.second)>0;});EXPECT_EQ(Text(read),"still alive");
}
