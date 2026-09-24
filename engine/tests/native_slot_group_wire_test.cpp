
#include "frame_sync/native_recovery_wire.hpp"
#include "fixtures/native_groups/original_wire.inc"
#include <gtest/gtest.h>
namespace fs=frame_sync;
namespace {
fs::NativeRecoverySession Session(uint32_t mask=0,uint16_t slot=0) {
 fs::NativeRecoverySession s;s.match=fs::NativeMatchContract(42,11,11);
 s.grant.match.fill(0x34);s.grant.secret.fill(0x12);s.grant.slot=slot;s.grant.generation=7;
 s.slot_mask=mask;return s;
}
void Mask(fs::NativeRecoveryPacket& p,uint32_t mask){fs::native_recovery_wire::put(p.bytes,101,mask,4);}
TEST(GroupWire,LegacyLoadingHelloRemainsByteIdentical) {
 auto old=original_wire::pack_recovery_load_hello(),unused=old;
 auto current=fs::pack_recovery_load_hello();
 EXPECT_EQ(current.size,old.size);
 EXPECT_TRUE(std::equal(current.view().begin(),current.view().end(),old.view().begin()));
 EXPECT_FALSE(fs::recovery_supports_slot_groups(current.view()));
}
TEST(GroupWire,GroupCapabilityIsExplicitAndBounded) {
 auto p=fs::pack_recovery_load_hello(true);
 EXPECT_EQ(p.size,32u);EXPECT_TRUE(fs::is_recovery_load_hello(p.view()));
 EXPECT_TRUE(fs::recovery_supports_slot_groups(p.view()));
 EXPECT_FALSE(original_wire::is_recovery_load_hello(p.view()));
}
TEST(GroupWire,UnknownCapabilityBitsReject) {
 for(uint32_t value:{0u,2u,3u,0xffffffffu}) {
  auto p=fs::pack_recovery_load_hello(true);fs::native_recovery_wire::put(p.bytes,28,value,4);
  EXPECT_FALSE(fs::is_recovery_load_hello(p.view()));EXPECT_FALSE(fs::recovery_supports_slot_groups(p.view()));
 }
}
TEST(GroupWire,OldNonLoadingHelloCannotSilentlyNegotiateGroups) {
 auto p=fs::pack_recovery_load_hello(true);p.bytes[0]=uint8_t(fs::NativeRecoveryKind::Hello);
 EXPECT_EQ(fs::native_recovery_wire::record_size(p.view()),-1);EXPECT_FALSE(fs::is_recovery_hello(p.view()));
}
TEST(GroupWire,LegacySessionsRetainExactBytesAndSingleSeatMeaning) {
 auto s=Session(0,3);original_wire::NativeRecoverySession old;
 old.match=s.match;old.grant=s.grant;
 auto a=fs::pack_recovery_session(s);auto b=original_wire::pack_recovery_session(old);
 EXPECT_EQ(a.size,101u);ASSERT_EQ(a.size,b.size);
 EXPECT_TRUE(std::equal(a.view().begin(),a.view().end(),b.view().begin()));
 auto decoded=fs::decode_recovery_session(b.view());ASSERT_TRUE(decoded);
 EXPECT_EQ(decoded->slot_mask,0u);EXPECT_EQ(decoded->grant.slot,3u);
}
TEST(GroupWire,AllTwentyTwoSeatsRoundTripInOneBoundedRecord) {
 auto p=fs::pack_recovery_session(Session(0x3fffff));
 EXPECT_EQ(p.size,105u);EXPECT_LT(p.size,1177u);
 auto d=fs::decode_recovery_session(p.view());ASSERT_TRUE(d);EXPECT_EQ(d->slot_mask,0x3fffffu);
 EXPECT_EQ(d->grant.generation,7u);EXPECT_EQ(d->grant.secret,Session().grant.secret);
}
TEST(GroupWire,NonContiguousAndExplicitSingleSeatGroupsRoundTrip) {
 for(auto s:{Session(0x55),Session(1u<<5,5)}) {
  auto d=fs::decode_recovery_session(fs::pack_recovery_session(s).view());ASSERT_TRUE(d);
  EXPECT_EQ(d->slot_mask,s.slot_mask);EXPECT_EQ(d->grant.slot,s.grant.slot);
 }
}
TEST(GroupWire,SeatsOutsideTheNegotiatedMatchReject) {
 auto s=Session(1);s.match=fs::NativeMatchContract(42,2,2);
 auto p=fs::pack_recovery_session(s);Mask(p,17);
 EXPECT_FALSE(fs::decode_recovery_session(p.view()));
 s.slot_mask=17;EXPECT_THROW(fs::pack_recovery_session(s),std::invalid_argument);
}
TEST(GroupWire,GroupMustContainItsPrimaryLeaseSeat) {
 auto s=Session(2,0);EXPECT_THROW(fs::pack_recovery_session(s),std::invalid_argument);
 auto p=fs::pack_recovery_session(Session(3));Mask(p,2);EXPECT_FALSE(fs::decode_recovery_session(p.view()));
}
TEST(GroupWire,AnExtendedZeroMaskCannotAliasALegacySession) {
 auto p=fs::pack_recovery_session(Session(3));Mask(p,0);EXPECT_FALSE(fs::decode_recovery_session(p.view()));
}
TEST(GroupWire,EveryTruncatedPrefixIsIncompleteWithoutDecoding) {
 auto p=fs::pack_recovery_session(Session(3));
 for(size_t size=0;size<p.size;++size) {
  auto prefix=p.view().first(size);EXPECT_EQ(fs::native_recovery_wire::record_size(prefix),0);
  EXPECT_FALSE(fs::decode_recovery_session(prefix));
 }
}
TEST(GroupWire,CoalescedFollowingRecordIsNotConsumed) {
 auto p=fs::pack_recovery_session(Session(3));p.bytes[p.size]=80;
 auto coalesced=std::span<const uint8_t>(p.bytes.data(),p.size+1);
 EXPECT_EQ(fs::native_recovery_wire::record_size(coalesced),105);
 EXPECT_FALSE(fs::decode_recovery_session(coalesced));
 EXPECT_TRUE(fs::decode_recovery_session(coalesced.first(105)));
}
TEST(GroupWire,UnnegotiatedOldDecoderRejectsTheExtension) {
 auto p=fs::pack_recovery_session(Session(3));
 EXPECT_FALSE(original_wire::decode_recovery_session(p.view()));
}
TEST(GroupWire,LoadingAndRestoringRemainMutuallyExclusive) {
 auto s=Session(3);s.loading=true;s.restoring=true;
 EXPECT_THROW(fs::pack_recovery_session(s),std::invalid_argument);
 s.restoring=false;auto d=fs::decode_recovery_session(fs::pack_recovery_session(s).view());
 ASSERT_TRUE(d);EXPECT_TRUE(d->loading);EXPECT_FALSE(d->restoring);
}
TEST(GroupWire,InvalidHighBitsAndPrimarySeatRejectBeforeEncoding) {
 for(uint32_t mask:{1u<<22,0xffffffffu})EXPECT_THROW(fs::pack_recovery_session(Session(mask)),std::invalid_argument);
 EXPECT_THROW(fs::pack_recovery_session(Session(1,22)),std::invalid_argument);
}
TEST(GroupWire,AllValidTeamSizesPreserveTheirCompleteRoster) {
 for(uint16_t left=0;left<=11;++left)for(uint16_t right=0;right<=11;++right) {
  const auto count=left+right;if(!count)continue;
  auto s=Session((uint32_t{1}<<count)-1,count-1);s.match=fs::NativeMatchContract(43,left,right);
  auto d=fs::decode_recovery_session(fs::pack_recovery_session(s).view());ASSERT_TRUE(d);
  EXPECT_EQ(d->match,s.match);EXPECT_EQ(d->slot_mask,s.slot_mask);
 }
}
}
