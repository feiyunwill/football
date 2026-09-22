// 2026-09-14: bounded complete-state transfer, independent of transport queues.
// A complete SHA-256 of the serialized bytes is separate from GameEnv's
// deterministic state hash. Transport authentication remains a separate layer.
#pragma once
#include "native_recovery_wire.hpp"
// 2026-09-14: OpenSSL stays inside the transport library implementation.
// #include <openssl/evp.h>
#include <bitset>
#include <vector>
namespace frame_sync {
// 2026-09-14: export the digest boundary without exposing crypto headers to AI/engine consumers.
// inline std::optional<NativeRecoveryDigest> recovery_snapshot_digest(
//     std::span<const uint8_t> bytes) {
//   if (bytes.empty() || bytes.size() > kNativeRecoverySnapshotBytes) return std::nullopt;
//   std::array<unsigned char, EVP_MAX_MD_SIZE> output{};
//   size_t length = 0;
//   if (EVP_Q_digest(nullptr, "SHA256", nullptr, bytes.data(), bytes.size(),
//                    output.data(), &length) != 1 || length != 32) return std::nullopt;
//   NativeRecoveryDigest result{};
//   std::copy_n(output.begin(), result.size(), result.begin());
//   return result;
// }
std::optional<NativeRecoveryDigest> recovery_snapshot_digest(std::span<const uint8_t> bytes);
enum class NativeRecoveryReceive {
  Accepted, Duplicate, Complete, Stale, Invalid, Expired
};
class NativeRecoveryAssembler {
 public:
  using Time = std::chrono::steady_clock::time_point;
  NativeRecoveryAssembler() = delete;
  explicit NativeRecoveryAssembler(uint64_t generation,
      size_t limit = kNativeRecoverySnapshotBytes,
      std::chrono::milliseconds timeout = std::chrono::seconds(30))
      : generation_(generation), limit_(limit), timeout_(timeout) {
    if (!generation || !limit || limit > kNativeRecoverySnapshotBytes ||
        timeout.count() < 1 || timeout > std::chrono::minutes(5))
      throw std::invalid_argument("Invalid recovery receiver limits");
  }
  ~NativeRecoveryAssembler() = default;
  NativeRecoveryAssembler(const NativeRecoveryAssembler&) = delete;
  NativeRecoveryAssembler& operator=(const NativeRecoveryAssembler&) = delete;
  NativeRecoveryAssembler(NativeRecoveryAssembler&&) = delete;
  NativeRecoveryAssembler& operator=(NativeRecoveryAssembler&&) = delete;

  NativeRecoveryReceive begin(const NativeRecoverySnapshot& metadata, Time now) {
    if (!advance(now)) return NativeRecoveryReceive::Invalid;
    if (expired_) return NativeRecoveryReceive::Expired;
    if (metadata.generation != generation_) return NativeRecoveryReceive::Stale;
    if (!valid_recovery_snapshot(metadata) || metadata.size > limit_)
      return NativeRecoveryReceive::Invalid;
    if (phase_ == Phase::Receiving || phase_ == Phase::Complete) {
      if (metadata == metadata_) return NativeRecoveryReceive::Duplicate;
      fail();
      return NativeRecoveryReceive::Invalid;
    }
    if (phase_ != Phase::Empty || Time::max() - now < timeout_)
      return NativeRecoveryReceive::Invalid;
    std::vector<uint8_t> incoming(metadata.size);
    if (incoming.capacity() > limit_) return NativeRecoveryReceive::Invalid;
    data_.swap(incoming);
    metadata_ = metadata;
    deadline_ = now + timeout_;
    phase_ = Phase::Receiving;
    return NativeRecoveryReceive::Accepted;
  }
  NativeRecoveryReceive push(const NativeRecoveryChunk& chunk, Time now) {
    if (!advance(now)) return NativeRecoveryReceive::Invalid;
    if (expired_) return NativeRecoveryReceive::Expired;
    if (chunk.generation != generation_) return NativeRecoveryReceive::Stale;
    if (phase_ != Phase::Receiving && phase_ != Phase::Complete)
      return NativeRecoveryReceive::Invalid;
    if (chunk.offset >= metadata_.size ||
        chunk.offset % kNativeRecoveryChunkBytes ||
        chunk.data.size() != std::min(size_t(metadata_.size - chunk.offset),
                                      kNativeRecoveryChunkBytes)) {
      fail();
      return NativeRecoveryReceive::Invalid;
    }
    const size_t index = chunk.offset / kNativeRecoveryChunkBytes;
    if (index >= received_.size()) {
      fail();
      return NativeRecoveryReceive::Invalid;
    }
    if (received_[index]) {
      if (std::equal(chunk.data.begin(), chunk.data.end(), data_.begin() + chunk.offset))
        return NativeRecoveryReceive::Duplicate;
      fail();
      return NativeRecoveryReceive::Invalid;
    }
    std::copy(chunk.data.begin(), chunk.data.end(), data_.begin() + chunk.offset);
    received_.set(index);
    ++chunks_;
    if (chunks_ == (metadata_.size + kNativeRecoveryChunkBytes - 1) /
                       kNativeRecoveryChunkBytes) {
      const auto digest = recovery_snapshot_digest(data_);
      if (!digest || !native_secret_equal(*digest, metadata_.digest)) {
        fail();
        return NativeRecoveryReceive::Invalid;
      }
      phase_ = Phase::Complete;
      return NativeRecoveryReceive::Complete;
    }
    return NativeRecoveryReceive::Accepted;
  }
  std::optional<std::vector<uint8_t>> take(Time now) {
    if (!advance(now) || phase_ != Phase::Complete) return std::nullopt;
    std::vector<uint8_t> result;
    result.swap(data_);
    phase_ = Phase::Taken;
    return result;
  }
  bool expired(Time now) { return advance(now) && expired_; }
  bool complete() const { return phase_ == Phase::Complete; }
  size_t retained_payload() const { return data_.capacity(); }
  const NativeRecoverySnapshot& metadata() const { return metadata_; }

