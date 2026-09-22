// 2026-09-13: actual native directory admission, process locking and crash recovery.
#include "frame_sync/replay_directory.hpp"
#include <gtest/gtest.h>
#include <fstream>
#include <csignal>
#include <poll.h>
#include <sys/wait.h>

namespace fs = frame_sync;
namespace rd = frame_sync::replay_directory_detail;
namespace {
class Child {
 public:
  pid_t pid = -1;
  ~Child() { if (pid > 0) { ::kill(pid, SIGKILL); int status; while (::waitpid(pid, &status, 0) < 0 && errno == EINTR) {} } }
  int Wait() {
    int status = 0; pid_t result;
    do { result = ::waitpid(pid, &status, 0); } while (result < 0 && errno == EINTR);
    if (result != pid) throw std::runtime_error("could not reap owned child");
    pid = -1;
    return status;
  }
};
class ReplayDirectoryTest : public ::testing::Test {
 protected:
  void SetUp() override {
    auto pattern = (std::filesystem::temp_directory_path() / "football-replay-directory-XXXXXX").string();
    const auto* created = ::mkdtemp(pattern.data()); ASSERT_NE(created, nullptr);
    directory = created; temporary = directory / rd::kTemporaryDirectory;
  }
  void TearDown() override {
    if (!directory.empty()) {
      ASSERT_EQ(directory.parent_path(), std::filesystem::temp_directory_path());
      ASSERT_TRUE(directory.filename().string().starts_with("football-replay-directory-"));
      std::filesystem::remove_all(directory);
    }
  }
  std::filesystem::path Path(uint32_t seed = 42) { return directory / ("replay_" + std::to_string(seed) + ".bin"); }
  fs::ReplayRecorder Recorder(uint32_t seed = 42, uint32_t count = 3, size_t slots = 2) {
    fs::ReplayRecorder recorder; recorder.StartRecording(seed, "directory", slots);
    std::vector<fs::SlotInput> input(slots);
    for (uint32_t frame = 0; frame < count; ++frame) {
      for (size_t slot = 0; slot < slots; ++slot) {
        input[slot].dir_x = float(int((frame + slot) % 9) - 4) / 4;
        input[slot].dir_y = float(int((frame * 3 + slot) % 9) - 4) / 4;
        input[slot].buttons = (frame + slot) % 2;
      }
      if (!recorder.RecordFrame(frame, uint64_t(frame) * 97 + seed, input))
        throw std::runtime_error("recording fixture refused a valid frame");
    }
    recorder.StopRecording(); return recorder;
  }
  static std::string Read(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file || file.tellg() < 0 || file.tellg() > 64 * 1024 * 1024) throw std::runtime_error("invalid saved file");
    std::string bytes(static_cast<size_t>(file.tellg()), '\0'); file.seekg(0);
    file.read(bytes.data(), bytes.size());
    if (static_cast<size_t>(file.gcount()) != bytes.size()) throw std::runtime_error("short file");
    return bytes;
  }
  static void Write(const std::filesystem::path& path, std::string_view bytes) {
    std::ofstream file(path, std::ios::binary); file.write(bytes.data(), bytes.size()); file.close();
    if (!file) throw std::runtime_error("fixture write failed");
  }
  static size_t Fds() { return std::distance(std::filesystem::directory_iterator("/proc/self/fd"), {}); }
  size_t Pending() {
    if (!std::filesystem::exists(temporary)) return 0;
    size_t count = 0;
    for (const auto& entry : std::filesystem::directory_iterator(temporary))
      count += rd::TemporaryName(entry.path().filename().string());
    return count;
  }
  std::filesystem::path directory, temporary;
};
struct ThrowWrite : rd::Operations {
  ssize_t Write(int, const char*, size_t) { throw std::bad_alloc(); }
};
struct StopWrite : rd::Operations {
  int ready = -1;
  ssize_t Write(int fd, const char* data, size_t size) {
    const auto count = FileOperations::Write(fd, data, std::min(size, size_t{64}));
    if (count <= 0 || ::fsync(fd) != 0 || ::write(ready, "x", 1) != 1) ::_exit(90);
    ::raise(SIGSTOP);
    ::_exit(91);
  }
};
struct DirectorySyncFailure : rd::Operations {
  bool published = false;
  int Publish(int directory, const char* temporary, const char* destination) {
    const int result = Operations::Publish(directory, temporary, destination);
    published = result == 0; return result;
  }
  int Sync(int fd) {
    if (published) { errno = EIO; return -1; }
    return Operations::Sync(fd);
  }
};

