// 2026-09-14: transport-local SHA-256 implementation; no engine or global crypto header dependency.
#include "frame_sync/native_recovery_transfer.hpp"
#include <openssl/evp.h>
namespace frame_sync {
std::optional<NativeRecoveryDigest> recovery_snapshot_digest(
    std::span<const uint8_t> bytes) {
  if (bytes.empty() || bytes.size() > kNativeRecoverySnapshotBytes) return std::nullopt;
  std::array<unsigned char, EVP_MAX_MD_SIZE> output{};
  size_t length = 0;
  if (EVP_Q_digest(nullptr, "SHA256", nullptr, bytes.data(), bytes.size(),
                   output.data(), &length) != 1 || length != 32) return std::nullopt;
  NativeRecoveryDigest result{};
  std::copy_n(output.begin(), result.size(), result.begin());
  return result;
}
}  // namespace frame_sync
