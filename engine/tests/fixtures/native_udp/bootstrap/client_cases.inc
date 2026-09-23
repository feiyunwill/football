
TEST(UDPBootstrap,ClientUsesOwnClockAndDeadline) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));
  NativeUDPBootstrapAttempt attempt(peer(),1000000,1000,fixed(3));
  auto hello=attempt.next_packet(1000000).value();
  auto challenge=signer.challenge(hello,peer(12346),100).value();
  EXPECT_FALSE(attempt.receive(challenge,peer(),1000001));
  EXPECT_EQ(attempt.state(),State::AwaitEstablished);
  auto confirm=attempt.next_packet(1000002).value();
  auto grant=signer.verify(confirm,peer(12346),101).value();
  EXPECT_TRUE(attempt.receive(grant.reply(),peer(),1000003));
  EXPECT_EQ(attempt.connection(),grant.connection());EXPECT_EQ(attempt.state(),State::Established);
}
TEST(UDPBootstrap,RetransmissionNeverRenewsDeadline) {
  NativeUDPBootstrapAttempt attempt(peer(),100,1000,fixed(3));
  const auto first=attempt.next_packet(100).value();
  for(uint64_t t=101;t<1100;++t) {
    EXPECT_EQ(attempt.next_packet(t),first);EXPECT_EQ(attempt.deadline(),1100u);
  }
  EXPECT_FALSE(attempt.next_packet(1100));EXPECT_EQ(attempt.state(),State::Expired);
  EXPECT_FALSE(attempt.next_packet(1101));EXPECT_FALSE(attempt.connection());
}
TEST(UDPBootstrap,FirstChallengeRemainsStableAcrossRetries) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));
  NativeUDPBootstrapAttempt attempt(peer(),100,1000,fixed(3));
  auto h=attempt.next_packet(100).value();
  auto c=signer.challenge(h,peer(12346),100).value();
  EXPECT_FALSE(attempt.receive(c,peer(),101));
  const auto confirm=attempt.next_packet(102).value();
  auto later=signer.challenge(h,peer(12346),102).value();ASSERT_NE(c,later);
  EXPECT_FALSE(attempt.receive(later,peer(),103));EXPECT_EQ(attempt.next_packet(104),confirm);
  EXPECT_EQ(attempt.deadline(),1100u);
}
TEST(UDPBootstrap,DuplicateWelcomeCannotResetEstablishedState) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));NativeUDPBootstrapAttempt attempt(peer(),100,1000,fixed(3));
  auto c=signer.challenge(attempt.next_packet(100).value(),peer(12346),100).value();
  EXPECT_FALSE(attempt.receive(c,peer(),101));
  auto grant=signer.verify(attempt.next_packet(102).value(),peer(12346),102).value();
  ASSERT_TRUE(attempt.receive(grant.reply(),peer(),103));
  for(unsigned i=104;i<304;++i)EXPECT_FALSE(attempt.receive(grant.reply(),peer(),i));
  EXPECT_FALSE(attempt.next_packet(304));EXPECT_EQ(attempt.connection(),grant.connection());
  EXPECT_FALSE(attempt.next_packet(1100));EXPECT_EQ(attempt.state(),State::Established);
}
TEST(UDPBootstrap,WelcomeBeforeChallengeAndConfirmAreIgnored) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));NativeUDPBootstrapAttempt attempt(peer(),100,1000,fixed(3));
  const auto grant=lease(signer,3,100,peer(12346));
  EXPECT_FALSE(attempt.receive(grant.reply(),peer(),101));EXPECT_EQ(attempt.state(),State::AwaitChallenge);
  EXPECT_FALSE(attempt.receive(as_kind(grant.reply(),Kind::Confirm),peer(),102));
  EXPECT_EQ(attempt.state(),State::AwaitChallenge);EXPECT_FALSE(attempt.connection());
}
TEST(UDPBootstrap,WrongReplyEndpointCannotEstablishOrChooseCookie) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));NativeUDPBootstrapAttempt attempt(peer(),100,1000,fixed(3));
  auto c=signer.challenge(attempt.next_packet(100).value(),peer(12346),100).value();
  EXPECT_FALSE(attempt.receive(c,peer(12347),101));EXPECT_EQ(attempt.state(),State::AwaitChallenge);
  EXPECT_FALSE(attempt.receive(c,peer(),102));
  auto grant=signer.verify(attempt.next_packet(103).value(),peer(12346),103).value();
  EXPECT_FALSE(attempt.receive(grant.reply(),peer(12347),104));EXPECT_EQ(attempt.state(),State::AwaitEstablished);
  EXPECT_TRUE(attempt.receive(grant.reply(),peer(),105));
}
TEST(UDPBootstrap,OldAttemptCannotEstablishFreshAttempt) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));NativeUDPBootstrapAttempt attempt(peer(),100,1000,fixed(4));
  auto old=lease(signer,3,100,peer(12346));
  EXPECT_FALSE(attempt.receive(as_kind(old.reply(),Kind::Challenge),peer(),101));
  EXPECT_EQ(attempt.state(),State::AwaitChallenge);EXPECT_FALSE(attempt.receive(old.reply(),peer(),102));
  auto c=signer.challenge(attempt.next_packet(103).value(),peer(12346),103).value();
  EXPECT_FALSE(attempt.receive(c,peer(),104));EXPECT_FALSE(attempt.receive(old.reply(),peer(),105));
  EXPECT_EQ(attempt.state(),State::AwaitEstablished);
  auto grant=signer.verify(attempt.next_packet(106).value(),peer(12346),106).value();
  EXPECT_TRUE(attempt.receive(grant.reply(),peer(),107));
}
TEST(UDPBootstrap,SelectedCookieMustMatchEveryWelcomeByte) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));NativeUDPBootstrapAttempt attempt(peer(),100,1000,fixed(3));
  auto c=signer.challenge(attempt.next_packet(100).value(),peer(12346),100).value();
  EXPECT_FALSE(attempt.receive(c,peer(),101));
  auto grant=signer.verify(attempt.next_packet(102).value(),peer(12346),102).value();
  for(size_t i=0;i<64;++i) {
    auto bad=grant.reply();bad[i]^=0x80;
    EXPECT_FALSE(attempt.receive(bad,peer(),103));EXPECT_EQ(attempt.state(),State::AwaitEstablished);
  }
  EXPECT_TRUE(attempt.receive(grant.reply(),peer(),104));
}
TEST(UDPBootstrap,LateRepliesAndClockReversalNeverExtendAttempt) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));NativeUDPBootstrapAttempt attempt(peer(),100,1000,fixed(3));
  auto c=signer.challenge(attempt.next_packet(100).value(),peer(12346),100).value();
  EXPECT_FALSE(attempt.receive(c,peer(),99));EXPECT_EQ(attempt.state(),State::AwaitChallenge);
  EXPECT_FALSE(attempt.next_packet(99));EXPECT_FALSE(attempt.receive(c,peer(),101));
  auto grant=signer.verify(attempt.next_packet(102).value(),peer(12346),102).value();
  EXPECT_FALSE(attempt.receive(grant.reply(),peer(),1100));EXPECT_EQ(attempt.state(),State::Expired);
  EXPECT_FALSE(attempt.receive(grant.reply(),peer(),1099));EXPECT_FALSE(attempt.connection());
}
TEST(UDPBootstrap,ActualEntropyGeneratesDistinctPhysicalAttempts) {
  NativeUDPBootstrapSigner signer(5000);std::set<ReliableUDPConnection> ids;
  for(unsigned i=0;i<128;++i) {
    NativeUDPBootstrapAttempt attempt(peer(),100,1000);
    auto c=signer.challenge(attempt.next_packet(100).value(),peer(12346),100).value();
    EXPECT_FALSE(attempt.receive(c,peer(),101));
    auto grant=signer.verify(attempt.next_packet(102).value(),peer(12346),102).value();
    ASSERT_TRUE(attempt.receive(grant.reply(),peer(),103));
    EXPECT_TRUE(ids.insert(attempt.connection().value()).second);
  }
}

TEST(UDPBootstrap,MatchesIndependentHmacSha256Vector) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));
  auto c=signer.challenge(hello(),peer(),100).value();
  const std::array<uint8_t,32> expected{212,79,33,37,13,91,229,247,211,245,26,1,173,75,196,35,242,124,236,85,222,3,132,89,153,134,189,234,162,40,32,14};
  EXPECT_TRUE(std::equal(expected.begin(),expected.end(),c.begin()+32));
}