TEST_F(ReplayDirectoryTest, RejectsInvalidBudgetsBeforeFilesystemUse) {
  EXPECT_THROW(fs::ReplayDirectoryBudget(0), std::invalid_argument);
  EXPECT_THROW(fs::ReplayDirectoryBudget(1025), std::invalid_argument);
  EXPECT_THROW(fs::ReplayDirectoryBudget(1, 127), std::invalid_argument);
  EXPECT_THROW(fs::ReplayDirectoryBudget(1, UINT64_MAX), std::invalid_argument);
  EXPECT_THROW(fs::ReplayDirectoryBudget(3, 1024, 2), std::invalid_argument);
  EXPECT_THROW(fs::ReplayDirectoryBudget(1, 1024, 1), std::invalid_argument);
  EXPECT_THROW(fs::ReplayDirectoryBudget(1, 1024, 16385), std::invalid_argument);
  EXPECT_THROW(fs::ReplayDirectoryBudget(1, 1024, 20, 5001), std::invalid_argument);
  EXPECT_TRUE(std::filesystem::is_empty(directory));
}
TEST_F(ReplayDirectoryTest, RequiresCanonicalSeedNameAndNonemptyRecording) {
  auto recorder = Recorder();
  for (const auto& name : {"other.bin", "replay_43.bin", "replay_042.bin", "..", "."}) {
    const auto result = fs::SaveManagedReplayFile(recorder, directory / name);
    EXPECT_FALSE(result); EXPECT_FALSE(result.committed); EXPECT_EQ(result.error.value(), EINVAL);
  }
  fs::ReplayRecorder empty;
  EXPECT_FALSE(fs::SaveManagedReplayFile(empty, Path(0)));
  EXPECT_FALSE(fs::SaveManagedReplayFile(recorder, std::filesystem::path(std::string("bad\0replay_42.bin", 17))));
  EXPECT_TRUE(std::filesystem::is_empty(directory));
  auto largest = Recorder(UINT32_MAX);
  ASSERT_TRUE(fs::SaveManagedReplayFile(largest, Path(UINT32_MAX)));
  EXPECT_EQ(Read(Path(UINT32_MAX)), largest.Serialize());
  EXPECT_EQ(largest.GetSerializedBytes(), largest.Serialize().size());
}
TEST_F(ReplayDirectoryTest, CountFillsRejectsPreservesFilesAndRecoversAfterExplicitRemoval) {
  const fs::ReplayDirectoryBudget budget(2, 4096);
  auto first = Recorder(42), second = Recorder(43), third = Recorder(44);
  ASSERT_TRUE(fs::SaveManagedReplayFile(first, Path(42), budget));
  ASSERT_TRUE(fs::SaveManagedReplayFile(second, Path(43), budget));
  const auto result = fs::SaveManagedReplayFile(third, Path(44), budget);
  EXPECT_FALSE(result); EXPECT_EQ(result.error.value(), EDQUOT); EXPECT_FALSE(result.committed);
  EXPECT_FALSE(std::filesystem::exists(Path(44))); EXPECT_EQ(Pending(), 0);
  EXPECT_EQ(Read(Path(42)), first.Serialize()); EXPECT_EQ(Read(Path(43)), second.Serialize());
  ASSERT_TRUE(std::filesystem::remove(Path(43)));
  ASSERT_TRUE(fs::SaveManagedReplayFile(third, Path(44), budget));
  EXPECT_EQ(Read(Path(44)), third.Serialize());
}
TEST_F(ReplayDirectoryTest, ByteQuotaIncludesOldDestinationAndNewScratchDuringReplacement) {
  auto first = Recorder(42), second = Recorder(43), replacement = Recorder(42, 4);
  const fs::ReplayDirectoryBudget budget(8, first.GetSerializedBytes() + replacement.GetSerializedBytes());
  ASSERT_TRUE(fs::SaveManagedReplayFile(first, Path(42), budget));
  ASSERT_TRUE(fs::SaveManagedReplayFile(second, Path(43), budget));
  const auto result = fs::SaveManagedReplayFile(replacement, Path(42), budget);
  EXPECT_FALSE(result); EXPECT_EQ(result.error.value(), EDQUOT);
  EXPECT_EQ(Read(Path(42)), first.Serialize()); EXPECT_EQ(Pending(), 0);
  ASSERT_TRUE(std::filesystem::remove(Path(43)));
  ASSERT_TRUE(fs::SaveManagedReplayFile(replacement, Path(42), budget));
  EXPECT_EQ(Read(Path(42)), replacement.Serialize());
}
TEST_F(ReplayDirectoryTest, SameSeedCanReplaceAtFileCountLimit) {
  auto first = Recorder(), second = Recorder(42, 4);
  const fs::ReplayDirectoryBudget budget(1, 4096);
  for (int cycle = 0; cycle < 50; ++cycle) {
    auto& value = cycle % 2 ? first : second;
    ASSERT_TRUE(fs::SaveManagedReplayFile(value, Path(), budget));
    EXPECT_EQ(Read(Path()), value.Serialize()); EXPECT_EQ(Pending(), 0);
  }
}
TEST_F(ReplayDirectoryTest, MinimumScanBudgetIncludesPrivateDirectoryAndAllowsReplacement) {
  auto first = Recorder(), second = Recorder(42, 4);
  const fs::ReplayDirectoryBudget budget(1, 4096, 2);
  ASSERT_TRUE(fs::SaveManagedReplayFile(first, Path(), budget));
  ASSERT_TRUE(fs::SaveManagedReplayFile(second, Path(), budget));
  EXPECT_EQ(Read(Path()), second.Serialize()); EXPECT_EQ(Pending(), 0);
}
TEST_F(ReplayDirectoryTest, DefaultFileCountRejectsTheSixtyFifthDistinctSeed) {
  for (uint32_t seed = 0; seed < 64; ++seed) {
    ASSERT_TRUE(fs::SaveManagedReplayFile(Recorder(seed), Path(seed)));
  }
  const auto result = fs::SaveManagedReplayFile(Recorder(64), Path(64));
  EXPECT_FALSE(result); EXPECT_EQ(result.error.value(), EDQUOT);
  EXPECT_FALSE(std::filesystem::exists(Path(64))); EXPECT_EQ(Pending(), 0);
  ASSERT_TRUE(fs::SaveManagedReplayFile(Recorder(42, 4), Path(42)));
  for (uint32_t seed = 0; seed < 64; ++seed) {
    EXPECT_EQ(Read(Path(seed)), Recorder(seed, seed == 42 ? 4 : 3).Serialize());
  }
}
TEST_F(ReplayDirectoryTest, UnsafeInterruptedLinksAreRejectedWithoutRemovingThem) {
  auto recorder = Recorder();
  ASSERT_TRUE(fs::SaveManagedReplayFile(recorder, Path()));
  const auto other = directory / "keep.txt", pending = temporary / ".football-replay-1-2.tmp";
  Write(other, "user");
  std::filesystem::create_symlink(other, pending);
  EXPECT_FALSE(fs::SaveManagedReplayFile(recorder, Path()));
  EXPECT_TRUE(std::filesystem::is_symlink(pending)); EXPECT_EQ(Read(other), "user");
  std::filesystem::remove(pending); std::filesystem::create_hard_link(other, pending);
  EXPECT_FALSE(fs::SaveManagedReplayFile(recorder, Path()));
  EXPECT_EQ(Read(pending), "user"); EXPECT_EQ(Read(other), "user");
  EXPECT_EQ(Read(Path()), recorder.Serialize());
}
TEST_F(ReplayDirectoryTest, PrivateUnknownAndLegacyParentScratchArePreservedAndCounted) {
  auto recorder = Recorder();
  ASSERT_TRUE(fs::SaveManagedReplayFile(recorder, Path()));
  Write(temporary / "keep.txt", "keep");
  const auto legacy = directory / ".football-replay-123-4.tmp";
  Write(legacy, std::string(400, 'x'));
  const fs::ReplayDirectoryBudget budget(4, 512);
  EXPECT_FALSE(fs::SaveManagedReplayFile(recorder, Path(), budget));
  EXPECT_EQ(Read(legacy), std::string(400, 'x')); EXPECT_EQ(Read(temporary / "keep.txt"), "keep");
  ASSERT_TRUE(std::filesystem::remove(legacy));
  ASSERT_TRUE(fs::SaveManagedReplayFile(recorder, Path(), budget));
  EXPECT_EQ(Read(temporary / "keep.txt"), "keep"); EXPECT_EQ(Pending(), 0);
}
TEST_F(ReplayDirectoryTest, RejectsSymlinkedScratchDirectoryAndLinkedPublishedFiles) {
  auto recorder = Recorder();
  const auto other = directory / "other"; std::filesystem::create_directory(other);
  Write(other / "keep.txt", "unchanged");
  std::filesystem::create_directory_symlink(other, temporary);
  EXPECT_FALSE(fs::SaveManagedReplayFile(recorder, Path()));
  EXPECT_EQ(Read(other / "keep.txt"), "unchanged"); EXPECT_FALSE(std::filesystem::exists(Path()));
  std::filesystem::remove(temporary);
  std::filesystem::create_symlink(other / "keep.txt", Path());
  EXPECT_FALSE(fs::SaveManagedReplayFile(recorder, Path()));
  EXPECT_TRUE(std::filesystem::is_symlink(Path()));
  std::filesystem::remove(Path()); std::filesystem::create_hard_link(other / "keep.txt", Path());
  EXPECT_FALSE(fs::SaveManagedReplayFile(recorder, Path()));
  EXPECT_EQ(Read(Path()), "unchanged"); EXPECT_EQ(Read(other / "keep.txt"), "unchanged");
}
TEST_F(ReplayDirectoryTest, RejectsUnsafeScratchPermissionsAndBoundsUnrelatedDirectoryScan) {
  auto recorder = Recorder();
  std::filesystem::create_directory(temporary); ASSERT_EQ(::chmod(temporary.c_str(), 0777), 0);
  const auto permissions = fs::SaveManagedReplayFile(recorder, Path());
  EXPECT_FALSE(permissions); EXPECT_EQ(permissions.error.value(), EACCES);
  ASSERT_EQ(::chmod(temporary.c_str(), 0700), 0);
  for (int i = 0; i < 4; ++i) Write(directory / ("other-" + std::to_string(i)), "user");
  const auto scan = fs::SaveManagedReplayFile(recorder, Path(), fs::ReplayDirectoryBudget(1, 4096, 3));
  EXPECT_FALSE(scan); EXPECT_EQ(scan.error.value(), E2BIG); EXPECT_FALSE(std::filesystem::exists(Path()));
  for (int i = 0; i < 4; ++i) EXPECT_EQ(Read(directory / ("other-" + std::to_string(i))), "user");
}
TEST_F(ReplayDirectoryTest, KilledWriterReleasesLockAndOnlyOwnedInterruptedFileIsRecovered) {
  auto first = Recorder(), second = Recorder(42, 100);
  ASSERT_TRUE(fs::SaveManagedReplayFile(first, Path()));
  Write(temporary / "keep.txt", "user");
  int pipe_fds[2]; ASSERT_EQ(::pipe2(pipe_fds, O_CLOEXEC), 0);
  rd::Descriptor reader, writer; reader.value = pipe_fds[0]; writer.value = pipe_fds[1];
  Child child; child.pid = ::fork(); ASSERT_GE(child.pid, 0);
  if (child.pid == 0) {
    reader.Close(); StopWrite operations; operations.ready = writer.value;
    rd::Save(second, Path(), fs::ReplayDirectoryBudget(), operations); ::_exit(92);
  }
  writer.Close();
  pollfd event{reader.value, POLLIN, 0}; ASSERT_EQ(::poll(&event, 1, 5000), 1);
  char signal; ASSERT_EQ(::read(reader.value, &signal, 1), 1);
  EXPECT_EQ(Pending(), 1); EXPECT_EQ(Read(Path()), first.Serialize());
  const auto blocked = fs::SaveManagedReplayFile(first, Path(), fs::ReplayDirectoryBudget(64, 4096, 4096, 0));
  EXPECT_FALSE(blocked); EXPECT_EQ(blocked.error.value(), EWOULDBLOCK);
  EXPECT_EQ(Pending(), 1);
  ASSERT_EQ(::kill(child.pid, SIGKILL), 0);
  const int status = child.Wait(); ASSERT_TRUE(WIFSIGNALED(status)); EXPECT_EQ(WTERMSIG(status), SIGKILL);
  EXPECT_EQ(Read(Path()), first.Serialize());
  ASSERT_TRUE(fs::SaveManagedReplayFile(second, Path()));
  EXPECT_EQ(Read(Path()), second.Serialize()); EXPECT_EQ(Pending(), 0);
  EXPECT_EQ(Read(temporary / "keep.txt"), "user");
}
TEST_F(ReplayDirectoryTest, ThreeProcessesShareTheSameSingleFileAdmission) {
  const fs::ReplayDirectoryBudget budget(1, 4096, 4096, 5000);
  int pipe_fds[2]; ASSERT_EQ(::pipe2(pipe_fds, O_CLOEXEC), 0);
  rd::Descriptor reader, writer; reader.value = pipe_fds[0]; writer.value = pipe_fds[1];
  Child children[3];
  for (int i = 0; i < 3; ++i) {
    children[i].pid = ::fork(); ASSERT_GE(children[i].pid, 0);
    if (children[i].pid == 0) {
      writer.Close(); char start; if (::read(reader.value, &start, 1) != 1) ::_exit(90);
      auto recorder = Recorder(42 + i);
      const auto result = fs::SaveManagedReplayFile(recorder, Path(42 + i), budget);
      ::_exit(result ? 0 : result.error.value() == EDQUOT ? 77 : 91);
    }
  }
  reader.Close(); ASSERT_EQ(::write(writer.value, "xxx", 3), 3); writer.Close();
  int accepted = 0, refused = 0;
  for (auto& child : children) {
    const int status = child.Wait(); ASSERT_TRUE(WIFEXITED(status));
    accepted += WEXITSTATUS(status) == 0; refused += WEXITSTATUS(status) == 77;
  }
  EXPECT_EQ(accepted, 1); EXPECT_EQ(refused, 2); EXPECT_EQ(Pending(), 0);
  int files = 0;
  for (int i = 0; i < 3; ++i) if (std::filesystem::exists(Path(42 + i))) {
    ++files; EXPECT_EQ(Read(Path(42 + i)), Recorder(42 + i).Serialize());
  }
  EXPECT_EQ(files, 1);
}
TEST_F(ReplayDirectoryTest, AllocationExceptionsReleaseLockDescriptorsAndPendingFiles) {
  auto recorder = Recorder();
  ASSERT_TRUE(fs::SaveManagedReplayFile(recorder, Path()));
  const auto before = Fds();
  for (int cycle = 0; cycle < 100; ++cycle) {
    ThrowWrite operations;
    EXPECT_THROW(rd::Save(recorder, Path(), fs::ReplayDirectoryBudget(), operations), std::bad_alloc);
    EXPECT_EQ(Pending(), 0); EXPECT_EQ(Read(Path()), recorder.Serialize());
  }
  EXPECT_EQ(Fds(), before);
  ASSERT_TRUE(fs::SaveManagedReplayFile(recorder, Path(), fs::ReplayDirectoryBudget(64, 4096, 4096, 0)));
}
TEST_F(ReplayDirectoryTest, CommittedSyncFailureRemainsPublishedAndConsumesQuota) {
  auto recorder = Recorder();
  const fs::ReplayDirectoryBudget budget(1, 4096);
  DirectorySyncFailure operations;
  const auto result = rd::Save(recorder, Path(), budget, operations);
  EXPECT_FALSE(result); EXPECT_TRUE(result.committed); EXPECT_EQ(result.error.value(), EIO);
  EXPECT_EQ(Read(Path()), recorder.Serialize()); EXPECT_EQ(Pending(), 0);
  EXPECT_FALSE(fs::SaveManagedReplayFile(Recorder(43), Path(43), budget));
  EXPECT_FALSE(std::filesystem::exists(Path(43)));
}
TEST_F(ReplayDirectoryTest, MaximumRecordingUsesTheSameWireBytesAndReplacesWithinPeakBudget) {
  auto recorder = Recorder(42, 100000, 22);
  ASSERT_EQ(recorder.GetFrameCount(), 100000);
  const fs::ReplayDirectoryBudget budget(1, 2 * recorder.GetSerializedBytes());
  for (int repetition = 0; repetition < 2; ++repetition) {
    const auto result = fs::SaveManagedReplayFile(recorder, Path(), budget);
    ASSERT_TRUE(result) << result.stage << ": " << result.error.message();
    EXPECT_EQ(result.bytes, recorder.GetSerializedBytes());
    EXPECT_TRUE(Read(Path()) == recorder.Serialize());
    EXPECT_EQ(Pending(), 0);
  }
}
}  // namespace
