// Copyright 2026 Google LLC & Contributors
// Validate a bounded RLtools TAR before its loader can abort on bad metadata.
#ifndef FOOTBALL_TRAINING_CHECKPOINT_ARCHIVE_HPP
#define FOOTBALL_TRAINING_CHECKPOINT_ARCHIVE_HPP

#include "frame_sync/state_hash.hpp"
#include <array>
#include <cstdint>
#include <cstring>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace football::training {
inline constexpr size_t kCheckpointFooterBytes = 64;

inline void Write32(std::vector<char>& bytes, size_t at, uint32_t value) {
  for (size_t i = 0; i < 4; ++i) bytes[at + i] = static_cast<char>(value >> (8 * i));
}
inline void Write64(std::vector<char>& bytes, size_t at, uint64_t value) {
  for (size_t i = 0; i < 8; ++i) bytes[at + i] = static_cast<char>(value >> (8 * i));
}
inline uint32_t Read32(std::span<const char> bytes, size_t at) {
  uint32_t value = 0;
  for (size_t i = 0; i < 4; ++i)
    value |= uint32_t(static_cast<unsigned char>(bytes[at + i])) << (8 * i);
  return value;
}
inline uint64_t Read64(std::span<const char> bytes, size_t at) {
  uint64_t value = 0;
  for (size_t i = 0; i < 8; ++i)
    value |= uint64_t(static_cast<unsigned char>(bytes[at + i])) << (8 * i);
  return value;
}
inline std::array<uint8_t, 32> Digest(std::span<const char> bytes) {
  frame_sync::SHA256 sha;
  sha.update(reinterpret_cast<const uint8_t*>(bytes.data()), bytes.size());
  std::array<uint8_t, 32> digest{};
  sha.finalize(digest.data());
  return digest;
}

// The footer follows TAR's two zero blocks. Ordinary TAR readers can still
// inspect the archive; this loader checks the footer and excludes it from the
// RLtools buffer view. Old, unchecked archives require explicit migration.
inline std::vector<char> SealArchive(std::vector<char> tar) {
  const size_t size = tar.size();
  const auto digest = Digest(tar);
  tar.resize(size + kCheckpointFooterBytes, '\0');
  std::memcpy(tar.data() + size, "FBCKPT02", 8);
  Write32(tar, size + 8, 1);
  Write64(tar, size + 16, size);
  std::memcpy(tar.data() + size + 24, digest.data(), digest.size());
  return tar;
}

inline bool TarSchemaMatches(std::span<const char> actual,
                             std::span<const char> expected,
                             std::string& error) {
  if (actual.size() != expected.size() || actual.size() < 1024 ||
      actual.size() % 512) {
    error = "archive size differs from this training configuration";
    return false;
  }
  size_t at = 0;
  while (at + 512 <= expected.size()) {
    const char* header = expected.data() + at;
    bool zero = true;
    for (size_t i = 0; i < 512; ++i) zero &= header[i] == 0;
    if (zero) {
      if (std::memcmp(actual.data() + at, expected.data() + at,
                      expected.size() - at) != 0) {
        error = "archive trailer is damaged";
        return false;
      }
      return true;
    }
    const size_t name_length = strnlen(header, 100);
    const std::string_view name(header, name_length);
    if (std::memcmp(actual.data() + at, header, 512) != 0) {
      error = "archive entry header differs: " + std::string(name);
      return false;
    }
    size_t size = 0;
    for (size_t i = 124; i < 136 && header[i] != '\0' && header[i] != ' '; ++i) {
      if (header[i] < '0' || header[i] > '7') {
        error = "invalid archive size field";
        return false;
      }
      size = size * 8 + (header[i] - '0');
      if (size > expected.size()) {
        error = "archive entry exceeds size limit";
        return false;
      }
    }
    const size_t padded = ((size + 511) / 512) * 512;
    if (at + 512 + padded > expected.size()) {
      error = "archive entry is truncated";
      return false;
    }
    if (name == "meta" || name.ends_with("/meta")) {
      if (std::memcmp(actual.data() + at + 512,
                      expected.data() + at + 512, size) != 0) {
        error = "archive tensor metadata differs: " + std::string(name);
        return false;
      }
    }
    if (std::memcmp(actual.data() + at + 512 + size,
                    expected.data() + at + 512 + size,
                    padded - size) != 0) {
      error = "archive entry padding is damaged: " + std::string(name);
      return false;
    }
    at += 512 + padded;
  }
  error = "archive end marker is missing";
  return false;
}

inline std::span<const char> OpenArchive(std::span<const char> file,
                                         std::span<const char> expected_tar,
                                         std::string& error) {
  if (file.size() < kCheckpointFooterBytes) {
    error = "checkpoint is truncated";
    return {};
  }
  const size_t at = file.size() - kCheckpointFooterBytes;
  if (std::memcmp(file.data() + at, "FBCKPT02", 8) != 0 ||
      Read32(file, at + 8) != 1 || Read32(file, at + 12) != 0 ||
      Read64(file, at + 16) != at) {
    error = "unsupported or damaged checkpoint footer";
    return {};
  }
  for (size_t i = 56; i < 64; ++i) {
    if (file[at + i] != 0) {
      error = "checkpoint footer reserved bytes are nonzero";
      return {};
    }
  }
  const auto tar = file.first(at);
  const auto digest = Digest(tar);
  if (std::memcmp(file.data() + at + 24, digest.data(), digest.size()) != 0) {
    error = "checkpoint SHA-256 mismatch";
    return {};
  }
  if (!TarSchemaMatches(tar, expected_tar, error)) return {};
  return tar;
}
}  // namespace football::training
#endif
