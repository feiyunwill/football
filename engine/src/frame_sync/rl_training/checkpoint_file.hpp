// Copyright 2026 Google LLC & Contributors
// Bounded file I/O; TAR/state validation remains the training serializer's responsibility.
#ifndef FOOTBALL_TRAINING_CHECKPOINT_FILE_HPP
#define FOOTBALL_TRAINING_CHECKPOINT_FILE_HPP
#include "frame_sync/atomic_file.hpp"
#include <algorithm>
#include <limits>
#include <new>
#include <span>
#include <sys/stat.h>
#include <vector>
namespace football::training {
inline constexpr size_t kMaxCheckpointFileBytes = 64u * 1024u * 1024u;
namespace checkpoint_file_detail {
struct Bytes {
  std::span<const char> payload;
  template<class Sink> void SerializeTo(Sink&& sink) const {
    sink(std::string_view(payload.data(), payload.size()));
  }
};
template<class Operations>
frame_sync::AtomicFileResult Save(std::span<const char> payload,
    const std::filesystem::path& path, Operations& operations,
    size_t max_bytes = kMaxCheckpointFileBytes) {
  if (payload.empty() || payload.size() > max_bytes) {
    frame_sync::AtomicFileResult result;
    result.error = {payload.empty() ? EINVAL : EFBIG, std::generic_category()};
    return result;
  }
  return frame_sync::atomic_file_detail::Save(Bytes{payload}, path, operations,
                                             true, ".football-checkpoint");
}
struct WriteOperations : frame_sync::atomic_file_detail::FileOperations {
  int Publish(int directory, const char* temporary, const char* destination) {
    struct stat target{};
    if (::fstatat(directory, destination, &target, AT_SYMLINK_NOFOLLOW) == 0) {
      if (!S_ISREG(target.st_mode)) { errno = EINVAL; return -1; }
    } else if (errno != ENOENT) { return -1; }
    return FileOperations::Publish(directory, temporary, destination);
  }
};
struct ReadOperations {
  int Open(const char* path) { return ::open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK); }
  int Stat(int fd, struct stat* info) { return ::fstat(fd, info); }
  ssize_t Read(int fd, char* data, size_t size) { return ::read(fd, data, size); }
  int Close(int fd) { return ::close(fd); }
};
}
inline frame_sync::AtomicFileResult SaveCheckpointFile(std::span<const char> payload,
    const std::filesystem::path& path, size_t max_bytes = kMaxCheckpointFileBytes) {
  checkpoint_file_detail::WriteOperations operations;
  return checkpoint_file_detail::Save(payload, path, operations, max_bytes);
}
struct CheckpointFileRead {
  std::vector<char> bytes;
  std::error_code error;
  const char* stage = "validate";
  explicit operator bool() const { return !error && !bytes.empty(); }
};
namespace checkpoint_file_detail {
template<class Operations>
CheckpointFileRead Read(const std::filesystem::path& path, Operations& operations,
                        size_t max_bytes = kMaxCheckpointFileBytes) {
  CheckpointFileRead result;
  if (path.empty() || path.native().find('\0') != std::string::npos || !max_bytes) {
    result.error = {EINVAL, std::generic_category()}; return result;
  }
  result.stage = "open";
  const int fd = operations.Open(path.c_str());
  if (fd < 0) { result.error = frame_sync::atomic_file_detail::LastError(); return result; }
  struct Owner {
    Operations& ops; int fd;
    ~Owner() { if (fd >= 0) ops.Close(fd); }
  } owner{operations, fd};
  auto fail = [&](std::error_code error) {
    result.error = error;
    std::vector<char>().swap(result.bytes);
    return std::move(result);
  };
  result.stage = "stat";
  struct stat before{};
  if (operations.Stat(fd, &before) != 0) return fail(frame_sync::atomic_file_detail::LastError());
  if (!S_ISREG(before.st_mode) || before.st_size <= 0)
    return fail({EINVAL, std::generic_category()});
  if (static_cast<uintmax_t>(before.st_size) > max_bytes ||
      static_cast<uintmax_t>(before.st_size) > result.bytes.max_size())
    return fail({EFBIG, std::generic_category()});
  result.stage = "allocate";
  try { result.bytes.resize(static_cast<size_t>(before.st_size)); }
  catch (const std::bad_alloc&) { return fail({ENOMEM, std::generic_category()}); }
  result.stage = "read";
  size_t offset = 0;
  while (offset < result.bytes.size()) {
    const size_t count = std::min(result.bytes.size()-offset,
                                  static_cast<size_t>(std::numeric_limits<ssize_t>::max()));
    const auto got = operations.Read(fd, result.bytes.data()+offset, count);
    if (got < 0 && errno == EINTR) continue;
    if (got < 0) return fail(frame_sync::atomic_file_detail::LastError());
    if (got == 0 || static_cast<size_t>(got) > count) return fail({EIO, std::generic_category()});
    offset += static_cast<size_t>(got);
  }
  // Detect truncation/growth or concurrent in-place writes instead of handing
  // a mixed version to the TAR reader. Atomic publishers leave this inode stable.
  char extra;
  ssize_t tail;
  do { tail = operations.Read(fd, &extra, 1); } while (tail < 0 && errno == EINTR);
  if (tail < 0) return fail(frame_sync::atomic_file_detail::LastError());
  if (tail != 0) return fail({EIO, std::generic_category()});
  struct stat after{};
  if (operations.Stat(fd, &after) != 0) return fail(frame_sync::atomic_file_detail::LastError());
  if (before.st_size != after.st_size ||
      before.st_mtim.tv_sec != after.st_mtim.tv_sec ||
      before.st_mtim.tv_nsec != after.st_mtim.tv_nsec)
    return fail({EIO, std::generic_category()});
  result.stage = "close";
  owner.fd = -1;
  if (operations.Close(fd) != 0) return fail(frame_sync::atomic_file_detail::LastError());
  result.stage = "complete";
  return result;
}
}
inline CheckpointFileRead ReadCheckpointFile(const std::filesystem::path& path,
                                             size_t max_bytes = kMaxCheckpointFileBytes) {
  checkpoint_file_detail::ReadOperations operations;
  return checkpoint_file_detail::Read(path, operations, max_bytes);
}
} // namespace football::training
#endif
