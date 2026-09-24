// 2026-09-14: an explicit FNRC/1 recovery family around the unchanged
// FNAT/1 match descriptor. Messages fit inside one bounded reliable UDP payload.
#pragma once
#include "frame_sync/native_recovery_credentials.hpp"
#include "frame_sync/native_match_contract.hpp"
#include <algorithm>
#include <array>
#include <cstdint>
#include <optional>
#include <span>
#include <stdexcept>
#include <utility>
namespace original_wire {
using namespace frame_sync;
enum class NativeRecoveryKind : uint8_t {
  Hello = 80, Session = 81, Resume = 82, Snapshot = 83,
  // 2026-09-14: explicit initial-loading records keep existing values stable.
  // Chunk = 84, Ready = 85, Accepted = 86, Rejected = 87
  Chunk = 84, Ready = 85, Accepted = 86, Rejected = 87,
// 2026-09-15: explicit authenticated cancellation and receipt keep existing wire values stable.
//   LoadHello = 88, LoadComplete = 89, LoadReceipt = 90
  LoadHello = 88, LoadComplete = 89, LoadReceipt = 90,
  LoadCancel = 91, LoadCancelled = 92
};
enum class NativeRecoveryReject : uint8_t {
  Incompatible = 1, Unauthorized = 2, Busy = 3,
  SnapshotUnavailable = 4, InvalidState = 5
};
inline constexpr size_t kNativeRecoveryHeaderBytes = 10;
inline constexpr size_t kNativeRecoveryPacketBytes = 1100;
inline constexpr size_t kNativeRecoveryChunkBytes = 1024;
inline constexpr uint32_t kNativeRecoverySnapshotBytes = 1024 * 1024;
using NativeRecoveryDigest = std::array<uint8_t, 32>;
struct NativeRecoveryPacket {
  std::array<uint8_t, kNativeRecoveryPacketBytes> bytes{};
  size_t size = 0;
  NativeRecoveryPacket() = default;
  ~NativeRecoveryPacket() = default;
  NativeRecoveryPacket(const NativeRecoveryPacket&) = default;
  NativeRecoveryPacket& operator=(const NativeRecoveryPacket&) = default;
  NativeRecoveryPacket(NativeRecoveryPacket&&) = default;
  NativeRecoveryPacket& operator=(NativeRecoveryPacket&&) = default;
  // 2026-09-14: an invalid locally constructed packet must not expose an oversized span.
  // std::span<const uint8_t> view() const { return {bytes.data(), size}; }
  std::span<const uint8_t> view() const {
    if (size > bytes.size()) throw std::length_error("Recovery packet storage exceeded");
    return {bytes.data(), size};
  }
};
struct NativeRecoverySession {
  NativeMatchContract match;
  NativeRecoveryGrant grant;
  bool restoring = false;
  // 2026-09-14: an opening reservation has no simulation control.
  bool loading = false;
  NativeRecoverySession() = default;
  ~NativeRecoverySession() = default;
  NativeRecoverySession(const NativeRecoverySession&) = default;
  NativeRecoverySession& operator=(const NativeRecoverySession&) = default;
  NativeRecoverySession(NativeRecoverySession&&) = default;
  NativeRecoverySession& operator=(NativeRecoverySession&&) = default;
};
struct NativeRecoverySnapshot {
  uint64_t generation = 0;
  uint32_t next_frame = 0, size = 0;
  NativeRecoveryDigest digest{};
  uint64_t state_hash = 0;
  NativeRecoverySnapshot() = default;
  ~NativeRecoverySnapshot() = default;
  NativeRecoverySnapshot(const NativeRecoverySnapshot&) = default;
  NativeRecoverySnapshot& operator=(const NativeRecoverySnapshot&) = default;
  NativeRecoverySnapshot(NativeRecoverySnapshot&&) = default;
  NativeRecoverySnapshot& operator=(NativeRecoverySnapshot&&) = default;
  bool operator==(const NativeRecoverySnapshot&) const = default;
};
struct NativeRecoveryReady {
  NativeRecoveryGrant grant;
  uint32_t next_frame = 0;
  uint64_t state_hash = 0;
  NativeRecoveryReady() = default;
  ~NativeRecoveryReady() = default;
  NativeRecoveryReady(const NativeRecoveryReady&) = default;
  NativeRecoveryReady& operator=(const NativeRecoveryReady&) = default;
  NativeRecoveryReady(NativeRecoveryReady&&) = default;
  NativeRecoveryReady& operator=(NativeRecoveryReady&&) = default;
};
struct NativeRecoveryChunk {
  uint64_t generation = 0;
  uint32_t offset = 0;
  std::span<const uint8_t> data;
  NativeRecoveryChunk() = default;
  ~NativeRecoveryChunk() = default;
  NativeRecoveryChunk(const NativeRecoveryChunk&) = default;
  NativeRecoveryChunk& operator=(const NativeRecoveryChunk&) = default;
  NativeRecoveryChunk(NativeRecoveryChunk&&) = default;
  NativeRecoveryChunk& operator=(NativeRecoveryChunk&&) = default;
};
namespace native_recovery_wire {
inline void put(std::span<uint8_t> out, size_t at, uint64_t value, size_t bytes) {
  for (size_t n = 0; n < bytes; ++n) out[at + n] = value >> (8 * n);
}
inline uint64_t get(std::span<const uint8_t> in, size_t at, size_t bytes) {
  uint64_t value = 0;
  for (size_t n = 0; n < bytes; ++n) value |= uint64_t(in[at + n]) << (8 * n);
  return value;
}
template <size_t N>
inline bool nonzero(const std::array<uint8_t, N>& bytes) {
  unsigned value = 0;
  for (auto byte : bytes) value |= byte;
  return value != 0;
}
inline bool valid_grant(const NativeRecoveryGrant& grant, bool generation = true) {
  return grant.slot < 22 && nonzero(grant.match) && nonzero(grant.secret) &&
      (!generation || grant.generation != 0);
}
inline NativeRecoveryPacket packet(NativeRecoveryKind kind, size_t payload) {
  if (payload > kNativeRecoveryPacketBytes - kNativeRecoveryHeaderBytes)
    throw std::invalid_argument("Recovery packet exceeds transport budget");
  NativeRecoveryPacket result;
  result.size = kNativeRecoveryHeaderBytes + payload;
  const std::array<uint8_t, 8> header{
      static_cast<uint8_t>(kind), 'F', 'N', 'R', 'C', 1, 0, 0};
  std::copy(header.begin(), header.end(), result.bytes.begin());
  put(result.bytes, 8, payload, 2);
  return result;
}
// Zero means an incomplete TCP prefix, -1 is invalid, positive is one whole
// record. A coalesced following record is left for the caller's next parse.
inline int record_size(std::span<const uint8_t> bytes) {
  if (bytes.empty()) return 0;
  // 2026-09-14: retain bounded parsing of new loading records.
  // if (bytes[0] < 80 || bytes[0] > 87) return -1;
// 2026-09-15: bound the two new fixed-size loading controls.
//   if (bytes[0] < 80 || bytes[0] > 90) return -1;
  if (bytes[0] < 80 || bytes[0] > 92) return -1;
  constexpr std::array<uint8_t, 7> marker{'F','N','R','C',1,0,0};
  for (size_t n = 1; n < std::min(bytes.size(), size_t{8}); ++n)
    if (bytes[n] != marker[n - 1]) return -1;
  if (bytes.size() < kNativeRecoveryHeaderBytes) return 0;
  const size_t payload = get(bytes, 8, 2);
  const auto kind = static_cast<NativeRecoveryKind>(bytes[0]);
  const size_t fixed =
      // 2026-09-14: fixed bounds for initial-loading messages.
      // kind == NativeRecoveryKind::Hello ? 18 :
      kind == NativeRecoveryKind::Hello || kind == NativeRecoveryKind::LoadHello ? 18 :
// 2026-09-15: cancellation proofs use the same complete grant, including its generation.
//       kind == NativeRecoveryKind::LoadComplete || kind == NativeRecoveryKind::LoadReceipt ? 58 :
      kind == NativeRecoveryKind::LoadComplete || kind == NativeRecoveryKind::LoadReceipt ||
      kind == NativeRecoveryKind::LoadCancel || kind == NativeRecoveryKind::LoadCancelled ? 58 :
      kind == NativeRecoveryKind::Session ? 91 :
      kind == NativeRecoveryKind::Resume ? 50 :
      kind == NativeRecoveryKind::Snapshot ? 56 :
      kind == NativeRecoveryKind::Ready ? 70 :
      kind == NativeRecoveryKind::Accepted ? 12 :
      kind == NativeRecoveryKind::Rejected ? 1 : 0;
  if ((kind == NativeRecoveryKind::Chunk &&
       (payload < 13 || payload > 12 + kNativeRecoveryChunkBytes)) ||
      (kind != NativeRecoveryKind::Chunk && payload != fixed)) return -1;
  const size_t total = kNativeRecoveryHeaderBytes + payload;
  if (total > kNativeRecoveryPacketBytes) return -1;
  return bytes.size() < total ? 0 : static_cast<int>(total);
}
inline bool complete(std::span<const uint8_t> bytes, NativeRecoveryKind kind) {
  const int count = record_size(bytes);
  return count > 0 && static_cast<size_t>(count) == bytes.size() &&
      bytes[0] == static_cast<uint8_t>(kind);
}
inline void put_grant(std::span<uint8_t> out, size_t at,
                      const NativeRecoveryGrant& grant, bool generation) {
  std::copy(grant.match.begin(), grant.match.end(), out.begin() + at);
  put(out, at + 16, grant.slot, 2);
  std::copy(grant.secret.begin(), grant.secret.end(), out.begin() + at + 18);
  if (generation) put(out, at + 50, grant.generation, 8);
}
inline NativeRecoveryGrant get_grant(std::span<const uint8_t> in, size_t at,
                                     bool generation) {
  NativeRecoveryGrant result;
  std::copy_n(in.begin() + at, 16, result.match.begin());
  result.slot = get(in, at + 16, 2);
  std::copy_n(in.begin() + at + 18, 32, result.secret.begin());
  if (generation) result.generation = get(in, at + 50, 8);
  return result;
}
}  // namespace native_recovery_wire

inline NativeRecoveryPacket pack_recovery_hello() {
  auto result = native_recovery_wire::packet(NativeRecoveryKind::Hello, 18);
  const auto inner = NativeMatchContract::Header();
  std::copy(inner.begin(), inner.end(), result.bytes.begin() + 10);
  return result;
}
inline bool is_recovery_hello(std::span<const uint8_t> bytes) {
  return native_recovery_wire::complete(bytes, NativeRecoveryKind::Hello) &&
      NativeMatchContract::IsHello(bytes.subspan(10));
}
// 2026-09-14: initial resources have one absolute, nonrenewable budget.
inline constexpr auto kNativeInitialLoadingTimeout = std::chrono::seconds(120);
inline NativeRecoveryPacket pack_recovery_load_hello() {
  auto result = native_recovery_wire::packet(NativeRecoveryKind::LoadHello,18);
  const auto inner = NativeMatchContract::Header();
  std::copy(inner.begin(),inner.end(),result.bytes.begin()+10);
  return result;
}
inline bool is_recovery_load_hello(std::span<const uint8_t> bytes) {
  return native_recovery_wire::complete(bytes,NativeRecoveryKind::LoadHello) &&
         NativeMatchContract::IsHello(bytes.subspan(10));
}
// 2026-09-15: cancellation and its receipt share the existing fixed grant codec.
inline NativeRecoveryPacket pack_recovery_load_control(
    NativeRecoveryKind kind,const NativeRecoveryGrant& grant) {
  // 2026-09-15: include explicit cancellation request/receipt kinds.
  // if ((kind != NativeRecoveryKind::LoadComplete && kind != NativeRecoveryKind::LoadReceipt) ||
  if ((kind != NativeRecoveryKind::LoadComplete && kind != NativeRecoveryKind::LoadReceipt &&
       kind != NativeRecoveryKind::LoadCancel && kind != NativeRecoveryKind::LoadCancelled) ||
      !native_recovery_wire::valid_grant(grant))
    throw std::invalid_argument("Invalid loading control");
  auto result = native_recovery_wire::packet(kind,58);
  native_recovery_wire::put_grant(result.bytes,10,grant,true);
  return result;
}
inline std::optional<NativeRecoveryGrant> decode_recovery_load_control(
    std::span<const uint8_t> bytes, NativeRecoveryKind kind) {
  // 2026-09-15: include explicit cancellation request/receipt kinds.
  // if ((kind != NativeRecoveryKind::LoadComplete && kind != NativeRecoveryKind::LoadReceipt) ||
  if ((kind != NativeRecoveryKind::LoadComplete && kind != NativeRecoveryKind::LoadReceipt &&
       kind != NativeRecoveryKind::LoadCancel && kind != NativeRecoveryKind::LoadCancelled) ||
      !native_recovery_wire::complete(bytes,kind)) return std::nullopt;
  const auto grant=native_recovery_wire::get_grant(bytes,10,true);
  return native_recovery_wire::valid_grant(grant) ? std::optional(grant) : std::nullopt;
}

inline NativeRecoveryPacket pack_recovery_session(const NativeRecoverySession& session) {
  session.match.Validate();
  if (session.loading && session.restoring) throw std::invalid_argument("Loading cannot restore a live match");
  if (!native_recovery_wire::valid_grant(session.grant) ||
      session.grant.slot >= session.match.left + session.match.right)
    throw std::invalid_argument("Recovery session ownership is invalid");
  auto result = native_recovery_wire::packet(NativeRecoveryKind::Session, 91);
  const auto inner = session.match.Packet();
  std::copy(inner.begin(), inner.end(), result.bytes.begin() + 10);
  native_recovery_wire::put_grant(result.bytes, 42, session.grant, true);
  // 2026-09-14: flag 2 is only sent after the explicit loading hello.
  // result.bytes[100] = session.restoring ? 1 : 0;
  result.bytes[100] = session.loading ? 2 : session.restoring ? 1 : 0;
  return result;
}
inline std::optional<NativeRecoverySession> decode_recovery_session(
    std::span<const uint8_t> bytes) {
  if (!native_recovery_wire::complete(bytes, NativeRecoveryKind::Session))
    return std::nullopt;
  NativeRecoverySession result;
  if (!NativeMatchContract::Decode(bytes.subspan(10, 32),
          NativeMatchContract::kSession, result.match) || bytes[100] > 2)
    return std::nullopt;
  result.grant = native_recovery_wire::get_grant(bytes, 42, true);
  if (!native_recovery_wire::valid_grant(result.grant) ||
      result.grant.slot >= result.match.left + result.match.right) return std::nullopt;
  // 2026-09-14: loading carries no authoritative snapshot.
  // result.restoring = bytes[100] != 0;
  result.restoring = bytes[100] == 1;
  result.loading = bytes[100] == 2;
  return result;
}
inline NativeRecoveryPacket pack_recovery_resume(const NativeRecoveryGrant& grant) {
  if (!native_recovery_wire::valid_grant(grant, false))
    throw std::invalid_argument("Recovery request credential is invalid");
  auto result = native_recovery_wire::packet(NativeRecoveryKind::Resume, 50);
  native_recovery_wire::put_grant(result.bytes, 10, grant, false);
  return result;
}
inline std::optional<NativeRecoveryGrant> decode_recovery_resume(
    std::span<const uint8_t> bytes) {
  if (!native_recovery_wire::complete(bytes, NativeRecoveryKind::Resume))
    return std::nullopt;
  auto result = native_recovery_wire::get_grant(bytes, 10, false);
  if (!native_recovery_wire::valid_grant(result, false)) return std::nullopt;
  return result;
}
inline bool valid_recovery_snapshot(const NativeRecoverySnapshot& snapshot) {
  return snapshot.generation && snapshot.next_frame != UINT32_MAX &&
      snapshot.size && snapshot.size <= kNativeRecoverySnapshotBytes;
}
inline NativeRecoveryPacket pack_recovery_snapshot(const NativeRecoverySnapshot& snapshot) {
  if (!valid_recovery_snapshot(snapshot))
    throw std::invalid_argument("Recovery snapshot metadata is invalid");
  auto result = native_recovery_wire::packet(NativeRecoveryKind::Snapshot, 56);
  native_recovery_wire::put(result.bytes, 10, snapshot.generation, 8);
  native_recovery_wire::put(result.bytes, 18, snapshot.next_frame, 4);
  native_recovery_wire::put(result.bytes, 22, snapshot.size, 4);
  std::copy(snapshot.digest.begin(), snapshot.digest.end(), result.bytes.begin() + 26);
  native_recovery_wire::put(result.bytes, 58, snapshot.state_hash, 8);
  return result;
}
inline std::optional<NativeRecoverySnapshot> decode_recovery_snapshot(
    std::span<const uint8_t> bytes) {
  if (!native_recovery_wire::complete(bytes, NativeRecoveryKind::Snapshot))
    return std::nullopt;
  NativeRecoverySnapshot result;
  result.generation = native_recovery_wire::get(bytes, 10, 8);
  result.next_frame = native_recovery_wire::get(bytes, 18, 4);
  result.size = native_recovery_wire::get(bytes, 22, 4);
  std::copy_n(bytes.begin() + 26, 32, result.digest.begin());
  result.state_hash = native_recovery_wire::get(bytes, 58, 8);
  if (!valid_recovery_snapshot(result)) return std::nullopt;
  return result;
}
inline NativeRecoveryPacket pack_recovery_chunk(const NativeRecoveryChunk& chunk) {
  if (!chunk.generation || chunk.offset % kNativeRecoveryChunkBytes ||
      chunk.offset >= kNativeRecoverySnapshotBytes || chunk.data.empty() ||
      chunk.data.size() > kNativeRecoveryChunkBytes ||
      chunk.data.size() > kNativeRecoverySnapshotBytes - chunk.offset)
    throw std::invalid_argument("Recovery chunk is invalid");
  auto result = native_recovery_wire::packet(NativeRecoveryKind::Chunk, 12 + chunk.data.size());
  native_recovery_wire::put(result.bytes, 10, chunk.generation, 8);
  native_recovery_wire::put(result.bytes, 18, chunk.offset, 4);
  std::copy(chunk.data.begin(), chunk.data.end(), result.bytes.begin() + 22);
  return result;
}
// The chunk view borrows the packet bytes; consume it before erasing TCP input.
inline std::optional<NativeRecoveryChunk> decode_recovery_chunk(
    std::span<const uint8_t> bytes) {
  if (!native_recovery_wire::complete(bytes, NativeRecoveryKind::Chunk))
    return std::nullopt;
  NativeRecoveryChunk result;
  result.generation = native_recovery_wire::get(bytes, 10, 8);
  result.offset = native_recovery_wire::get(bytes, 18, 4);
  result.data = bytes.subspan(22);
  if (!result.generation || result.offset % kNativeRecoveryChunkBytes ||
      result.offset >= kNativeRecoverySnapshotBytes ||
      result.data.size() > kNativeRecoverySnapshotBytes - result.offset)
    return std::nullopt;
  return result;
}
inline NativeRecoveryPacket pack_recovery_ready(const NativeRecoveryReady& ready) {
  if (!native_recovery_wire::valid_grant(ready.grant) || ready.next_frame == UINT32_MAX)
    throw std::invalid_argument("Recovery Ready is invalid");
  auto result = native_recovery_wire::packet(NativeRecoveryKind::Ready, 70);
  native_recovery_wire::put_grant(result.bytes, 10, ready.grant, true);
  native_recovery_wire::put(result.bytes, 68, ready.next_frame, 4);
  native_recovery_wire::put(result.bytes, 72, ready.state_hash, 8);
  return result;
}
inline std::optional<NativeRecoveryReady> decode_recovery_ready(
    std::span<const uint8_t> bytes) {
  if (!native_recovery_wire::complete(bytes, NativeRecoveryKind::Ready))
    return std::nullopt;
  NativeRecoveryReady result;
  result.grant = native_recovery_wire::get_grant(bytes, 10, true);
  result.next_frame = native_recovery_wire::get(bytes, 68, 4);
  result.state_hash = native_recovery_wire::get(bytes, 72, 8);
  if (!native_recovery_wire::valid_grant(result.grant) || result.next_frame == UINT32_MAX)
    return std::nullopt;
  return result;
}
inline NativeRecoveryPacket pack_recovery_accepted(uint64_t generation, uint32_t frame) {
  if (!generation || frame == UINT32_MAX)
    throw std::invalid_argument("Recovery acceptance boundary is invalid");
  auto result = native_recovery_wire::packet(NativeRecoveryKind::Accepted, 12);
  native_recovery_wire::put(result.bytes, 10, generation, 8);
  native_recovery_wire::put(result.bytes, 18, frame, 4);
  return result;
}
inline std::optional<std::pair<uint64_t, uint32_t>> decode_recovery_accepted(
    std::span<const uint8_t> bytes) {
  if (!native_recovery_wire::complete(bytes, NativeRecoveryKind::Accepted))
    return std::nullopt;
  const auto generation = native_recovery_wire::get(bytes, 10, 8);
  const uint32_t frame = native_recovery_wire::get(bytes, 18, 4);
  if (!generation || frame == UINT32_MAX) return std::nullopt;
  return std::pair(generation, frame);
}
inline NativeRecoveryPacket pack_recovery_rejected(NativeRecoveryReject reason) {
  const auto value = static_cast<uint8_t>(reason);
  if (value < 1 || value > 5) throw std::invalid_argument("Invalid recovery rejection");
  auto result = native_recovery_wire::packet(NativeRecoveryKind::Rejected, 1);
  result.bytes[10] = value;
  return result;
}
inline std::optional<NativeRecoveryReject> decode_recovery_rejected(
    std::span<const uint8_t> bytes) {
  if (!native_recovery_wire::complete(bytes, NativeRecoveryKind::Rejected) ||
      bytes[10] < 1 || bytes[10] > 5) return std::nullopt;
  return static_cast<NativeRecoveryReject>(bytes[10]);
}
}  // namespace frame_sync
