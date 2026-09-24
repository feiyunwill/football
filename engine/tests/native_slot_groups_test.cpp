
#include "frame_sync/native_recovery_groups.hpp"
#include <gtest/gtest.h>
#include <chrono>
namespace fs=frame_sync;
using namespace std::chrono_literals;
namespace {
unsigned next_byte=1;bool fail_entropy=false;
bool Entropy(std::span<uint8_t> bytes) noexcept {
 if(fail_entropy)return false;
 std::fill(bytes.begin(),bytes.end(),static_cast<uint8_t>(next_byte++));return true;
}
struct Groups : ::testing::Test {
 void SetUp() override {next_byte=1;fail_entropy=false;}
 static auto T(int ms){return fs::NativeRecoveryGroups::Time{}+std::chrono::milliseconds(ms);}
};
TEST_F(Groups,SingleSeatRetainsTheOriginalLeaseSemantics) {
 fs::NativeRecoveryGroups groups(2,100ms,Entropy);
 auto a=groups.issue(1,T(0));ASSERT_TRUE(a);EXPECT_EQ(a->lease.slot,0);
 EXPECT_EQ(a->slots,1u);EXPECT_TRUE(groups.owns_slot(0,a->lease.generation,0,T(0)));
 EXPECT_FALSE(groups.owns_slot(0,a->lease.generation,1,T(0)));
}
TEST_F(Groups,OneLeaseOwnsAllTwentyTwoSeats) {
 fs::NativeRecoveryGroups groups(22,100ms,Entropy);
 auto a=groups.issue(fs::NativeRecoveryGroups::kAllSlots,T(0));ASSERT_TRUE(a);
 EXPECT_EQ(a->slots,0x3fffffu);
 for(uint16_t slot=0;slot<22;++slot)EXPECT_TRUE(groups.owns_slot(0,a->lease.generation,slot,T(0)));
 EXPECT_FALSE(groups.issue(1,T(0)));EXPECT_FALSE(groups.owns_slot(0,a->lease.generation,22,T(0)));
}
TEST_F(Groups,DisjointNonContiguousGroupsRemainIndependent) {
 fs::NativeRecoveryGroups groups(8,100ms,Entropy);
 auto a=groups.issue(0x55,T(0)),b=groups.issue(0xaa,T(0));ASSERT_TRUE(a);ASSERT_TRUE(b);
 EXPECT_EQ(a->lease.slot,0);EXPECT_EQ(b->lease.slot,1);
 for(uint16_t slot=0;slot<8;++slot) {
  EXPECT_EQ(groups.owns_slot(0,a->lease.generation,slot,T(0)),slot%2==0);
  EXPECT_EQ(groups.owns_slot(1,b->lease.generation,slot,T(0)),slot%2==1);
 }
}
TEST_F(Groups,OverlappingAdmissionDoesNotLeakUnclaimedSeats) {
 fs::NativeRecoveryGroups groups(4,100ms,Entropy);ASSERT_TRUE(groups.issue(3,T(0)));
 EXPECT_FALSE(groups.issue(6,T(0)));EXPECT_EQ(groups.reserved(),3u);
 EXPECT_TRUE(groups.issue(12,T(0)));EXPECT_EQ(groups.reserved(),15u);
}
TEST_F(Groups,InvalidMasksAndBoundsCannotReserveSeats) {
 fs::NativeRecoveryGroups groups(2,100ms,Entropy);
 for(uint32_t mask:{0u,4u,0xffffffffu})EXPECT_FALSE(groups.issue(mask,T(0)));
 EXPECT_EQ(groups.reserved(),0u);EXPECT_EQ(groups.members(65535),0u);
 EXPECT_FALSE(groups.owns_slot(65535,1,65535,T(0)));
 EXPECT_THROW(fs::NativeRecoveryGroups(0),std::invalid_argument);
 EXPECT_THROW(fs::NativeRecoveryGroups(33),std::invalid_argument);
}
TEST_F(Groups,EntropyFailureKeepsAdmissionAtomic) {
 fs::NativeRecoveryGroups groups(22,100ms,Entropy);fail_entropy=true;
 EXPECT_FALSE(groups.issue(fs::NativeRecoveryGroups::kAllSlots,T(0)));
 EXPECT_EQ(groups.reserved(),0u);
 fail_entropy=false;EXPECT_TRUE(groups.issue(fs::NativeRecoveryGroups::kAllSlots,T(0)));
}
TEST_F(Groups,PregameReleaseFreesEverySeatAndRejectsStaleOwner) {
 fs::NativeRecoveryGroups groups(4,100ms,Entropy);auto a=groups.issue(15,T(0));ASSERT_TRUE(a);
 EXPECT_FALSE(groups.release_admission(0,a->lease.generation+1,T(0)));
 EXPECT_EQ(groups.reserved(),15u);
 EXPECT_TRUE(groups.release_admission(0,a->lease.generation,T(1)));
 EXPECT_EQ(groups.reserved(),0u);
 auto b=groups.issue(15,T(2));ASSERT_TRUE(b);EXPECT_GT(b->lease.generation,a->lease.generation);
 EXPECT_FALSE(groups.release_admission(0,a->lease.generation,T(3)));EXPECT_EQ(groups.reserved(),15u);
}
TEST_F(Groups,RecoveryRotatesOwnershipForTheWholeGroupAtOnce) {
 fs::NativeRecoveryGroups groups(4,100ms,Entropy);auto a=groups.issue(15,T(0));ASSERT_TRUE(a);
 auto b=groups.begin(0,a->lease.match,a->lease.secret,T(1));ASSERT_TRUE(b);
 EXPECT_EQ(b->slots,15u);EXPECT_GT(b->lease.generation,a->lease.generation);
 for(uint16_t slot=0;slot<4;++slot) {
  EXPECT_FALSE(groups.owns_slot(0,a->lease.generation,slot,T(1)));
  EXPECT_TRUE(groups.owns_slot(0,b->lease.generation,slot,T(1)));
 }
 EXPECT_FALSE(groups.detach(0,a->lease.generation,T(2)));
 EXPECT_TRUE(groups.commit(0,b->lease.generation,b->lease.secret,T(2)));
 EXPECT_TRUE(groups.attached(0,b->lease.generation,T(2)));
}
TEST_F(Groups,NonPrimarySeatCannotRotateOrReleaseTheGroup) {
 fs::NativeRecoveryGroups groups(4,100ms,Entropy);auto a=groups.issue(15,T(0));ASSERT_TRUE(a);
 for(uint16_t slot=1;slot<4;++slot) {
  EXPECT_FALSE(groups.begin(slot,a->lease.match,a->lease.secret,T(1)));
  EXPECT_FALSE(groups.release_admission(slot,a->lease.generation,T(1)));
  EXPECT_FALSE(groups.revoke(slot,a->lease.generation,T(1)));
 }
 EXPECT_TRUE(groups.attached(0,a->lease.generation,T(1)));EXPECT_EQ(groups.reserved(),15u);
}
TEST_F(Groups,LostRecoveryResponsePreservesOriginalGraceAndMembership) {
 fs::NativeRecoveryGroups groups(4,100ms,Entropy);auto a=groups.issue(15,T(0));ASSERT_TRUE(a);
 ASSERT_TRUE(groups.detach(0,a->lease.generation,T(1)));
 auto b=groups.begin(0,a->lease.match,a->lease.secret,T(40));ASSERT_TRUE(b);
 ASSERT_TRUE(groups.detach(0,b->lease.generation,T(41)));
 auto c=groups.begin(0,a->lease.match,a->lease.secret,T(80));ASSERT_TRUE(c);
 EXPECT_EQ(c->lease.secret,b->lease.secret);EXPECT_EQ(c->slots,15u);
 EXPECT_TRUE(groups.detach(0,c->lease.generation,T(90)));
 EXPECT_FALSE(groups.begin(0,a->lease.match,a->lease.secret,T(101)));
 EXPECT_EQ(groups.reserved(),15u);
}
TEST_F(Groups,ReadyCommitIsIdempotentAndRetiresTheOldProof) {
 fs::NativeRecoveryGroups groups(2,100ms,Entropy);auto a=groups.issue(3,T(0));ASSERT_TRUE(a);
 auto b=groups.begin(0,a->lease.match,a->lease.secret,T(1));ASSERT_TRUE(b);
 EXPECT_TRUE(groups.commit(0,b->lease.generation,b->lease.secret,T(2)));
 EXPECT_TRUE(groups.commit(0,b->lease.generation,b->lease.secret,T(3)));
 EXPECT_FALSE(groups.begin(0,a->lease.match,a->lease.secret,T(4)));
 EXPECT_TRUE(groups.begin(0,b->lease.match,b->lease.secret,T(5)));
}
TEST_F(Groups,ExpiredGroupCannotControlAnyMember) {
 fs::NativeRecoveryGroups groups(22,100ms,Entropy);auto a=groups.issue(fs::NativeRecoveryGroups::kAllSlots,T(0));ASSERT_TRUE(a);
 ASSERT_TRUE(groups.detach(0,a->lease.generation,T(1)));
 for(uint16_t slot=0;slot<22;++slot)EXPECT_FALSE(groups.owns_slot(0,a->lease.generation,slot,T(101)));
 EXPECT_EQ(groups.members(0),fs::NativeRecoveryGroups::kAllSlots);
 EXPECT_TRUE(groups.release_admission(0,a->lease.generation,T(102)));EXPECT_EQ(groups.reserved(),0u);
}
TEST_F(Groups,SealedAdmissionCannotReassignExpiredGroups) {
 fs::NativeRecoveryGroups groups(4,100ms,Entropy);auto a=groups.issue(3,T(0));ASSERT_TRUE(a);
 groups.seal_admissions();EXPECT_FALSE(groups.issue(12,T(1)));
 ASSERT_TRUE(groups.detach(0,a->lease.generation,T(2)));
 EXPECT_FALSE(groups.owns(0,a->lease.generation,T(102)));
 EXPECT_FALSE(groups.release_admission(0,a->lease.generation,T(103)));EXPECT_EQ(groups.reserved(),3u);
}
TEST_F(Groups,RevocationRemovesAllPlayerControlWithoutTouchingOtherGroups) {
 fs::NativeRecoveryGroups groups(4,100ms,Entropy);auto a=groups.issue(3,T(0)),b=groups.issue(12,T(0));ASSERT_TRUE(a);ASSERT_TRUE(b);
 ASSERT_TRUE(groups.revoke(0,a->lease.generation,T(1)));
 EXPECT_FALSE(groups.owns_slot(0,a->lease.generation,0,T(1)));
 EXPECT_FALSE(groups.owns_slot(0,a->lease.generation,1,T(1)));
 EXPECT_TRUE(groups.owns_slot(2,b->lease.generation,2,T(1)));
 EXPECT_TRUE(groups.owns_slot(2,b->lease.generation,3,T(1)));
}
TEST_F(Groups,WrongMatchCannotReplaceTheOwner) {
 fs::NativeRecoveryGroups groups(2,100ms,Entropy);auto a=groups.issue(3,T(0));ASSERT_TRUE(a);
 auto match=a->lease.match;match[0]^=1;
 EXPECT_FALSE(groups.begin(0,match,a->lease.secret,T(1)));
 EXPECT_TRUE(groups.attached(0,a->lease.generation,T(1)));
}
TEST_F(Groups,ClockReversalDoesNotReleaseOrRotateMembership) {
 fs::NativeRecoveryGroups groups(4,100ms,Entropy);auto a=groups.issue(15,T(10));ASSERT_TRUE(a);
 EXPECT_FALSE(groups.release_admission(0,a->lease.generation,T(9)));
 EXPECT_FALSE(groups.begin(0,a->lease.match,a->lease.secret,T(9)));
 EXPECT_EQ(groups.reserved(),15u);EXPECT_TRUE(groups.attached(0,a->lease.generation,T(10)));
}
}
