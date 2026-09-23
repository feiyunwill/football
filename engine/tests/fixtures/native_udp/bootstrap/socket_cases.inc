
std::vector<uint8_t> read_datagram(udp::socket& socket,const udp::endpoint& expected) {
  pollfd fd{socket.native_handle(),POLLIN,0};
  if(::poll(&fd,1,2000)!=1 || !(fd.revents&POLLIN))throw std::runtime_error("UDP test receive deadline");
  std::vector<uint8_t> packet(1500);udp::endpoint source;boost::system::error_code error;
  const auto n=socket.receive_from(asio::buffer(packet),source,0,error);
  if(error || source!=expected)throw std::runtime_error("UDP test wrong source or receive failure");
  packet.resize(n);return packet;
}
std::vector<uint8_t> wire(udp::socket& from,udp::socket& to,std::span<const uint8_t> packet) {
  if(from.send_to(asio::buffer(packet.data(),packet.size()),to.local_endpoint())!=packet.size())
    throw std::runtime_error("UDP test short send");
  return read_datagram(to,from.local_endpoint());
}
TEST(UDPBootstrapSocket,LostMessagesRetryWithoutDuplicatingChannel) {
  for(unsigned lost=1;lost<=4;++lost) {
    SCOPED_TRACE(lost);
    asio::io_context io;udp::socket client(io,udp::endpoint(asio::ip::make_address("127.0.0.1"),0));
    udp::socket server(io,udp::endpoint(asio::ip::make_address("127.0.0.1"),0));
    auto client_key=boot::address(client.local_endpoint()).value();
    auto server_key=boot::address(server.local_endpoint()).value();
    NativeUDPBootstrapSigner signer(5000,fixed(7));
    NativeUDPBootstrapAttempt attempt(server_key,100,1000,fixed(lost));
    NativeUDPConnectionRegistry registry(1);
    std::optional<NativeUDPBootstrapLease> accepted;
    bool dropped=false;unsigned allocations=0;
    for(unsigned round=0;round<8 && !attempt.connection();++round) {
      const uint64_t now=100+round*10;
      auto request=attempt.next_packet(now);ASSERT_TRUE(request);
      auto inbound=wire(client,server,*request);auto record=boot::decode(inbound);ASSERT_TRUE(record);
      if(!dropped && record->kind==Kind::Hello && lost==1){dropped=true;continue;}
      if(record->kind==Kind::Hello) {
        auto c=signer.challenge(inbound,client_key,now);ASSERT_TRUE(c);
        auto reply=wire(server,client,*c);
        if(!dropped && lost==2){dropped=true;continue;}
        EXPECT_FALSE(attempt.receive(reply,server_key,now));
      } else {
        ASSERT_EQ(record->kind,Kind::Confirm);
        if(!dropped && lost==3){dropped=true;continue;}
        accepted=signer.verify(inbound,client_key,now);ASSERT_TRUE(accepted);
        auto claim=registry.claim(*accepted,now);ASSERT_TRUE(claim);allocations+=claim->second;
        auto reply=wire(server,client,accepted->reply());
        if(!dropped && lost==4){dropped=true;continue;}
        EXPECT_TRUE(attempt.receive(reply,server_key,now));
      }
    }
    ASSERT_TRUE(dropped);ASSERT_TRUE(attempt.connection());ASSERT_TRUE(accepted);
    EXPECT_EQ(allocations,1u);EXPECT_EQ(registry.active(),1u);
    EXPECT_EQ(attempt.connection(),accepted->connection());
    auto duplicate=wire(client,server,as_kind(accepted->reply(),Kind::Confirm));
    auto proof=signer.verify(duplicate,client_key,200);ASSERT_TRUE(proof);
    auto claim=registry.claim(*proof,200);ASSERT_TRUE(claim);EXPECT_FALSE(claim->second);
    auto welcome=wire(server,client,proof->reply());EXPECT_FALSE(attempt.receive(welcome,server_key,200));
    unsigned deliveries=0;
    ReliableUDPChannel send(client,server.local_endpoint(),{},DatagramBudget{},
                            ReliableUDPChannel::Clock::now,attempt.connection());
    ReliableUDPChannel receive(server,client.local_endpoint(),
      [&](const uint8_t* p,size_t n){++deliveries;EXPECT_EQ(std::string(reinterpret_cast<const char*>(p),n),"input");},
      DatagramBudget{},ReliableUDPChannel::Clock::now,accepted->connection());
    for(unsigned i=0;i<2;++i) {
      ASSERT_TRUE(send.Send("input",5));
      const auto bytes=read_datagram(server,client.local_endpoint());
      EXPECT_EQ(boot::get(bytes.data()+17,4),i);
      EXPECT_TRUE(registry.find(client_key,accepted->connection()));
      ASSERT_TRUE(receive.HandleReceived(bytes.data(),bytes.size()));
      const auto ack=read_datagram(client,server.local_endpoint());
      ASSERT_TRUE(send.HandleReceived(ack.data(),ack.size()));
      EXPECT_EQ(send.pending_count(),0u);
    }
    EXPECT_EQ(deliveries,2u);
  }
}
TEST(UDPBootstrapSocket,FreshNegotiationRejectsPreviousDataAndAck) {
  asio::io_context io;udp::socket client(io,udp::endpoint(asio::ip::make_address("127.0.0.1"),0));
  udp::socket server(io,udp::endpoint(asio::ip::make_address("127.0.0.1"),0));
  const auto ck=boot::address(client.local_endpoint()).value();
  const auto sk=boot::address(server.local_endpoint()).value();
  NativeUDPBootstrapSigner signer(5000,fixed(7));NativeUDPConnectionRegistry registry(2);
  std::vector<uint8_t> old_data,old_ack;ReliableUDPConnection old_id{};
  for(unsigned cycle=0;cycle<2;++cycle) {
    NativeUDPBootstrapAttempt attempt(sk,100,1000,fixed(cycle+1));
    auto h=wire(client,server,attempt.next_packet(100).value());
    auto challenge=wire(server,client,signer.challenge(h,ck,100).value());
    EXPECT_FALSE(attempt.receive(challenge,sk,101));
    auto confirm=wire(client,server,attempt.next_packet(102).value());
    auto grant=signer.verify(confirm,ck,102);ASSERT_TRUE(grant);
    ASSERT_TRUE(registry.claim(*grant,102+cycle));
    EXPECT_TRUE(attempt.receive(wire(server,client,grant->reply()),sk,103));
    unsigned deliveries=0;
    ReliableUDPChannel left(client,server.local_endpoint(),{},DatagramBudget{},
                             ReliableUDPChannel::Clock::now,attempt.connection());
    ReliableUDPChannel right(server,client.local_endpoint(),[&](const uint8_t*,size_t){++deliveries;},
                              DatagramBudget{},ReliableUDPChannel::Clock::now,grant->connection());
    ASSERT_TRUE(left.Send("input",5));auto data=read_datagram(server,client.local_endpoint());
    if(cycle) {
      EXPECT_NE(old_id,grant->connection());EXPECT_FALSE(registry.find(ck,old_id));
      auto stale=wire(client,server,old_data);ASSERT_TRUE(right.HandleReceived(stale.data(),stale.size()));
      EXPECT_EQ(deliveries,0u);EXPECT_EQ(client.available(),0u);
      stale=wire(server,client,old_ack);ASSERT_TRUE(left.HandleReceived(stale.data(),stale.size()));
      EXPECT_EQ(left.pending_count(),1u);
    }
    ASSERT_TRUE(right.HandleReceived(data.data(),data.size()));auto ack=read_datagram(client,server.local_endpoint());
    ASSERT_TRUE(left.HandleReceived(ack.data(),ack.size()));EXPECT_EQ(deliveries,1u);EXPECT_EQ(left.pending_count(),0u);
    if(!cycle){old_data=data;old_ack=ack;old_id=grant->connection();}
    left.Close();right.Close();ASSERT_TRUE(registry.retire(ck,grant->connection(),102+cycle));
    EXPECT_FALSE(registry.claim(*grant,102+cycle));
  }
  EXPECT_EQ(registry.active(),0u);EXPECT_EQ(registry.retired(),2u);
}
