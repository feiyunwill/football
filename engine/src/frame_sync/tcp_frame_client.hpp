// Copyright 2026 Google LLC & Contributors
// 2026-09-09: production whole-frame prediction over bounded TCP transport.
#ifndef GFOOTBALL_FRAME_SYNC_TCP_FRAME_CLIENT_HPP
#define GFOOTBALL_FRAME_SYNC_TCP_FRAME_CLIENT_HPP
#include "frame_sync/tcp_client_transport.hpp"
#include "frame_sync/frame_simulation.hpp"
namespace frame_sync {
class TCPFrameClient {
 public:
  using PrepareEngine = std::function<EngineCallbacks(const TCPSessionInfo&)>;
  TCPFrameClient(std::string host, unsigned short port, PrepareEngine prepare,
                 TCPClientLimits limits = TCPClientLimits{}, SnapshotBudget snapshots = SnapshotBudget{})
      : transport_(std::move(host), port, limits), prepare_(std::move(prepare)),
        snapshots_(snapshots.snapshot_bytes, snapshots.history_bytes) {
    if (!prepare_) throw std::invalid_argument("TCPFrameClient needs an actual engine factory");
  }
  bool Connect() {
    simulation_.reset(); engine_ = {}; timing_.clear();
    if (!transport_.Connect()) return false;
    try {
      engine_ = prepare_(transport_.session());
      if (!engine_.compute_hash) throw std::invalid_argument("TCPFrameClient requires state hashes");
      simulation_ = std::make_unique<FrameSimulation>(engine_, slots(), snapshots_);
    } catch (...) { return transport_.Fail(TCPClientStatus::EngineFailure); }
    return transport_.Ready();  // host preparation completes before Ready
  }
  bool Resume(session_token_t token) {
    if (!simulation_ || !token) return transport_.Fail(TCPClientStatus::InvalidState);
    if (!transport_.Connect(token)) return false;
    auto snapshot = transport_.TakeBootstrap();
    if (!snapshot || RetainedBytes(snapshot->state) > snapshots_.snapshot_bytes)
      return transport_.Fail(TCPClientStatus::InvalidMessage);
    try {
      auto resumed = std::make_unique<FrameSimulation>(engine_, slots(), snapshots_, snapshot->next_frame);
      engine_.restore_state(snapshot->state);
      simulation_.swap(resumed); timing_.clear();
    } catch (...) { return transport_.Fail(TCPClientStatus::EngineFailure); }
    return transport_.Ready();
  }
  void Poll() { transport_.Poll(); }
  void Close() { transport_.Close(); }
  bool SendInput(const SlotInput& input) {
    if (!connected() || !simulation_) return false;
    std::array<SlotInput, 22> inputs; inputs.fill(input);
    const auto& local = transport_.session().slots;
    return transport_.SendInput(simulation_->next_frame(), local.data(), inputs.data(), static_cast<uint16_t>(local.size()));
  }
  FrameSimulation::TickResult Tick(const SlotInput& input, int max_predict = MAX_PREDICT_AHEAD_FRAMES) {
    Poll();
    if (!connected() || !simulation_) return {};
    TCPAuthority authority;
    while (transport_.PopAuthority(authority)) {
      timing_.record_frame_arrival(authority.arrival_ms);
      if (!simulation_->QueueAuthority(authority.frame, authority.inputs)) {
        transport_.Fail(TCPClientStatus::InvalidMessage); return {};
      }
    }
    try {
      auto result = simulation_->Tick(input, transport_.session().slots, max_predict);
      if (!transport_.VerifyHashes([this](frame_id_t frame, uint64_t hash) -> std::optional<bool> {
            auto verified = simulation_->VerifyHash(frame, hash);
            // A hash older than the retained confirmed window can no longer be
            // verified. It must not be silently treated as a successful check.
            if (!verified && frame < simulation_->confirmed_count()) return false;
            return verified;
          })) return {};
      return result;
    } catch (...) { transport_.Fail(TCPClientStatus::EngineFailure); return {}; }
  }
  bool connected() const { return transport_.connected(); }
  TCPClientStatus status() const { return transport_.status(); }
  frame_id_t next_frame() const { return simulation_ ? simulation_->next_frame() : 0; }
  frame_id_t confirmed_count() const { return simulation_ ? simulation_->confirmed_count() : 0; }
  int rollback_count() const { return simulation_ ? simulation_->rollback_count() : 0; }
  double jitter_ms() const { return timing_.jitter_ms(); }
  const TCPSessionInfo& session() const { return transport_.session(); }
  TCPClientStats stats() const { return transport_.stats(); }
  const FrameSimulation* simulation() const { return simulation_.get(); }
 private:
  size_t slots() const { return size_t(transport_.session().left) + transport_.session().right; }
  TCPClientTransport transport_;
  PrepareEngine prepare_;
  SnapshotBudget snapshots_;
  EngineCallbacks engine_;
  std::unique_ptr<FrameSimulation> simulation_;
  ClientState timing_;
};
}  // namespace frame_sync
#endif
