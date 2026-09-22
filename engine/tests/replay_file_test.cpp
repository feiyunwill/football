// 2026-09-10: real-file publication, bounded encoding and failure recovery.
#include "frame_sync/replay_file.hpp"
#include <gtest/gtest.h>
#include <fstream>
#include <iterator>
#include <iostream>
#include <functional>
#include <latch>
#include <csignal>
#include <sys/resource.h>
#include <sys/wait.h>
#include <thread>

namespace fs = frame_sync;
namespace {
class ReplayFileTest : public ::testing::Test {
 protected:
  void SetUp() override {
    auto pattern = (std::filesystem::temp_directory_path() / "football-replay-file-XXXXXX").string();
    const char* created = ::mkdtemp(pattern.data());
    ASSERT_NE(created, nullptr);
    directory = created;
    target = directory / "replay_42.bin";
  }
  void TearDown() override { std::filesystem::remove_all(directory); }
  fs::ReplayRecorder Recorder(uint32_t seed = 42, uint32_t count = 200) {
    fs::ReplayRecorder recorder;
    recorder.StartRecording(seed, "streamed_native_replay", 22);
    for (uint32_t frame = 0; frame < count; ++frame) {
      if (!recorder.RecordFrame(frame, Hash(frame, seed), Inputs(frame)))
        throw std::runtime_error("recording fixture exceeded budget");
    }
    return recorder;
  }
  static uint64_t Hash(uint32_t frame, uint32_t seed = 42) {
    return (uint64_t(frame) * 0x9e3779b97f4a7c15ULL) ^ seed;
  }
  static std::vector<fs::SlotInput> Inputs(uint32_t frame) {
    std::vector<fs::SlotInput> values(22);
    for (unsigned slot = 0; slot < values.size(); ++slot) {
      values[slot].dir_x = float(int((frame + slot) % 9) - 4) / 4;
      values[slot].dir_y = float(int((frame * 3 + slot) % 9) - 4) / 4;
      values[slot].buttons = (frame + slot) % 2 ? 1 : 0;
    }
    return values;
  }
  static std::string Read(const std::filesystem::path& path) {
    // 2026-09-10: size and data must come from the same opened file while an
    // atomic writer replaces the directory entry in the concurrent-reader case.
    // std::ifstream input(path, std::ios::binary);
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input) throw std::runtime_error("could not open saved replay");
    // const auto size = std::filesystem::file_size(path);
    const auto ending = input.tellg();
    if (ending < 0) throw std::runtime_error("could not measure opened replay");
    const auto size = static_cast<size_t>(ending);
    if (size > 64 * 1024 * 1024) throw std::runtime_error("test replay exceeds read budget");
    std::string data(size, '\0');
    input.seekg(0);
    input.read(data.data(), data.size());
    if (static_cast<size_t>(input.gcount()) != size) throw std::runtime_error("truncated saved replay");
    return data;
  }
  static size_t ResidentBytes() {
    std::ifstream input("/proc/self/smaps_rollup");
    std::string line;
    while (std::getline(input, line)) {
      if (line.starts_with("Rss:")) return std::stoull(line.substr(4)) * 1024;
    }
    throw std::runtime_error("RSS unavailable");
  }
  void OldFile() { std::ofstream(target, std::ios::binary) << "existing replay must survive"; }
  size_t Entries() { return std::distance(std::filesystem::directory_iterator(directory), {}); }
  std::filesystem::path directory, target;
};

