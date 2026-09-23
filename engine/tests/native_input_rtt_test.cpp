#include "frame_sync/native_input_publication.hpp"
#include "fixtures/native_input/original_clock.inc"
#include "fixtures/native_input/unpaced_lead_clock.inc"
#include <gtest/gtest.h>
#include <cmath>
#include <limits>
#include <vector>
namespace fs=frame_sync;
namespace {
std::int64_t now=0;
std::int64_t Clock(){return now;}
template<class Scheduler> size_t OnTime(Scheduler schedule) {
  size_t accepted=0;
  // Independent deadline model: 50 ms authority path + 50 ms outbound path;
  // server collects every 20 ms. Sampling continues every millisecond.
  for(std::int64_t ms=100;ms<2100;++ms) {
    const auto authority=static_cast<fs::frame_id_t>((ms-50)/20+1);
    const auto frame=schedule(authority,ms*1000000);
    if(frame && ms+50 < std::int64_t(*frame+1)*20)++accepted;
  }
  return accepted;
}
TEST(NativeInputRTT,OldOneFrameLeadMissesHundredMillisecondRoundTrip) {
  fs::OriginalNativePublicationClock old;
  const auto old_on_time=OnTime([&](auto a,auto t){return old.Next(a,0,t);});
  fs::NativePublicationClock current;
  const auto new_on_time=OnTime([&](auto a,auto t){
    return current.Next(a,0,t,fs::NativePublicationClock::LeadFrames(100));});
  EXPECT_EQ(old_on_time,0u);EXPECT_GE(new_on_time,95u);
}
TEST(NativeInputRTT,ZeroAndLowLatencyKeepOriginalOneFrameLead) {
  EXPECT_EQ(fs::NativePublicationClock::LeadFrames(0),1u);
  EXPECT_EQ(fs::NativePublicationClock::LeadFrames(.1),1u);
  EXPECT_EQ(fs::NativePublicationClock::LeadFrames(20),1u);
  EXPECT_EQ(fs::NativePublicationClock::LeadFrames(20.01),2u);
  EXPECT_EQ(fs::NativePublicationClock::LeadFrames(100),5u);
}
TEST(NativeInputRTT,ExtremeDelayIsBoundedByUnchangedServerWindow) {
  EXPECT_EQ(fs::NativePublicationClock::LeadFrames(1e300),fs::ServerInputWindow::kFrames-1);
  fs::NativePublicationClock clock;
  const auto frame=clock.Next(10,0,0,fs::NativePublicationClock::LeadFrames(1e300));
  ASSERT_TRUE(frame);EXPECT_LT(*frame-10,fs::ServerInputWindow::kFrames);
}
TEST(NativeInputRTT,InvalidBudgetAndLeadRejectBeforeMutation) {
  for(double value:{-1.,std::numeric_limits<double>::infinity(),std::numeric_limits<double>::quiet_NaN()})
    EXPECT_THROW(fs::NativePublicationClock::LeadFrames(value),std::invalid_argument);
  fs::NativePublicationClock clock;
  EXPECT_THROW(clock.Next(0,0,0,0),std::invalid_argument);
  EXPECT_THROW(clock.Next(0,0,0,fs::ServerInputWindow::kFrames),std::invalid_argument);
  EXPECT_EQ(clock.Next(0,0,0),1u);
}
TEST(NativeInputRTT,LeadChangesNeverRewriteOrReorderPublishedFrames) {
  fs::NativePublicationClock clock;std::optional<fs::frame_id_t> last;
  for(std::int64_t ms=0;ms<3000;++ms) {
    const auto a=static_cast<fs::frame_id_t>(ms/20);
    const auto lead=fs::NativePublicationClock::LeadFrames(ms<500?0:ms<1500?140:20);
    auto frame=clock.Next(a,0,ms*1000000,lead);
    if(frame) {if(last)EXPECT_GT(*frame,*last);EXPECT_LT(*frame-a,fs::ServerInputWindow::kFrames);last=frame;}
  }
}
TEST(NativeInputRTT,PublicationKeepsExactSampleAndRecoveryClearsLead) {
  fs::LocalInputHistory history;fs::NativePublishedHistory published(history,Clock);
  std::vector<std::pair<fs::frame_id_t,fs::SlotInput>> sent;size_t samples=0;
  auto sample=[&](auto){++samples;return fs::SlotInput{1,0,512};};
  auto send=[&](auto f,const auto& input){sent.emplace_back(f,input);return true;};
  now=0;EXPECT_EQ(published.PublishTimed(0,sample,send,100),5u);
  EXPECT_FALSE(published.PublishTimed(0,sample,send,100));
  EXPECT_EQ(samples,1u);ASSERT_EQ(sent.size(),1u);
  EXPECT_EQ(published.Read(5,0).buttons,512);
  published.Reset(100);now=100000000;
  EXPECT_EQ(published.PublishTimed(100,sample,send,0),101u);
  EXPECT_EQ(samples,2u);
}
TEST(NativeInputRTT,FullWindowWaitDoesNotSkipFutureInputAfterAuthorityBatch) {
  fs::UnpacedLeadClock old;
  fs::NativePublicationClock current;
  std::vector<fs::frame_id_t> before,after;
  for(std::int64_t ms=0;ms<2000;++ms) {
    const auto known=static_cast<fs::frame_id_t>((ms/60)*3);
    if(auto frame=old.Next(known,0,ms*1000000,15))before.push_back(*frame);
    if(auto frame=current.Next(known,0,ms*1000000,15))after.push_back(*frame);
  }
  auto gaps=[](const auto& rows) {
    size_t count=0;
    for(size_t i=1;i<rows.size();++i)if(rows[i]!=rows[i-1]+1)++count;
    return count;
  };
  EXPECT_GE(gaps(before),30u);
  ASSERT_GE(after.size(),95u);
  EXPECT_EQ(gaps(after),0u);
}

TEST(NativeInputRTT,LargeAuthorityJumpReanchorsTheMeasuredHorizon) {
  fs::NativePublicationClock clock;
  EXPECT_EQ(clock.Next(0,0,0,5),5u);
  EXPECT_EQ(clock.Next(100,0,2000000000,5),105u);
  EXPECT_FALSE(clock.Next(100,0,2000000000,5));
  EXPECT_EQ(clock.Next(101,0,2020000000,5),106u);
}

}
