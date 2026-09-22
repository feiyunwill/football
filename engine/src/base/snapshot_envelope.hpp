// 2026-09-09: versioned local snapshots with bounded size and corruption checks.
#ifndef FOOTBALL_SNAPSHOT_ENVELOPE_HPP
#define FOOTBALL_SNAPSHOT_ENVELOPE_HPP

#include <array>
#include <bit>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <string_view>

namespace blunted::snapshot {
inline constexpr size_t kMaxBytes = 10000000;
inline constexpr size_t kHeaderBytes = 16;
inline constexpr uint32_t kVersion = 2;

inline uint32_t Checksum(std::string_view bytes) {
  static constexpr auto table = [] {
    std::array<uint32_t, 256> result{};
    for (uint32_t index = 0; index < result.size(); ++index) {
      uint32_t value = index;
      for (int bit = 0; bit < 8; ++bit)
        value = (value >> 1) ^ (0xedb88320u & (0u - (value & 1u)));
      result[index] = value;
    }
    return result;
  }();
  uint32_t value = 0xffffffffu;
  for (unsigned char byte : bytes) value = table[(value ^ byte) & 255] ^ (value >> 8);
  return value ^ 0xffffffffu;
}

inline void Write32(std::string& bytes, size_t position, uint32_t value) {
  for (size_t byte = 0; byte < 4; ++byte) bytes[position + byte] = static_cast<char>(value >> (8 * byte));
}
inline uint32_t Read32(std::string_view bytes, size_t position) {
  uint32_t value = 0;
  for (size_t byte = 0; byte < 4; ++byte)
    value |= uint32_t(static_cast<unsigned char>(bytes[position + byte])) << (8 * byte);
  return value;
}

inline std::string Encode(std::string_view payload) {
  static_assert(std::endian::native == std::endian::little && sizeof(float) == 4 && sizeof(int) == 4,
                "Snapshot v2 payload targets the supported little-endian Linux ABI");
  if (payload.empty() || payload.size() > kMaxBytes) throw std::invalid_argument("Invalid snapshot payload size");
  std::string result(kHeaderBytes, '\0');
  result.replace(0, 4, "FSTA");
  Write32(result, 4, kVersion);
  Write32(result, 8, payload.size());
  Write32(result, 12, Checksum(payload));
  result.append(payload);
  return result;
}

inline std::string_view Decode(std::string_view bytes) {
  if (bytes.size() < kHeaderBytes || bytes.size() > kHeaderBytes + kMaxBytes)
    throw std::invalid_argument("Invalid snapshot size");
  if (bytes.substr(0, 4) != "FSTA" || Read32(bytes, 4) != kVersion)
    throw std::invalid_argument("Unsupported snapshot format/version");
  const auto payload = bytes.substr(kHeaderBytes);
  if (payload.empty() || payload.size() != Read32(bytes, 8))
    throw std::invalid_argument("Snapshot length mismatch");
  if (Checksum(payload) != Read32(bytes, 12)) throw std::invalid_argument("Snapshot checksum mismatch");
  return payload;
}
}  // namespace blunted::snapshot
#endif
