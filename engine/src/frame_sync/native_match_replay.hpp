// 2026-09-13: native product replay envelope; legacy raw payload remains unchanged.
#pragma once
#include "frame_sync/native_match_contract.hpp"
#include "frame_sync/replay_system.hpp"
namespace frame_sync {
class NativeReplayView {
 public:
  NativeReplayView() = delete;
  NativeReplayView(const ReplayRecorder& recorder,NativeMatchContract contract)
      :recorder_(recorder),contract_(contract) {
    contract_.Validate();
    const auto& meta=recorder.GetMetadata();
    if(meta.seed!=contract.seed || meta.num_slots!=contract.left+contract.right || meta.scenario!="default_11v11")
      throw std::invalid_argument("Replay differs from native match contract");
  }
  ~NativeReplayView() = default;
  NativeReplayView(const NativeReplayView&) = default;
  NativeReplayView& operator=(const NativeReplayView&) = delete;
  NativeReplayView(NativeReplayView&&) = default;
  NativeReplayView& operator=(NativeReplayView&&) = delete;
  auto GetFrameCount() const { return recorder_.GetFrameCount(); }
  const ReplayMetadata& GetMetadata() const { return recorder_.GetMetadata(); }
  size_t GetSerializedBytes() const {
    const auto bytes=recorder_.GetSerializedBytes();
    if(bytes>std::numeric_limits<size_t>::max()-40)throw std::overflow_error("Native replay size");
    return 40+bytes;
  }
  template<class Sink> size_t SerializeTo(Sink&& sink) const {
    std::array<char,40> header{};
    std::copy_n("FNRPLY1",8,header.begin());
    const auto packet=contract_.Packet();
    std::copy(packet.begin(),packet.end(),header.begin()+8);
    sink(std::string_view(header.data(),header.size()));
    return header.size()+recorder_.SerializeTo(std::forward<Sink>(sink));
  }
 private:
  const ReplayRecorder& recorder_;
  NativeMatchContract contract_;
};
class NativeReplayPlayer {
 public:
  NativeReplayPlayer() = default;
  ~NativeReplayPlayer() = default;
  NativeReplayPlayer(const NativeReplayPlayer&) = default;
  NativeReplayPlayer& operator=(const NativeReplayPlayer&) = default;
  NativeReplayPlayer(NativeReplayPlayer&&) = default;
  NativeReplayPlayer& operator=(NativeReplayPlayer&&) = default;
  bool LoadReplay(std::string_view data) {
    if(data.size()<40 || data.size()-40>ReplayBudget{}.byte_limit ||
       data.substr(0,8)!=std::string_view("FNRPLY1",8))return false;
    NativeMatchContract contract;
    const auto* bytes=reinterpret_cast<const uint8_t*>(data.data()+8);
    if(!NativeMatchContract::Decode({bytes,32},NativeMatchContract::kSession,contract))return false;
    ReplayPlayer candidate;
    if(!candidate.LoadReplay(std::string(data.substr(40))))return false;
    const auto& meta=candidate.GetMetadata();
    if(meta.seed!=contract.seed || meta.num_slots!=contract.left+contract.right ||
       meta.scenario!="default_11v11")return false;
    for(size_t frame=0;frame<candidate.GetTotalFrames();++frame)
      if(candidate.GetFrameAt(frame)->frame_number!=frame)return false;
    player_=std::move(candidate);contract_=contract;return true;
  }
  const NativeMatchContract& contract() const { return contract_; }
  auto GetTotalFrames() const { return player_.GetTotalFrames(); }
  const ReplayMetadata& GetMetadata() const { return player_.GetMetadata(); }
  auto GetFrameAt(size_t frame) const { return player_.GetFrameAt(frame); }
 private:
  ReplayPlayer player_;
  NativeMatchContract contract_;
};
}
