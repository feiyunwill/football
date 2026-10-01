// Copyright 2026 Google LLC & Contributors
// Linux local-filesystem atomic publication shared by replays and training archives.
#ifndef FOOTBALL_ATOMIC_FILE_HPP
#define FOOTBALL_ATOMIC_FILE_HPP
#include <atomic>
#include <cerrno>
#include <cstdio>
#include <cstdint>
#include <filesystem>
#include <fcntl.h>
#include <string_view>
#include <system_error>
#include <utility>
#include <unistd.h>
namespace frame_sync {
struct AtomicFileResult {
  size_t bytes = 0;
  bool committed = false;
  std::error_code error;
  std::error_code cleanup_error;
  const char* stage = "validate";
  // Populated before creating the file; useful if cleanup itself fails.
  std::filesystem::path temporary_path;
  explicit operator bool() const { return committed && !error && !cleanup_error; }
};
namespace atomic_file_detail {
inline std::error_code LastError() {
  return {errno ? errno : EIO, std::generic_category()};
}

// The operation boundary also permits deterministic I/O fault injection while
// tests continue to create, write, rename and read actual filesystem objects.
struct FileOperations {
  int OpenDirectory(const char* path) { return ::open(path, O_RDONLY | O_DIRECTORY | O_CLOEXEC); }
  // 2026-09-13: managed writers can place scratch files in an owned child
  // directory while sharing this publication/error-handling implementation.
  std::filesystem::path TemporaryPath(const std::filesystem::path& parent, const char* name) {
    return parent / name;
  }
  int Create(int directory, const char* name) {
    return ::openat(directory, name, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
  }
  ssize_t Write(int fd, const char* data, size_t size) { return ::write(fd, data, size); }
  int Sync(int fd) { return ::fsync(fd); }
  int Close(int fd) { return ::close(fd); }
  int Publish(int directory, const char* temporary, const char* destination) {
    return ::renameat(directory, temporary, directory, destination);
  }
  int Remove(int directory, const char* name) { return ::unlinkat(directory, name, 0); }
};

template<class Operations>
class TemporaryFile {
 public:
  TemporaryFile(Operations& operations, int directory)
      : operations_(operations), directory_(directory) {}
  TemporaryFile(const TemporaryFile&) = delete;
  TemporaryFile& operator=(const TemporaryFile&) = delete;
  ~TemporaryFile() { Cleanup(); }
  int file = -1;
  char name[96]{};
  bool owned = false;
  std::error_code Cleanup() noexcept {
    std::error_code error;
    if (file >= 0) {
      const int closing = std::exchange(file, -1);
      // Linux releases the descriptor even on close errors: never retry close.
      if (operations_.Close(closing) != 0) error = LastError();
    }
    if (owned) {
      owned = false;
      int removed;
      do { removed = operations_.Remove(directory_, name); } while (removed != 0 && errno == EINTR);
      if (removed != 0 && !error) error = LastError();
    }
    if (directory_ >= 0) {
      const int closing = std::exchange(directory_, -1);
      if (operations_.Close(closing) != 0 && !error) error = LastError();
    }
    return error;
  }
 private:
  Operations& operations_;
  int directory_;
};

template<class Operations, class Recorder>
AtomicFileResult Save(const Recorder& recorder, const std::filesystem::path& path,
                      Operations& operations, bool has_content,
                      const char* temporary_prefix = ".football-file") {
  AtomicFileResult result;
  const auto filename = path.filename().string();
  if (filename.empty() || filename == "." || filename == ".." ||
      path.native().find('\0') != std::string::npos || !has_content) {
    result.error = {EINVAL, std::generic_category()};
    return result;
  }
  const auto parent = path.has_parent_path() ? path.parent_path() : std::filesystem::path(".");
  result.stage = "open directory";
  const int directory = operations.OpenDirectory(parent.c_str());
  if (directory < 0) { result.error = LastError(); return result; }
  TemporaryFile<Operations> temporary(operations, directory);
  auto finish = [&]() {
    result.cleanup_error = temporary.Cleanup();
    // Avoid allocating a path copy after publication.
    return std::move(result);
  };
  result.stage = "create temporary file";
  static std::atomic<uint64_t> next{0};
  for (unsigned attempt = 0; attempt < 64; ++attempt) {
    std::snprintf(temporary.name, sizeof(temporary.name), "%s-%ld-%llu.tmp", temporary_prefix,
                  static_cast<long>(::getpid()),
                  static_cast<unsigned long long>(next.fetch_add(1, std::memory_order_relaxed)));
    result.temporary_path = operations.TemporaryPath(parent, temporary.name);
    temporary.file = operations.Create(directory, temporary.name);
    if (temporary.file >= 0) { temporary.owned = true; break; }
    if (errno != EEXIST) { result.error = LastError(); return finish(); }
  }
  if (temporary.file < 0) { result.error = {EEXIST, std::generic_category()}; return finish(); }
  result.stage = "write";
  try {
    recorder.SerializeTo([&](std::string_view chunk) {
      while (!chunk.empty()) {
        const auto written = operations.Write(temporary.file, chunk.data(), chunk.size());
        if (written < 0 && errno == EINTR) continue;
        if (written < 0) throw std::system_error(LastError(), "write file");
        if (written == 0 || static_cast<size_t>(written) > chunk.size())
          throw std::system_error(EIO, std::generic_category(), "file write made no valid progress");
        result.bytes += static_cast<size_t>(written);
        chunk.remove_prefix(static_cast<size_t>(written));
      }
    });
  } catch (const std::system_error& error) {
    result.error = error.code();
    return finish();
  }
  auto sync = [&](int fd) {
    int code;
    do { code = operations.Sync(fd); } while (code != 0 && errno == EINTR);
    return code;
  };
  result.stage = "sync file";
  if (sync(temporary.file) != 0) { result.error = LastError(); return finish(); }
  result.stage = "close file";
  const int closing = std::exchange(temporary.file, -1);
  if (operations.Close(closing) != 0) { result.error = LastError(); return finish(); }
  result.stage = "publish";
  if (operations.Publish(directory, temporary.name, filename.c_str()) != 0) {
    result.error = LastError();
    return finish();
  }
  temporary.owned = false;
  result.committed = true;
  result.stage = "sync directory";
  if (sync(directory) != 0) { result.error = LastError(); return finish(); }
  result.stage = "complete";
  return finish();
}
} // namespace atomic_file_detail
} // namespace frame_sync
#endif