struct FaultOperations : fs::replay_file_detail::FileOperations {
  enum Fault { None, ShortWrite, ZeroWrite, WriteError, SyncFile, CloseFile, PublishFile, SyncDirectory,
               CleanupError, ThrowWrite, CreateError } fault = None;
  int writes = 0, syncs = 0, closes = 0;
  int Create(int directory, const char* name) {
    if (fault == CreateError) { errno = ENOSPC; return -1; }
    return FileOperations::Create(directory, name);
  }
  ssize_t Write(int fd, const char* data, size_t size) {
    ++writes;
    if (fault == ThrowWrite) throw std::bad_alloc();
    if (fault == ShortWrite && writes == 1) { errno = EINTR; return -1; }
    if (fault == ZeroWrite && writes > 1) return 0;
    if ((fault == WriteError || fault == CleanupError) && writes > 1) { errno = ENOSPC; return -1; }
    return FileOperations::Write(fd, data, fault == ShortWrite ? std::min(size, size_t{7}) : size);
  }
  int Sync(int fd) {
    ++syncs;
    if ((fault == SyncFile && syncs == 1) || (fault == SyncDirectory && syncs == 2)) {
      errno = EIO; return -1;
    }
    return FileOperations::Sync(fd);
  }
  int Close(int fd) {
    ++closes;
    const int result = FileOperations::Close(fd);
    if (fault == CloseFile && closes == 1) { errno = EIO; return -1; }
    return result;
  }
  int Publish(int directory, const char* temporary, const char* destination) {
    if (fault == PublishFile) { errno = EACCES; return -1; }
    return FileOperations::Publish(directory, temporary, destination);
  }
  int Remove(int directory, const char* name) {
    if (fault == CleanupError) { errno = EACCES; return -1; }
    return FileOperations::Remove(directory, name);
  }
};

struct ObservedOperations : fs::replay_file_detail::FileOperations {
  std::function<void()> observe;
  size_t calls = 0;
  ssize_t Write(int fd, const char* data, size_t size) {
    if (calls++ % 128 == 0) observe();
    return FileOperations::Write(fd, data, size);
  }
};

TEST_F(ReplayFileTest, ChunksAreBoundedAndExactlyMatchExistingWireFormat) {
  auto recorder = Recorder();
  std::string actual;
  size_t largest = 0, calls = 0;
  const auto count = recorder.SerializeTo([&](std::string_view chunk) {
    ASSERT_FALSE(chunk.empty());
    ASSERT_LE(chunk.size(), 4096u);
    largest = std::max(largest, chunk.size());
    ++calls;
    actual.append(chunk);
  });
  EXPECT_EQ(actual, recorder.Serialize());
  EXPECT_EQ(count, actual.size());
  EXPECT_EQ(largest, 4096u);
  EXPECT_GT(calls, 10u);
  EXPECT_TRUE(recorder.IsRecording());
  const auto before = actual;
  EXPECT_THROW(recorder.SerializeTo([](std::string_view) { throw std::runtime_error("sink"); }),
               std::runtime_error);
  EXPECT_EQ(recorder.Serialize(), before);
}

TEST_F(ReplayFileTest, ShortWritesAndInterruptedWritesPreserveEveryByte) {
  OldFile();
  auto recorder = Recorder();
  FaultOperations operations;
  operations.fault = FaultOperations::ShortWrite;
  auto result = fs::replay_file_detail::Save(recorder, target, operations);
  ASSERT_TRUE(result) << result.error.message();
  EXPECT_EQ(result.bytes, recorder.Serialize().size());
  EXPECT_GT(operations.writes, 1000);
  EXPECT_EQ(Read(target), recorder.Serialize());
  EXPECT_EQ(Entries(), 1u);
}

TEST_F(ReplayFileTest, EveryPreCommitIoFailurePreservesOldFileAndAllowsRetry) {
  for (auto fault : {FaultOperations::ZeroWrite, FaultOperations::WriteError, FaultOperations::SyncFile,
                     FaultOperations::CloseFile, FaultOperations::PublishFile, FaultOperations::CreateError}) {
    SCOPED_TRACE(fault);
    OldFile();
    const auto original = Read(target);
    auto recorder = Recorder();
    FaultOperations operations;
    operations.fault = fault;
    auto result = fs::replay_file_detail::Save(recorder, target, operations);
    EXPECT_FALSE(result);
    EXPECT_FALSE(result.committed);
    EXPECT_TRUE(result.error);
    EXPECT_FALSE(result.cleanup_error);
    EXPECT_EQ(Read(target), original);
    EXPECT_EQ(Entries(), 1u);
    // Failed close must not be retried; the second close is the directory.
    EXPECT_EQ(operations.closes, fault == FaultOperations::CreateError ? 1 : 2);
    ASSERT_TRUE(fs::SaveReplayFile(recorder, target));
    EXPECT_EQ(Read(target), recorder.Serialize());
  }
}

