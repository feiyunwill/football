
#include "frame_sync/native_authority_recording.hpp"
#include <gtest/gtest.h>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <vector>
#include <atomic>
#include <csignal>
#include <sys/resource.h>
#include <unistd.h>
namespace {
namespace fs=frame_sync;
namespace path=std::filesystem;
class AuthorityRecording : public ::testing::Test {
 protected:
  path::path dir;
  const fs::NativeMatchContract match{0x12345678,11,11};
  const std::vector<uint8_t> header{'F','T','A','C',0x78,0x56,0x34,0x12,11,11,2,0};
  void SetUp() override {
    std::string pattern=(path::temp_directory_path()/"football-authority-XXXXXX").string();
    char* value=mkdtemp(pattern.data());ASSERT_NE(value,nullptr);dir=value;
  }
  void TearDown() override {if(!dir.empty())path::remove_all(dir);}
  static std::vector<uint8_t> Read(const path::path& file) {
    std::ifstream input(file,std::ios::binary);
    return {std::istreambuf_iterator<char>(input),{}};
  }
};
TEST_F(AuthorityRecording,HeaderPinsMatchAndPhysicsBeforeReturn) {
 auto record=fs::OpenNativeAuthorityRecording((dir/"trace").c_str(),match);
 EXPECT_EQ(Read(dir/"trace"),header);
}
TEST_F(AuthorityRecording,EveryPacketIsVisibleInOriginalOrderBeforeClose) {
 auto record=fs::OpenNativeAuthorityRecording((dir/"trace").c_str(),match);auto expected=header;
 for(uint8_t kind:{3,4,10,11}) {
  const std::array<uint8_t,9> row{kind,0,1,2,3,4,5,6,7};
  record(row);expected.insert(expected.end(),row.begin(),row.end());
  EXPECT_EQ(Read(dir/"trace"),expected);
 }
}
TEST_F(AuthorityRecording,ExistingFileIsNotOverwritten) {
 auto record=fs::OpenNativeAuthorityRecording((dir/"trace").c_str(),match);
 EXPECT_THROW(fs::OpenNativeAuthorityRecording((dir/"trace").c_str(),match),std::runtime_error);
 EXPECT_EQ(Read(dir/"trace"),header);
}
TEST_F(AuthorityRecording,SymlinkDoesNotOverwriteItsTarget) {
 auto record=fs::OpenNativeAuthorityRecording((dir/"trace").c_str(),match);
 path::create_symlink(dir/"trace",dir/"link");
 EXPECT_THROW(fs::OpenNativeAuthorityRecording((dir/"link").c_str(),match),std::runtime_error);
 EXPECT_EQ(Read(dir/"trace"),header);
}
TEST_F(AuthorityRecording,MissingParentIsAnExplicitError) {
 EXPECT_THROW(fs::OpenNativeAuthorityRecording((dir/"absent/trace").c_str(),match),std::runtime_error);
}
TEST_F(AuthorityRecording,InvalidMatchCannotCreateAFile) {
 auto invalid=match;invalid.left=12;
 EXPECT_THROW(fs::OpenNativeAuthorityRecording((dir/"invalid").c_str(),invalid),std::invalid_argument);
 EXPECT_FALSE(path::exists(dir/"invalid"));
}
TEST_F(AuthorityRecording,NullOrEmptyPathIsRejected) {
 EXPECT_THROW(fs::OpenNativeAuthorityRecording(nullptr,match),std::invalid_argument);
 EXPECT_THROW(fs::OpenNativeAuthorityRecording("",match),std::invalid_argument);
}
TEST_F(AuthorityRecording,EmptyOrUnsupportedPacketCannotAppend) {
 auto record=fs::OpenNativeAuthorityRecording((dir/"trace").c_str(),match);
 EXPECT_THROW(record({}),std::invalid_argument);
 const std::array<uint8_t,1> wrong{90};EXPECT_THROW(record(wrong),std::invalid_argument);
 EXPECT_EQ(Read(dir/"trace"),header);
}
TEST_F(AuthorityRecording,OnlyTheFrameOwnerCanAppend) {
 auto record=fs::OpenNativeAuthorityRecording((dir/"trace").c_str(),match);
 std::atomic<bool> rejected=false;
 std::thread other([&]{try{record(std::array<uint8_t,1>{3});}catch(const std::runtime_error&){rejected=true;}});
 other.join();EXPECT_TRUE(rejected);EXPECT_EQ(Read(dir/"trace"),header);
}
TEST_F(AuthorityRecording,ByteBudgetRejectsBeforeWriting) {
 auto record=fs::OpenNativeAuthorityRecording((dir/"trace").c_str(),match);
 std::vector<uint8_t> large(64*1024*1024,0);large[0]=3;
 EXPECT_THROW(record(large),std::length_error);EXPECT_EQ(Read(dir/"trace"),header);
}
TEST_F(AuthorityRecording,ActualFlushFailurePropagates) {
 auto record=fs::OpenNativeAuthorityRecording((dir/"trace").c_str(),match);
 rlimit previous{};ASSERT_EQ(getrlimit(RLIMIT_FSIZE,&previous),0);
 auto original_signal=std::signal(SIGXFSZ,SIG_IGN);
 auto bounded=previous;bounded.rlim_cur=header.size();
 const int limited=setrlimit(RLIMIT_FSIZE,&bounded);
 bool rejected=false;
 if(limited==0) {
  try{record(std::array<uint8_t,1>{3});}catch(const std::runtime_error&){rejected=true;}
 }
 const int restored=setrlimit(RLIMIT_FSIZE,&previous);std::signal(SIGXFSZ,original_signal);
 ASSERT_EQ(limited,0);ASSERT_EQ(restored,0);EXPECT_TRUE(rejected);EXPECT_EQ(Read(dir/"trace"),header);
}
}