 private:
  enum class Phase { Empty, Receiving, Complete, Taken, Failed };
  bool advance(Time now) {
    if (now < Time{} || now < last_time_) return false;
    last_time_ = now;
    if ((phase_ == Phase::Receiving || phase_ == Phase::Complete) && now >= deadline_) {
      fail();
      expired_ = true;
    }
    return true;
  }
  void fail() {
    std::vector<uint8_t>().swap(data_);
    received_.reset();
    chunks_ = 0;
    phase_ = Phase::Failed;
  }
  const uint64_t generation_;
  const size_t limit_;
  const std::chrono::milliseconds timeout_;
  NativeRecoverySnapshot metadata_;
  std::vector<uint8_t> data_;
  std::bitset<kNativeRecoverySnapshotBytes / kNativeRecoveryChunkBytes> received_;
  size_t chunks_ = 0;
  Time last_time_{}, deadline_{};
  Phase phase_ = Phase::Empty;
  bool expired_ = false;
};
class NativeRecoverySender {
 public:
  NativeRecoverySender() = delete;
  NativeRecoverySender(uint64_t generation, uint32_t next_frame,
                       uint64_t state_hash, std::vector<uint8_t> state)
      : data_(std::move(state)) {
    if (!generation || next_frame == UINT32_MAX || data_.empty() ||
        data_.size() > kNativeRecoverySnapshotBytes ||
        data_.capacity() > kNativeRecoverySnapshotBytes)
      throw std::invalid_argument("Invalid recovery sender snapshot");
    const auto digest = recovery_snapshot_digest(data_);
    if (!digest) throw std::runtime_error("Recovery snapshot digest failed");
    metadata_.generation = generation;
    metadata_.next_frame = next_frame;
    metadata_.size = data_.size();
    metadata_.digest = *digest;
    metadata_.state_hash = state_hash;
  }
  ~NativeRecoverySender() = default;
  NativeRecoverySender(const NativeRecoverySender&) = delete;
  NativeRecoverySender& operator=(const NativeRecoverySender&) = delete;
  NativeRecoverySender(NativeRecoverySender&&) = delete;
  NativeRecoverySender& operator=(NativeRecoverySender&&) = delete;
  const NativeRecoverySnapshot& metadata() const { return metadata_; }
  bool done() const { return announced_ && offset_ == metadata_.size; }
  size_t retained_payload() const { return data_.capacity(); }
  // The frame/IO owner calls this once per scheduling turn. At most four packets
  // leave a turn; a full TCP/UDP queue does not advance or discard a fragment.
  template <typename Send>
  unsigned pump(Send&& send) {
    unsigned sent = 0;
    while (sent < 4 && !done()) {
      NativeRecoveryPacket packet;
      if (!announced_) {
        packet = pack_recovery_snapshot(metadata_);
      } else {
        NativeRecoveryChunk chunk;
        chunk.generation = metadata_.generation;
        chunk.offset = offset_;
        chunk.data = std::span<const uint8_t>(data_).subspan(offset_,
            std::min(kNativeRecoveryChunkBytes, size_t(metadata_.size - offset_)));
        packet = pack_recovery_chunk(chunk);
      }
      if (!send(packet.view())) break;
      ++sent;
      if (!announced_) announced_ = true;
      else {
        offset_ += std::min(kNativeRecoveryChunkBytes, size_t(metadata_.size - offset_));
        if (done()) std::vector<uint8_t>().swap(data_);
      }
    }
    return sent;
  }

 private:
  NativeRecoverySnapshot metadata_;
  std::vector<uint8_t> data_;
  uint32_t offset_ = 0;
  bool announced_ = false;
};
}  // namespace frame_sync