TEST_F(ReplayFileTest, CommittedDirectorySyncFailureIsNotReportedAsOldData) {
  OldFile();
  auto recorder = Recorder();
  FaultOperations operations;
  operations.fault = FaultOperations::SyncDirectory;
  auto result = fs::replay_file_detail::Save(recorder, target, operations);
  EXPECT_FALSE(result);
  EXPECT_TRUE(result.committed);
  EXPECT_EQ(result.error.value(), EIO);
  EXPECT_STREQ(result.stage, "sync directory");
  EXPECT_EQ(Read(target), recorder.Serialize());
  EXPECT_EQ(Entries(), 1u);
}

TEST_F(ReplayFileTest, CleanupFailureIsObservableAndDoesNotRemoveSomeoneElsesFile) {
  OldFile();
  const auto original = Read(target);
  std::ofstream(directory / ".football-replay-unrelated.tmp") << "unrelated";
  FaultOperations operations;
  operations.fault = FaultOperations::CleanupError;
  auto result = fs::replay_file_detail::Save(Recorder(), target, operations);
  EXPECT_FALSE(result.committed);
  EXPECT_EQ(result.error.value(), ENOSPC);
  EXPECT_EQ(result.cleanup_error.value(), EACCES);
  EXPECT_TRUE(std::filesystem::exists(result.temporary_path));
  EXPECT_EQ(Read(target), original);
  EXPECT_EQ(Read(directory / ".football-replay-unrelated.tmp"), "unrelated");
  EXPECT_EQ(Entries(), 3u);
}

TEST_F(ReplayFileTest, ExceptionsReleaseTemporaryFileAndDescriptors) {
  OldFile();
  const auto before = Read(target);
  const auto descriptor_count = [] {
    return std::distance(std::filesystem::directory_iterator("/proc/self/fd"), {});
  };
  const auto initial = descriptor_count();
  for (unsigned attempt = 0; attempt < 100; ++attempt) {
    FaultOperations operations;
    operations.fault = FaultOperations::ThrowWrite;
    EXPECT_THROW(fs::replay_file_detail::Save(Recorder(), target, operations), std::bad_alloc);
    EXPECT_EQ(operations.closes, 2);
    EXPECT_EQ(Entries(), 1u);
  }
  EXPECT_EQ(descriptor_count(), initial);
  EXPECT_EQ(Read(target), before);
}

TEST_F(ReplayFileTest, InvalidPathsAndEmptyRecordingsDoNotCreateFiles) {
  auto recorder = Recorder();
  for (const auto& path : {directory / "missing" / "replay.bin", directory,
                          directory / ".", directory / "..",
                          directory / std::string("nul\0suffix", 10)}) {
    auto result = fs::SaveReplayFile(recorder, path);
    EXPECT_FALSE(result);
    EXPECT_FALSE(result.committed);
    EXPECT_TRUE(result.error);
    EXPECT_EQ(Entries(), 0u);
  }
  auto result = fs::SaveReplayFile(fs::ReplayRecorder{}, target);
  EXPECT_FALSE(result);
  EXPECT_EQ(Entries(), 0u);
}

