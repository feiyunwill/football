#include "frame_sync/rl_training/checkpoint_file.hpp"
#include <gtest/gtest.h>
#include <fstream>
#include <iterator>
#include <csignal>
#include <sys/resource.h>
#include <sys/wait.h>
#include <thread>
#include <atomic>
namespace tr = football::training;
namespace {
class CheckpointFileTest : public ::testing::Test {
 protected:
  std::filesystem::path directory, target;
  std::string payload=std::string(8192,'x');
  void SetUp() override {
    auto pattern=(std::filesystem::temp_directory_path()/"football-training-file-XXXXXX").string();
    const auto* made=::mkdtemp(pattern.data());ASSERT_NE(made,nullptr);
    directory=made;target=directory/"training.tar";
    std::ofstream out(target,std::ios::binary);out<<"previous";
  }
  void TearDown() override { std::filesystem::remove_all(directory); }
  std::string Read() {
    std::ifstream in(target,std::ios::binary);
    return std::string(std::istreambuf_iterator<char>(in),{});
  }
  void NoScratch() {
    for (const auto& entry:std::filesystem::directory_iterator(directory))
      EXPECT_EQ(entry.path(),target);
  }
};
struct WriteFault : tr::checkpoint_file_detail::WriteOperations {
  enum Kind {Short,Interrupted,Full,Zero,FileSync,CloseFile,PublishFile,DirectorySync};
  Kind kind;int writes=0,syncs=0,closes=0;
  explicit WriteFault(Kind k):kind(k){}
  ssize_t Write(int fd,const char* data,size_t size) {
    ++writes;
    if (kind==Interrupted && writes==1) {errno=EINTR;return -1;}
    if (kind==Full) {errno=ENOSPC;return -1;}
    if (kind==Zero) return 0;
    return WriteOperations::Write(fd,data,kind==Short?std::min(size,size_t(11)):size);
  }
  int Sync(int fd) {
    ++syncs;
    if ((kind==FileSync&&syncs==1)||(kind==DirectorySync&&syncs==2)) {errno=EIO;return -1;}
    return WriteOperations::Sync(fd);
  }
  int Close(int fd) {
    ++closes;const auto result=WriteOperations::Close(fd);
    if (kind==CloseFile && closes==1) {errno=EIO;return -1;}return result;
  }
  int Publish(int dir,const char* temp,const char* dest) {
    if(kind==PublishFile) {errno=EACCES;return -1;}
    return WriteOperations::Publish(dir,temp,dest);
  }
};
TEST_F(CheckpointFileTest,BinaryRoundTripAndAtomicReplace) {
  payload[3]='\0';
  auto saved=tr::SaveCheckpointFile(payload,target);
  ASSERT_TRUE(saved);EXPECT_TRUE(saved.committed);EXPECT_EQ(saved.bytes,payload.size());
  auto loaded=tr::ReadCheckpointFile(target);
  ASSERT_TRUE(loaded);EXPECT_EQ(std::string(loaded.bytes.begin(),loaded.bytes.end()),payload);
  NoScratch();
}
TEST_F(CheckpointFileTest,EveryPrecommitFailurePreservesPreviousFile) {
  for(auto kind:{WriteFault::Full,WriteFault::Zero,WriteFault::FileSync,WriteFault::CloseFile,WriteFault::PublishFile}) {
    SCOPED_TRACE(kind);WriteFault fault(kind);
    auto result=tr::checkpoint_file_detail::Save(std::span<const char>(payload),target,fault);
    EXPECT_FALSE(result);EXPECT_FALSE(result.committed);EXPECT_TRUE(result.error);
    EXPECT_EQ(Read(),"previous");NoScratch();
  }
}
TEST_F(CheckpointFileTest,ShortAndInterruptedWritesRetainAllBytes) {
  for(auto kind:{WriteFault::Short,WriteFault::Interrupted}) {
    WriteFault fault(kind);
    auto result=tr::checkpoint_file_detail::Save(std::span<const char>(payload),target,fault);
    ASSERT_TRUE(result);EXPECT_EQ(Read(),payload);EXPECT_GT(fault.writes,1);NoScratch();
  }
}
TEST_F(CheckpointFileTest,DirectorySyncFailureReportsCommittedData) {
  WriteFault fault(WriteFault::DirectorySync);
  auto result=tr::checkpoint_file_detail::Save(std::span<const char>(payload),target,fault);
  EXPECT_FALSE(result);EXPECT_TRUE(result.committed);EXPECT_TRUE(result.error);
  EXPECT_EQ(Read(),payload);NoScratch();
}
TEST_F(CheckpointFileTest,RejectsEmptyAndOversizedPayloadBeforePublication) {
  EXPECT_FALSE(tr::SaveCheckpointFile({},target));
  EXPECT_FALSE(tr::SaveCheckpointFile(payload,target,16));
  EXPECT_EQ(Read(),"previous");NoScratch();
}
TEST_F(CheckpointFileTest,RejectsOversizedRegularFileBeforeReading) {
  EXPECT_EQ(::truncate(target.c_str(),tr::kMaxCheckpointFileBytes+1),0);
  auto result=tr::ReadCheckpointFile(target);
  EXPECT_FALSE(result);EXPECT_EQ(result.error.value(),EFBIG);EXPECT_TRUE(result.bytes.empty());
}
TEST_F(CheckpointFileTest,RejectsEmptyMissingDirectorySymlinkAndFifo) {
  auto empty=directory/"empty";std::ofstream{empty};
  auto link=directory/"link";ASSERT_EQ(::symlink(target.c_str(),link.c_str()),0);
  auto fifo=directory/"fifo";ASSERT_EQ(::mkfifo(fifo.c_str(),0600),0);
  for(const auto& path:{empty,directory/"missing",directory,link,fifo}) {
    SCOPED_TRACE(path);auto result=tr::ReadCheckpointFile(path);
    EXPECT_FALSE(result);EXPECT_TRUE(result.error);EXPECT_TRUE(result.bytes.empty());
  }
}
TEST_F(CheckpointFileTest,DoesNotPublishOverSymlinkOrSpecialFile) {
  auto link=directory/"link";ASSERT_EQ(::symlink(target.c_str(),link.c_str()),0);
  auto fifo=directory/"fifo";ASSERT_EQ(::mkfifo(fifo.c_str(),0600),0);
  EXPECT_FALSE(tr::SaveCheckpointFile(payload,link));
  EXPECT_FALSE(tr::SaveCheckpointFile(payload,fifo));
  EXPECT_TRUE(std::filesystem::is_symlink(link));EXPECT_TRUE(std::filesystem::is_fifo(fifo));
  EXPECT_EQ(Read(),"previous");
}
struct ReadFault : tr::checkpoint_file_detail::ReadOperations {
  enum Kind{Short,Interrupted,EarlyEnd,IOError,CloseError,Growth,Modified};
  Kind kind;int reads=0,stats=0;
  explicit ReadFault(Kind k):kind(k){}
  ssize_t Read(int fd,char* out,size_t size) {
    ++reads;
    if(kind==Interrupted && reads==1){errno=EINTR;return -1;}
    if(kind==EarlyEnd)return 0;
    if(kind==IOError){errno=EIO;return -1;}
    if(kind==Growth && size==1 && reads>1){*out='x';return 1;}
    return ReadOperations::Read(fd,out,kind==Short?std::min(size,size_t(2)):size);
  }
  int Stat(int fd,struct stat* info) {
    ++stats;int result=ReadOperations::Stat(fd,info);
    if(kind==Modified && stats==2)++info->st_mtim.tv_nsec;
    return result;
  }
  int Close(int fd) {
    int result=ReadOperations::Close(fd);
    if(kind==CloseError){errno=EIO;return -1;}return result;
  }
};
TEST_F(CheckpointFileTest,ShortAndInterruptedReadsRetainAllBytes) {
  for(auto kind:{ReadFault::Short,ReadFault::Interrupted}) {
    ReadFault fault(kind);
    auto result=tr::checkpoint_file_detail::Read(target,fault);
    ASSERT_TRUE(result);EXPECT_EQ(std::string(result.bytes.begin(),result.bytes.end()),"previous");
  }
}
TEST_F(CheckpointFileTest,ReadErrorsAndConcurrentChangesDiscardPartialData) {
  for(auto kind:{ReadFault::EarlyEnd,ReadFault::IOError,ReadFault::CloseError,ReadFault::Growth,ReadFault::Modified}) {
    SCOPED_TRACE(kind);ReadFault fault(kind);
    auto result=tr::checkpoint_file_detail::Read(target,fault);
    EXPECT_FALSE(result);EXPECT_TRUE(result.error);EXPECT_TRUE(result.bytes.empty());
  }
}
TEST_F(CheckpointFileTest,RealFileSizeLimitPreservesPreviousArchive) {
  const auto child=::fork();ASSERT_GE(child,0);
  if(child==0) {
    ::signal(SIGXFSZ,SIG_IGN);struct rlimit limit{128,128};
    if(::setrlimit(RLIMIT_FSIZE,&limit)!=0)_exit(2);
    const auto saved=tr::SaveCheckpointFile(payload,target);
    _exit(!saved && !saved.committed && saved.error.value()==EFBIG ? 0 : 3);
  }
  int status=0;ASSERT_EQ(::waitpid(child,&status,0),child);
  ASSERT_TRUE(WIFEXITED(status));EXPECT_EQ(WEXITSTATUS(status),0);
  EXPECT_EQ(Read(),"previous");NoScratch();
}
TEST_F(CheckpointFileTest,ConcurrentReaderSeesOnlyCompleteVersions) {
  ASSERT_TRUE(tr::SaveCheckpointFile(payload,target));
  std::atomic<bool> done=false,good=true;
  std::thread reader([&] {
    while(!done.load()) {
      auto row=tr::ReadCheckpointFile(target);
      if(!row){good=false;break;}
      auto text=std::string(row.bytes.begin(),row.bytes.end());
      if(text!=std::string(8192,'x') && text!=std::string(4096,'y')){good=false;break;}
    }
  });
  for(int i=0;i<20;++i) {
    std::string content(i%2?8192:4096,i%2?'x':'y');
    if(!tr::SaveCheckpointFile(content,target)){good=false;break;}
  }
  done=true;reader.join();EXPECT_TRUE(good);NoScratch();
}
}
