// 2026-09-13: bounded cooperative native replay storage and crash recovery.
// Linux local filesystems. Published recordings are never automatically pruned.
#ifndef GFOOTBALL_FRAME_SYNC_REPLAY_DIRECTORY_HPP
#define GFOOTBALL_FRAME_SYNC_REPLAY_DIRECTORY_HPP
#include "frame_sync/replay_file.hpp"
#include <chrono>
#include <dirent.h>
#include <memory>
#include <sys/file.h>
#include <sys/stat.h>
#include <thread>

namespace frame_sync {
struct ReplayDirectoryBudget {
  explicit ReplayDirectoryBudget(size_t files = 64, uint64_t bytes = 256ULL * 1024 * 1024,
                                 size_t entries = 4096, unsigned wait_ms = 2000)
      : file_limit(files), byte_limit(bytes), scan_limit(entries), lock_wait_ms(wait_ms) {
    if (!files || files > 1024 || bytes < 128 || bytes > 16ULL * 1024 * 1024 * 1024 ||
        // 2026-09-13: scans also visit the private temporary directory.
        // entries < files || entries > 16384 || wait_ms > 5000)
        entries <= files || entries > 16384 || wait_ms > 5000)
      throw std::invalid_argument("Invalid native replay directory budget");
  }
  ~ReplayDirectoryBudget() = default;
  ReplayDirectoryBudget(const ReplayDirectoryBudget&) = default;
  ReplayDirectoryBudget& operator=(const ReplayDirectoryBudget&) = delete;
  ReplayDirectoryBudget(ReplayDirectoryBudget&&) = default;
  ReplayDirectoryBudget& operator=(ReplayDirectoryBudget&&) = delete;
  const size_t file_limit;
  const uint64_t byte_limit;
  const size_t scan_limit;
  const unsigned lock_wait_ms;
};

namespace replay_directory_detail {
inline constexpr char kTemporaryDirectory[] = ".football-replay-tmp-v1";
class Descriptor {
 public:
  int value = -1;
  Descriptor() = default;
  Descriptor(const Descriptor&) = delete;
  Descriptor& operator=(const Descriptor&) = delete;
  Descriptor(Descriptor&&) = delete;
  Descriptor& operator=(Descriptor&&) = delete;
  ~Descriptor() { Close(); }
  std::error_code Close() noexcept {
    const int closing = std::exchange(value, -1);
    if (closing >= 0 && ::close(closing) != 0) return replay_file_detail::LastError();
    return {};
  }
};
inline void Check(bool ok, int error) {
  if (!ok) throw std::system_error(error, std::generic_category());
}
inline void CheckSystem(bool ok) {
  if (!ok) throw std::system_error(replay_file_detail::LastError());
}
inline bool Decimal(std::string_view value, uint64_t maximum) {
  if (value.empty() || value.size() > 20 || (value.size() > 1 && value[0] == '0')) return false;
  uint64_t number = 0;
  for (const char digit : value) {
    if (digit < '0' || digit > '9') return false;
    const auto part = static_cast<unsigned>(digit - '0');
    if (number > (maximum - part) / 10) return false;
    number = number * 10 + part;
  }
  return true;
}
inline bool ReplayName(std::string_view name) {
  if (!name.starts_with("replay_") || !name.ends_with(".bin")) return false;
  name.remove_prefix(7); name.remove_suffix(4);
  return Decimal(name, UINT32_MAX);
}
inline bool TemporaryName(std::string_view name) {
  constexpr std::string_view prefix = ".football-replay-";
  if (!name.starts_with(prefix) || !name.ends_with(".tmp")) return false;
  name.remove_prefix(prefix.size()); name.remove_suffix(4);
  const auto split = name.find('-');
  return split != std::string_view::npos && Decimal(name.substr(0, split), UINT64_MAX) &&
         Decimal(name.substr(split + 1), UINT64_MAX);
}
template<class Visitor>
void Scan(int directory, size_t limit, Visitor&& visitor) {
  // Fresh open description: no directory offsets shared with subsequent scans.
  const int fd = ::openat(directory, ".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  CheckSystem(fd >= 0);
  DIR* raw = ::fdopendir(fd);
  if (!raw) { const auto error = replay_file_detail::LastError(); ::close(fd); throw std::system_error(error); }
  // 2026-09-13: preserve RAII without discarding libc function attributes.
  // std::unique_ptr<DIR, decltype(&::closedir)> stream(raw, ::closedir);
  const auto close_directory = [](DIR* handle) noexcept { ::closedir(handle); };
  std::unique_ptr<DIR, decltype(close_directory)> stream(raw, close_directory);
  size_t entries = 0;
  for (;;) {
    errno = 0;
    const auto* entry = ::readdir(stream.get());
    if (!entry) { CheckSystem(errno == 0); return; }
    const std::string_view name(entry->d_name);
    if (name == "." || name == "..") continue;
    Check(++entries <= limit, E2BIG);
    visitor(name, entry->d_name);
  }
}
inline struct stat FileStatus(int directory, const char* name) {
  struct stat status{};
  CheckSystem(::fstatat(directory, name, &status, AT_SYMLINK_NOFOLLOW) == 0);
  Check(S_ISREG(status.st_mode) && status.st_uid == ::geteuid() && status.st_nlink == 1 &&
        status.st_size >= 0, EINVAL);
  return status;
}
struct Operations : replay_file_detail::FileOperations {
  void Bind(int parent, int temporary) { parent_ = parent; temporary_ = temporary; opened_parent_ = -1; }
  int OpenDirectory(const char*) {
    opened_parent_ = ::fcntl(parent_, F_DUPFD_CLOEXEC, 0);
    return opened_parent_;
  }
  std::filesystem::path TemporaryPath(const std::filesystem::path& parent, const char* name) {
    return parent / kTemporaryDirectory / name;
  }
  int Create(int, const char* name) { return FileOperations::Create(temporary_, name); }
  int Remove(int, const char* name) { return FileOperations::Remove(temporary_, name); }
  int Publish(int directory, const char* temporary, const char* destination) {
    return ::renameat(temporary_, temporary, directory, destination);
  }
  int Sync(int fd) {
    if (fd != opened_parent_) return FileOperations::Sync(fd);
    // The shared Save() already marks committed=true here. Attempt both
    // directory syncs after cross-directory rename; do not disguise publication.
    const int temporary_result = FileOperations::Sync(temporary_);
    const int temporary_error = errno;
    const int parent_result = FileOperations::Sync(fd);
    if (temporary_result != 0) { errno = temporary_error; return temporary_result; }
    return parent_result;
  }
 private:
  int parent_ = -1, temporary_ = -1, opened_parent_ = -1;
};
// 2026-09-13: disk admission uses the complete envelope byte count.
// template<class IO>
// ReplayFileResult Save(const ReplayRecorder& recorder, const std::filesystem::path& path,
template<class IO,class Recorder>
ReplayFileResult Save(const Recorder& recorder, const std::filesystem::path& path,
                      const ReplayDirectoryBudget& budget, IO& operations) {
  ReplayFileResult result;
  Descriptor parent, temporary;
  auto finish = [&]() {
    const auto temporary_error = temporary.Close();
    const auto parent_error = parent.Close();
    if (!result.cleanup_error) result.cleanup_error = temporary_error ? temporary_error : parent_error;
    return std::move(result);
  };
  try {
    const auto filename = path.filename().string();
    // 2026-09-14: reuse the content predicate for checkpoint-only atomic saves.
    // Check(path.native().find('\0') == std::string::npos && recorder.GetFrameCount() &&
    Check(path.native().find('\0') == std::string::npos && replay_file_detail::HasReplayContent(recorder) &&
          filename == "replay_" + std::to_string(recorder.GetMetadata().seed) + ".bin", EINVAL);
    const auto expected_bytes = recorder.GetSerializedBytes();
    Check(expected_bytes && expected_bytes <= budget.byte_limit, EDQUOT);
    const auto directory = path.has_parent_path() ? path.parent_path() : std::filesystem::path(".");
    result.stage = "open replay directory";
    parent.value = ::open(directory.c_str(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    CheckSystem(parent.value >= 0);
    result.stage = "lock replay directory";
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(budget.lock_wait_ms);
    while (::flock(parent.value, LOCK_EX | LOCK_NB) != 0) {
      const int error = errno;
      Check(error == EWOULDBLOCK || error == EAGAIN || error == EINTR, error);
      Check(std::chrono::steady_clock::now() < deadline, EWOULDBLOCK);
      std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    result.stage = "open replay temporary directory";
    if (::mkdirat(parent.value, kTemporaryDirectory, 0700) != 0) CheckSystem(errno == EEXIST);
    temporary.value = ::openat(parent.value, kTemporaryDirectory, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    CheckSystem(temporary.value >= 0);
    struct stat directory_status{};
    CheckSystem(::fstat(temporary.value, &directory_status) == 0);
    Check(directory_status.st_uid == ::geteuid() && (directory_status.st_mode & 0777) == 0700, EACCES);

    result.stage = "recover interrupted replay writes";
    // Only strict scratch names inside this private, versioned app directory
    // are owned. Unknown entries and legacy parent scratch are preserved.
    // The parent directory lock excludes every active cooperative writer.
    std::vector<std::string> interrupted;
    Scan(temporary.value, budget.scan_limit, [&](std::string_view name, const char* raw) {
      if (!TemporaryName(name)) return;
      const auto status = FileStatus(temporary.value, raw);
      Check((status.st_mode & 0077) == 0, EACCES);
      Check(interrupted.size() < 1024, E2BIG);
      interrupted.emplace_back(name);
    });
    for (const auto& name : interrupted) CheckSystem(::unlinkat(temporary.value, name.c_str(), 0) == 0);
    if (!interrupted.empty()) CheckSystem(::fsync(temporary.value) == 0);

    result.stage = "inspect replay directory budget";
    uint64_t used_bytes = 0;
    size_t used_files = 0;
    bool replacing = false;
    auto account = [&](int directory_fd, const char* name) {
      const auto status = FileStatus(directory_fd, name);
      const auto bytes = static_cast<uint64_t>(status.st_size);
      Check(bytes <= budget.byte_limit - used_bytes, EDQUOT);
      used_bytes += bytes;
      Check(++used_files <= budget.file_limit, EDQUOT);
    };
    Scan(parent.value, budget.scan_limit, [&](std::string_view name, const char* raw) {
      if (!ReplayName(name) && !TemporaryName(name)) return;
      account(parent.value, raw);
      if (name == filename) replacing = true;
    });
    Scan(temporary.value, budget.scan_limit, [&](std::string_view, const char* raw) {
      account(temporary.value, raw);
    });
    result.stage = "admit replay file count";
    Check(replacing || used_files < budget.file_limit, EDQUOT);
    result.stage = "admit replay bytes";
    // Count the old destination PLUS the new scratch payload during replacement.
    Check(expected_bytes <= budget.byte_limit - used_bytes, EDQUOT);
    operations.Bind(parent.value, temporary.value);
    result = replay_file_detail::Save(recorder, path, operations);
    if (result) Check(result.bytes == expected_bytes, EIO);
  } catch (const std::system_error& error) {
    result.error = error.code();
  }
  return finish();
}
}  // namespace replay_directory_detail
// Frozen recorder, canonical replay_<seed>.bin. Limits cover cooperating writes,
// legacy native scratch, and new payload during replacement. Published files
// are never pruned. Logical payload bytes exclude filesystem metadata and
// unrelated parent files. At most one new pending file exists while locked.
// 2026-09-13: same atomic writer supports explicit product replay metadata.
// inline ReplayFileResult SaveManagedReplayFile(const ReplayRecorder& recorder,
template<class Recorder>
inline ReplayFileResult SaveManagedReplayFile(const Recorder& recorder,
                                              const std::filesystem::path& path,
                                              const ReplayDirectoryBudget& budget = ReplayDirectoryBudget()) {
  replay_directory_detail::Operations operations;
  return replay_directory_detail::Save(recorder, path, budget, operations);
}
}  // namespace frame_sync
#endif