TEST_F(ReplayFileTest, MaximumReplayReopensInAnotherProcessAndKeepsEveryFrame) {
  // Warm filesystem and libc paths before measuring the large save's RSS.
  ASSERT_TRUE(fs::SaveReplayFile(Recorder(), target));
  auto recorder = Recorder(42, 100000);
  EXPECT_FALSE(recorder.IsRecording());
  EXPECT_EQ(recorder.GetStopReason(), fs::ReplayStopReason::Capacity);
  EXPECT_LE(recorder.GetRetainedBytes(), 32u * 1024 * 1024);
  const auto rss_before = ResidentBytes();
  size_t rss_max = rss_before;
  ObservedOperations operations;
  operations.observe = [&] { rss_max = std::max(rss_max, ResidentBytes()); };
  const auto started = std::chrono::steady_clock::now();
  auto result = fs::replay_file_detail::Save(recorder, target, operations);
  const auto save_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now() - started).count();
  const auto rss_after = ResidentBytes();
  ASSERT_TRUE(result);
  // A whole 23 MB serialized copy would exceed this explicit scratch allowance.
  EXPECT_LE(std::max(rss_max, rss_after), rss_before + 1024 * 1024);
  EXPECT_EQ(result.bytes, 28u + recorder.GetMetadata().scenario.size() + 100000u * (12u + 22u * 10u));
  EXPECT_EQ(std::filesystem::file_size(target), result.bytes);
  const auto child = ::fork();
  ASSERT_GE(child, 0);
  if (child == 0) {
    bool valid = true;
    try {
      fs::ReplayPlayer player;
      valid = player.LoadReplay(Read(target)) && player.GetTotalFrames() == 100000 &&
              player.GetRetainedBytes() <= 32u * 1024 * 1024 && player.GetMetadata().seed == 42;
      for (uint32_t number = 0; valid && number < 100000; ++number) {
        const auto frame = player.GetFrameAt(number);
        valid = frame && frame->frame_number == number && frame->state_hash == Hash(number) &&
                frame->inputs == Inputs(number);
      }
    } catch (...) { valid = false; }
    ::_exit(valid ? 0 : 1);
  }
  int status = 0;
  ASSERT_EQ(::waitpid(child, &status, 0), child);
  ASSERT_TRUE(WIFEXITED(status));
  EXPECT_EQ(WEXITSTATUS(status), 0);
  EXPECT_EQ(Entries(), 1u);
  if (const char* artifact = std::getenv("FOOTBALL_REPLAY_FILE_EVIDENCE")) {
    ASSERT_FALSE(std::filesystem::exists(artifact));
    ASSERT_TRUE(std::filesystem::copy_file(target, artifact));
  }
  std::cout << "REPLAY_FILE_EVIDENCE {\"frames\":100000,\"slots\":22,\"bytes\":" << result.bytes
            << ",\"retained_bytes\":" << recorder.GetRetainedBytes()
            << ",\"rss_before\":" << rss_before << ",\"rss_after\":" << rss_after
            << ",\"rss_sampled_max\":" << rss_max << ",\"write_calls\":" << operations.calls
            << ",\"save_ns\":" << save_ns << "}\n";
}

TEST_F(ReplayFileTest, RealFilesystemLimitRejectsWriteAndPreservesOldReplay) {
  OldFile();
  const auto before = Read(target);
  auto recorder = Recorder();
  const auto child = ::fork();
  ASSERT_GE(child, 0);
  if (child == 0) {
    std::signal(SIGXFSZ, SIG_IGN);
    const rlimit limit{64, 64};
    if (::setrlimit(RLIMIT_FSIZE, &limit) != 0) ::_exit(2);
    const auto result = fs::SaveReplayFile(recorder, target);
    const bool valid = !result && !result.committed && result.error.value() == EFBIG &&
                       result.bytes == 64 && !result.cleanup_error && Read(target) == before && Entries() == 1;
    ::_exit(valid ? 0 : 1);
  }
  int status = 0;
  ASSERT_EQ(::waitpid(child, &status, 0), child);
  ASSERT_TRUE(WIFEXITED(status));
  EXPECT_EQ(WEXITSTATUS(status), 0);
  EXPECT_EQ(Read(target), before);
  EXPECT_EQ(Entries(), 1u);
  EXPECT_TRUE(fs::SaveReplayFile(recorder, target));
}

TEST_F(ReplayFileTest, ConcurrentReaderAlwaysSeesOneCompletePublishedVersion) {
  const auto first = Recorder(42, 30);
  const auto second = Recorder(43, 200);
  const auto first_bytes = first.Serialize(), second_bytes = second.Serialize();
  ASSERT_TRUE(fs::SaveReplayFile(first, target));
  std::atomic<unsigned> reads{0}, invalid{0};
  std::latch ready{1};
  std::jthread reader([&](std::stop_token stop) {
    try {
      while (!stop.stop_requested()) {
        const auto data = Read(target);
        if (data != first_bytes && data != second_bytes) ++invalid;
        if (++reads == 1) ready.count_down();
      }
    } catch (...) {
      ++invalid;
      if (!reads.load()) ready.count_down();
    }
  });
  ready.wait();
  for (unsigned round = 0; round < 64; ++round)
    ASSERT_TRUE(fs::SaveReplayFile(round % 2 ? first : second, target));
  reader.request_stop();
  reader.join();
  EXPECT_GT(reads.load(), 0u);
  EXPECT_EQ(invalid.load(), 0u);
  EXPECT_EQ(Read(target), first_bytes);
  EXPECT_EQ(Entries(), 1u);
}
}  // namespace
