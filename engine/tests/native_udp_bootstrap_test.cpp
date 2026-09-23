#include "frame_sync/native_udp_bootstrap.hpp"
#include <gtest/gtest.h>
#include <poll.h>
#include <set>
namespace frame_sync {
namespace {
namespace boot=native_udp_bootstrap;
using Kind=NativeUDPBootstrapKind;
using State=NativeUDPBootstrapAttempt::State;
// 2026-09-15: original test callback could not convert a capturing lambda to
// the production noexcept function-pointer entropy interface.
// NativeRecoveryCredentials::Entropy fixed(uint8_t seed) {
//   return [seed](std::span<uint8_t> bytes){std::fill(bytes.begin(),bytes.end(),seed);return true;};
// }
template<size_t Seed> bool fixed_bytes(std::span<uint8_t> bytes) noexcept {
  std::fill(bytes.begin(),bytes.end(),static_cast<uint8_t>(Seed));return true;
}
template<size_t... Seeds> auto fixed_table(std::index_sequence<Seeds...>) {
  return std::array<NativeRecoveryCredentials::Entropy,sizeof...(Seeds)>{&fixed_bytes<Seeds>...};
}
NativeRecoveryCredentials::Entropy fixed(uint8_t seed) {
  static const auto table=fixed_table(std::make_index_sequence<256>{});return table[seed];
}
thread_local int calls=0;
bool zeros_entropy(std::span<uint8_t> bytes) noexcept {
  ++calls;std::fill(bytes.begin(),bytes.end(),0);return true;
}
bool unavailable_entropy(std::span<uint8_t>) noexcept {++calls;return false;}
NativeUDPAddress peer(unsigned port=12345) {
  return boot::address(udp::endpoint(asio::ip::make_address("127.0.0.1"),port)).value();
}
NativeUDPBootstrapPacket hello(uint8_t seed=3) {
  NativeUDPBootstrapRecord r;r.nonce.fill(seed);return boot::encode(r);
}
NativeUDPBootstrapPacket as_kind(NativeUDPBootstrapPacket bytes,Kind kind) {
  bytes[5]=static_cast<uint8_t>(kind);return bytes;
}
NativeUDPBootstrapLease lease(NativeUDPBootstrapSigner& signer,uint8_t seed=3,
    uint64_t now=100,const NativeUDPAddress& addr=peer()) {
  auto challenge=signer.challenge(hello(seed),addr,now).value();
  return signer.verify(as_kind(challenge,Kind::Confirm),addr,now).value();
}
TEST(UDPBootstrap,CanonicalEndpointAndScope) {
  EXPECT_EQ(peer(),boot::address(udp::endpoint(asio::ip::make_address("::ffff:127.0.0.1"),12345)));
  EXPECT_NE(peer(),peer(12346));
  auto v6=asio::ip::make_address_v6("fe80::1");v6.scope_id(4);
  const auto a=boot::address(udp::endpoint(v6,999)).value();v6.scope_id(5);
  EXPECT_NE(a,boot::address(udp::endpoint(v6,999)));
  EXPECT_TRUE(boot::valid_address(a));EXPECT_EQ(a[0],6);EXPECT_EQ(a[17],4);
}
TEST(UDPBootstrap,RejectInvalidEndpointsAndPadding) {
  for(const auto* ip:{"0.0.0.0","::","::ffff:0.0.0.0"})
    EXPECT_FALSE(boot::address(udp::endpoint(asio::ip::make_address(ip),123)));
  EXPECT_FALSE(boot::address(udp::endpoint(asio::ip::make_address("127.0.0.1"),0)));
  auto a=peer();a[5]=1;EXPECT_FALSE(boot::valid_address(a));
  a=peer();a[17]=1;EXPECT_FALSE(boot::valid_address(a));
  a=peer();a[0]=7;EXPECT_FALSE(boot::valid_address(a));
  a=peer();a[21]=a[22]=0;EXPECT_FALSE(boot::valid_address(a));
}
TEST(UDPBootstrap,ExactBoundedWireFormat) {
  const auto h=hello();EXPECT_EQ(h.size(),64u);
  EXPECT_EQ(std::string(h.begin(),h.begin()+4),"FNDU");
  EXPECT_EQ(h[4],1);EXPECT_EQ(h[5],1);EXPECT_EQ(h[8],3);EXPECT_EQ(h[23],3);
  NativeUDPBootstrapSigner signer(5000,fixed(7));
  auto c=signer.challenge(h,peer(),100).value();
  EXPECT_EQ(c.size(),h.size());EXPECT_EQ(boot::get(c.data()+24,8),5100u);
  for(auto kind:{Kind::Challenge,Kind::Confirm,Kind::Established}) {
    auto packet=as_kind(c,kind);auto parsed=boot::decode(packet);
    ASSERT_TRUE(parsed);EXPECT_EQ(parsed->kind,kind);EXPECT_EQ(boot::encode(*parsed),packet);
  }
}
TEST(UDPBootstrap,RejectMalformedWireBeforeState) {
  auto h=hello();
  for(size_t n=0;n<h.size();++n)EXPECT_FALSE(boot::decode(std::span(h.data(),n)));
  std::vector<uint8_t> extra(h.begin(),h.end());extra.push_back(0);
  EXPECT_FALSE(boot::decode(extra));
  for(size_t i=0;i<8;++i) {auto bad=h;bad[i]=0xff;EXPECT_FALSE(boot::decode(bad));}
  auto bad=h;std::fill(bad.begin()+8,bad.begin()+24,0);EXPECT_FALSE(boot::decode(bad));
  bad=h;bad[24]=1;EXPECT_FALSE(boot::decode(bad));
  bad=h;bad[32]=1;EXPECT_FALSE(boot::decode(bad));
  bad=as_kind(h,Kind::Challenge);EXPECT_FALSE(boot::decode(bad));
  EXPECT_THROW(boot::encode(NativeUDPBootstrapRecord{}),std::invalid_argument);
}
TEST(UDPBootstrap,ServerEntropyFailsClosedAndIsBounded) {
  // 2026-09-15: preserve original four-call/one-call failure assertions.
  // int calls=0;
  // auto zeros=[&](std::span<uint8_t> bytes){++calls;std::fill(bytes.begin(),bytes.end(),0);return true;};
  calls=0;auto zeros=&zeros_entropy;
  EXPECT_THROW(NativeUDPBootstrapSigner(5000,zeros),std::runtime_error);EXPECT_EQ(calls,4);
  // calls=0;auto unavailable=[&](std::span<uint8_t>){++calls;return false;};
  calls=0;auto unavailable=&unavailable_entropy;
  EXPECT_THROW(NativeUDPBootstrapSigner(5000,unavailable),std::runtime_error);EXPECT_EQ(calls,1);
  EXPECT_THROW(NativeUDPBootstrapSigner(0,fixed(1)),std::invalid_argument);
  EXPECT_THROW(NativeUDPBootstrapSigner(30001,fixed(1)),std::invalid_argument);
  EXPECT_THROW(NativeUDPBootstrapSigner(5000,{}),std::invalid_argument);
}
TEST(UDPBootstrap,ClientEntropyFailsClosedAndIsBounded) {
  // 2026-09-15: preserve original four-call/one-call failure assertions.
  // int calls=0;
  // auto zeros=[&](std::span<uint8_t> bytes){++calls;std::fill(bytes.begin(),bytes.end(),0);return true;};
  calls=0;auto zeros=&zeros_entropy;
  EXPECT_THROW(NativeUDPBootstrapAttempt(peer(),100,1000,zeros),std::runtime_error);
  EXPECT_EQ(calls,4);
  EXPECT_THROW(NativeUDPBootstrapAttempt(peer(),100,0,fixed(1)),std::invalid_argument);
  EXPECT_THROW(NativeUDPBootstrapAttempt(peer(),100,30001,fixed(1)),std::invalid_argument);
  EXPECT_THROW(NativeUDPBootstrapAttempt(peer(),UINT64_MAX,1,fixed(1)),std::invalid_argument);
  EXPECT_THROW(NativeUDPBootstrapAttempt(NativeUDPAddress{},100,1,fixed(1)),std::invalid_argument);
  EXPECT_THROW(NativeUDPBootstrapAttempt(peer(),100,1000,{}),std::runtime_error);
}
TEST(UDPBootstrap,CookieBindsAllBytesAndReturnRoute) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));
  const auto proof=as_kind(signer.challenge(hello(),peer(),100).value(),Kind::Confirm);
  ASSERT_TRUE(signer.verify(proof,peer(),100));
  for(size_t i=8;i<64;++i) {auto bad=proof;bad[i]^=1;EXPECT_FALSE(signer.verify(bad,peer(),100));}
  EXPECT_FALSE(signer.verify(proof,peer(12346),100));
  auto other=peer();other[1]=128;EXPECT_FALSE(signer.verify(proof,other,100));
  EXPECT_FALSE(signer.verify(as_kind(proof,Kind::Hello),peer(),100));
  EXPECT_FALSE(signer.verify(as_kind(proof,Kind::Challenge),peer(),100));
  EXPECT_FALSE(signer.verify(as_kind(proof,Kind::Established),peer(),100));
}
TEST(UDPBootstrap,ServerExpirationAndOverflowAreAbsolute) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));
  const auto proof=as_kind(signer.challenge(hello(),peer(),100).value(),Kind::Confirm);
  EXPECT_FALSE(signer.verify(proof,peer(),99));
  EXPECT_TRUE(signer.verify(proof,peer(),5099));
  EXPECT_FALSE(signer.verify(proof,peer(),5100));
  EXPECT_FALSE(signer.verify(proof,peer(),UINT64_MAX));
  EXPECT_FALSE(signer.challenge(hello(),peer(),UINT64_MAX-4999));
  EXPECT_TRUE(signer.challenge(hello(),peer(),UINT64_MAX-5000));
}
TEST(UDPBootstrap,RestartAndFreshNonceChangeIdentity) {
  NativeUDPBootstrapSigner a(5000,fixed(7)),b(5000,fixed(8));
  auto c=a.challenge(hello(),peer(),100).value();
  EXPECT_FALSE(b.verify(as_kind(c,Kind::Confirm),peer(),100));
  EXPECT_NE(lease(a).connection(),lease(b).connection());
  EXPECT_NE(lease(a,3).connection(),lease(a,4).connection());
}
TEST(UDPBootstrap,NoRegistrySlotsAllocatedByHelloFlood) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));NativeUDPConnectionRegistry registry(4);
  for(unsigned i=1;i<=4096;++i) {
    auto c=signer.challenge(hello(static_cast<uint8_t>(1+i%255)),peer(1000+i),100);
    ASSERT_TRUE(c);EXPECT_EQ(c->size(),64u);
  }
  EXPECT_EQ(registry.active(),0u);EXPECT_EQ(registry.retired(),0u);
}
TEST(UDPBootstrap,CapacityIsHardBoundIncludingTombstones) {
  EXPECT_THROW(NativeUDPConnectionRegistry(0),std::invalid_argument);
  EXPECT_THROW(NativeUDPConnectionRegistry(129),std::invalid_argument);
  NativeUDPBootstrapSigner signer(5000,fixed(7));NativeUDPConnectionRegistry registry(128);
  for(unsigned i=1;i<=128;++i)EXPECT_TRUE(registry.claim(lease(signer,i),100));
  EXPECT_EQ(registry.active(),128u);EXPECT_FALSE(registry.claim(lease(signer,129),100));
  EXPECT_TRUE(registry.retire(peer(),lease(signer,1).connection(),101));
  EXPECT_EQ(registry.active(),127u);EXPECT_EQ(registry.retired(),1u);
  EXPECT_FALSE(registry.claim(lease(signer,129),101));
}
TEST(UDPBootstrap,DuplicateConfirmReusesExistingChannel) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));NativeUDPConnectionRegistry registry(1);
  auto grant=lease(signer);auto first=registry.claim(grant,100);ASSERT_TRUE(first);EXPECT_TRUE(first->second);
  for(unsigned i=101;i<500;++i) {
    auto again=registry.claim(grant,i);ASSERT_TRUE(again);
    EXPECT_EQ(again->first,first->first);EXPECT_FALSE(again->second);
  }
  EXPECT_EQ(registry.active(),1u);EXPECT_EQ(registry.find(peer(),grant.connection()),first->first);
}
TEST(UDPBootstrap,RetiredGenerationCannotReopenBeforeCookieExpiry) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));NativeUDPConnectionRegistry registry(1);
  auto old=lease(signer);ASSERT_TRUE(registry.claim(old,100));
  ASSERT_TRUE(registry.retire(peer(),old.connection(),200));
  EXPECT_FALSE(registry.find(peer(),old.connection()));
  EXPECT_FALSE(registry.claim(old,201));EXPECT_FALSE(registry.claim(lease(signer,4),201));
  ASSERT_TRUE(registry.maintain(5100));EXPECT_EQ(registry.retired(),0u);
  EXPECT_FALSE(registry.claim(old,5100));
  auto fresh=lease(signer,4,5100);EXPECT_TRUE(registry.claim(fresh,5100));
  EXPECT_FALSE(registry.find(peer(),old.connection()));EXPECT_TRUE(registry.find(peer(),fresh.connection()));
}
TEST(UDPBootstrap,ActiveConnectionOutlivesBootstrapCookie) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));NativeUDPConnectionRegistry registry(1);
  auto grant=lease(signer);ASSERT_TRUE(registry.claim(grant,100));
  ASSERT_TRUE(registry.maintain(5100));EXPECT_EQ(registry.active(),1u);
  EXPECT_TRUE(registry.find(peer(),grant.connection()));
  ASSERT_TRUE(registry.retire(peer(),grant.connection(),5101));
  EXPECT_EQ(registry.active(),0u);EXPECT_EQ(registry.retired(),0u);
  EXPECT_TRUE(registry.claim(lease(signer,4,5101),5101));
}
TEST(UDPBootstrap,RegistryRejectsClockReversalAndWrongRetirement) {
  NativeUDPBootstrapSigner signer(5000,fixed(7));NativeUDPConnectionRegistry registry(2);
  auto grant=lease(signer);ASSERT_TRUE(registry.claim(grant,100));
  EXPECT_FALSE(registry.maintain(99));EXPECT_FALSE(registry.claim(lease(signer,4),99));
  EXPECT_FALSE(registry.retire(peer(),grant.connection(),99));
  EXPECT_FALSE(registry.retire(peer(12346),grant.connection(),100));
  EXPECT_EQ(registry.active(),1u);EXPECT_TRUE(registry.retire(peer(),grant.connection(),100));
}
#include "fixtures/native_udp/bootstrap/client_cases.inc"
#include "fixtures/native_udp/bootstrap/socket_cases.inc"
} // namespace
} // namespace frame_sync
