#include "game_load.hpp"
#include "game_env.hpp"
#include "frame_sync/native_recovery_replay.hpp"
#include "frame_sync/native_presentation.hpp"
#include "frame_sync/native_client_loop.hpp"
#include "frame_sync/native_replay.hpp"
// 2026-09-13: common product scenario construction.
// #include "frame_sync/default_scenario.hpp"  // 2026-09-09: common deterministic initial state.
#include "frame_sync/default_scenario.hpp"  // 2026-09-09: common deterministic initial state.
#include "frame_sync/native_match_scenario.hpp"
// Copyright 2019 Google LLC & Contributors
// Integrated frame sync client with rendering: connects to server, runs GameEnv
// with SDL2/OpenGL rendering, forwards keyboard input, implements prediction & rollback.

#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"
#include "frame_sync/client_state.hpp"
#include "frame_sync/engine_integration.hpp"
#include "frame_sync/engine_bridge.hpp"
#include "frame_sync/frame_simulation.hpp"
// 2026-09-13: staged shared input admission; see isolated validation status.
#include "frame_sync/native_input_buffer.hpp"
// 2026-09-13: share product input publication independently of expensive reconciliation.
// #include "frame_sync/local_input_history.hpp"
#include "frame_sync/local_input_history.hpp"
// 2026-09-13: cross-thread stop and failure indicators have atomic visibility.
// #include "frame_sync/native_input_publication.hpp"
#include "frame_sync/native_input_publication.hpp"
#include <atomic>
#include "frame_sync/bounded_tcp_writer.hpp"
#include "frame_sync/native_udp_dialer.hpp"
#include <type_traits>
#include <array>
#include <stdexcept>
#include <algorithm>
#include "frame_sync/interpolator.hpp"
#include "frame_sync/prediction_accuracy_tracker.hpp"
#include "frame_sync/adaptive_prediction_cap.hpp"
#include "frame_sync/adaptive_jitter_buffer.hpp"
#include "frame_sync/latency_compensator.hpp"
#include "frame_sync/replay_system.hpp"
#include "frame_sync/replay_file.hpp"  // 2026-09-10: checked atomic replay persistence.
// 2026-09-13: cross-process storage admission and interrupted-write recovery.
#include "frame_sync/replay_directory.hpp"
#include "frame_sync/network_diagnostics.hpp"
#include "game_env.hpp"
#include "main.hpp"
#include "gfootball_actions.h"

// 2026-08-26 GCC 15 compat: <utility> before Boost.Asio
#include <utility>
#include <boost/asio.hpp>
#include <SDL.h>
#include <chrono>
#include <cstring>
#include <deque>
#include <iostream>
#include <memory>
#include <mutex>
#include <queue>
#include <string>
#include <thread>
#include <vector>
#include <cstdio>

namespace asio = boost::asio;
using tcp = asio::ip::tcp;

// ===== Keyboard → SlotInput mapping =====
// WASD/Arrow keys for direction, Z/X/C/V/B/N for actions.
struct KeyboardState {
  float dir_x = 0.f;
  float dir_y = 0.f;
  // Button bitmask (e_ButtonFunction)
  uint16_t buttons = 0;

  void update(const Uint8* keys) {
    // Direction from arrow keys and WASD
    dir_x = 0.f;
    dir_y = 0.f;
    if (keys[SDL_SCANCODE_LEFT] || keys[SDL_SCANCODE_A]) dir_x -= 1.f;
    if (keys[SDL_SCANCODE_RIGHT] || keys[SDL_SCANCODE_D]) dir_x += 1.f;
    if (keys[SDL_SCANCODE_UP] || keys[SDL_SCANCODE_W]) dir_y += 1.f;
    if (keys[SDL_SCANCODE_DOWN] || keys[SDL_SCANCODE_S]) dir_y -= 1.f;

    // Normalize diagonal
    float len = std::sqrt(dir_x * dir_x + dir_y * dir_y);
    if (len > 1.f) {
      dir_x /= len;
      dir_y /= len;
    }

    // Buttons
    buttons = 0;
    if (keys[SDL_SCANCODE_Z]) buttons |= (1 << e_ButtonFunction_ShortPass);
    if (keys[SDL_SCANCODE_X]) buttons |= (1 << e_ButtonFunction_HighPass);
    if (keys[SDL_SCANCODE_C]) buttons |= (1 << e_ButtonFunction_LongPass);
    if (keys[SDL_SCANCODE_V]) buttons |= (1 << e_ButtonFunction_Shot);
    if (keys[SDL_SCANCODE_B]) buttons |= (1 << e_ButtonFunction_Sliding);
    if (keys[SDL_SCANCODE_LSHIFT] || keys[SDL_SCANCODE_RSHIFT])
      buttons |= (1 << e_ButtonFunction_Sprint);
    if (keys[SDL_SCANCODE_SPACE])
      buttons |= (1 << e_ButtonFunction_Pressure);
    if (keys[SDL_SCANCODE_TAB])
      buttons |= (1 << e_ButtonFunction_Switch);
    if (keys[SDL_SCANCODE_N])
      buttons |= (1 << e_ButtonFunction_TeamPressure);
    if (keys[SDL_SCANCODE_M])
      buttons |= (1 << e_ButtonFunction_Dribble);
  }

  frame_sync::SlotInput to_slot_input() const {
    frame_sync::SlotInput s;
    s.dir_x = dir_x;
    s.dir_y = dir_y;
    s.buttons = buttons;
    return s;
  }
};

// ===== IntegratedFrameSyncClient =====

// 2026-09-21: share the product session state across TCP and reliable UDP.
// class IntegratedFrameSyncClient {
template<class Socket>
class BasicIntegratedFrameSyncClient {
 public:
  // 2026-09-21: diagnostics identify the selected physical transport.
  static constexpr const char* kTransportName =
      std::is_same_v<Socket,tcp::socket> ? "TCP" : "UDP";
  BasicIntegratedFrameSyncClient() = delete;
// 2026-09-21: share the product session state across TCP and reliable UDP.
//   IntegratedFrameSyncClient(asio::io_context& io, const std::string& host,
  BasicIntegratedFrameSyncClient(asio::io_context& io, const std::string& host,
                            unsigned short port, GameEnv* env,
                            const frame_sync::MultiplayerConfig& config)
// 2026-09-09: private IO is dispatched only by the owning client poll loop
//       : io_(io), socket_(io), host_(host), port_(port),
// 2026-09-21: share the product session state across TCP and reliable UDP.
//       : socket_(std::make_shared<tcp::socket>(io_)), host_(host), port_(port),
      : host_(host), port_(port),
        env_(env), config_(config),
        client_state_(frame_sync::MAX_PREDICT_AHEAD_FRAMES + 4) {
    // 2026-09-13: the client owns presentation longer than its wrapped engine callbacks.
    // engine_ = frame_sync::MakeGameEnvCallbacks(env);
    if (!env_) throw std::invalid_argument("Client requires an environment");
    if constexpr (std::is_same_v<Socket,tcp::socket>) {
      socket_ = std::make_shared<Socket>(io_);
    } else {
      static_assert(std::is_same_v<Socket,frame_sync::NativeUDPSocket>);
      if (!config_.native_product)
        throw std::invalid_argument("Reliable UDP requires the native product contract");
      socket_ = std::make_shared<Socket>(asio::make_strand(io_));
      recovery_dialer_ = std::make_unique<frame_sync::NativeUDPDialer>(io_);
    }
    // 2026-09-13: defer presentation until the game owner first uses the initialized match.
//     presentation_ = std::make_unique<frame_sync::NativePresentation<GameEnv>>(
//         *env_, config_.render, std::chrono::nanoseconds(frame_sync::NativeLoopClock::Period(config_.frame_rate_hz)));
//     engine_ = presentation_->Wrap(frame_sync::MakeGameEnvCallbacks(env));
  }
// 2026-09-21: share the product session state across TCP and reliable UDP.
//   ~IntegratedFrameSyncClient() { stop(); }
  ~BasicIntegratedFrameSyncClient() { stop(); }
// 2026-09-21: share the product session state across TCP and reliable UDP.
//   IntegratedFrameSyncClient(const IntegratedFrameSyncClient&) = delete;
  BasicIntegratedFrameSyncClient(const BasicIntegratedFrameSyncClient&) = delete;
// 2026-09-21: share the product session state across TCP and reliable UDP.
//   IntegratedFrameSyncClient& operator=(const IntegratedFrameSyncClient&) = delete;
  BasicIntegratedFrameSyncClient& operator=(const BasicIntegratedFrameSyncClient&) = delete;
// 2026-09-21: share the product session state across TCP and reliable UDP.
//   IntegratedFrameSyncClient(IntegratedFrameSyncClient&&) = delete;
  BasicIntegratedFrameSyncClient(BasicIntegratedFrameSyncClient&&) = delete;
// 2026-09-21: share the product session state across TCP and reliable UDP.
//   IntegratedFrameSyncClient& operator=(IntegratedFrameSyncClient&&) = delete;
  BasicIntegratedFrameSyncClient& operator=(BasicIntegratedFrameSyncClient&&) = delete;
// 2026-09-13: only one owner may restart or dispatch this IO context at a time.
//   void poll() {
//     io_.restart();
  // 2026-09-14: recover native sessions while preserving the legacy path.
  //   void poll() {
  //     std::lock_guard dispatch(poll_mu_);
  //     io_.restart();
  //     for (size_t i = 0; i < 64 && io_.poll_one() != 0; ++i) {}
  //     std::lock_guard lock(mu_);
  //     if (running_ && writer_ && writer_->is_closed()) fail_locked("stream write failed or timed out");
  //   }
  void poll() {
    std::lock_guard dispatch(poll_mu_);
    io_.restart();
    const auto until = std::chrono::steady_clock::now()+std::chrono::milliseconds(2);
    for (size_t i=0;i<64 && io_.poll_one()!=0;++i)
      if (std::chrono::steady_clock::now()>=until) break;
    std::lock_guard lock(mu_);
    if (config_.native_product) maintain_recovery_locked();
    else if (running_ && writer_ && writer_->is_closed()) fail_locked("stream write failed or timed out");
  }
  bool is_running() const { return running_; }
  bool failed() const { return failed_; }
  frame_sync::frame_id_t confirmed_count() const { return simulation_ ? simulation_->confirmed_count() : 0; }
// 2026-09-13: expose received-but-unapplied authority so rendering cannot indefinitely grow reconciliation lag.
//   size_t verified_hashes() const { return verified_hashes_; }
  size_t verified_hashes() const { return verified_hashes_; }
  // Called by the simulation owner only; transport receipt is protected by mu_.
  // 2026-09-14: recover native sessions while preserving the legacy path.
  //   bool has_pending_authority() {
  //     std::lock_guard lock(mu_);
  //     return config_.native_product && received_authority_count_ > confirmed_count();
  //   }
  bool has_pending_authority() {
    std::lock_guard lock(mu_);
    return config_.native_product && recovery_can_tick_locked() &&
           received_authority_count_ > confirmed_count();
  }
  // 2026-09-13: bounded receive telemetry observes parsed packets without advancing the engine.
  std::pair<size_t, size_t> queued_authority_and_hashes() {
    std::lock_guard lock(mu_);
    return {auth_queue_.size(), pending_hashes_.size()};
  }
// 2026-09-13: serialize transport close with in-flight dispatch; the main loop joins its pump first.
//   void stop() {
//     std::lock_guard lock(mu_);
  // 2026-09-14: recover native sessions while preserving the legacy path.
  //   void stop() {
  //     std::lock_guard dispatch(poll_mu_);
  //     std::lock_guard lock(mu_);
  //     running_ = false;
  //     if (writer_) writer_->Close();
  //   }
// 2026-09-15: send a bounded, authenticated pregame release before closing the socket.
//   void stop() {
//     std::lock_guard dispatch(poll_mu_);
//     std::lock_guard lock(mu_);
//     running_ = false;
//     if (config_.native_product) {
//       close_native_attempt_locked();clear_transport_payload_locked();
//       recovery_phase_ = RecoveryPhase::Stopped;
//     } else if (writer_) writer_->Close();
//   }
  void stop() {
    std::lock_guard dispatch(poll_mu_);
    try {
      {
        std::lock_guard lock(mu_);
        request_loading_cancel_locked();
      }
      // Dispatch only transport callbacks; the pump is serialized by poll_mu_.
      // The absolute budget starts at the first request, before resource unwind.
      for (;;) {
        {
          std::lock_guard lock(mu_);
          if (!loading_cancel_sent_ || loading_cancel_acknowledged_ ||
              loading_cancel_rejected_ || !running_ || !writer_ ||
              writer_->is_closed() || RecoveryClock::now() >= loading_cancel_until_)
            break;
        }
        io_.restart();
        for (unsigned n = 0; n < 64 && io_.poll_one() != 0; ++n) {
          if (RecoveryClock::now() >= loading_cancel_until_) break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
      }
    } catch (...) {
      // stop() is also called by the destructor; always close the owned attempt.
      failed_ = true;
// 2026-09-21: retain original diagnostic format for comparison.
//       fprintf(stderr, "TCP cancellation drain failed\n");
      fprintf(stderr, "%s cancellation drain failed\n",kTransportName);
    }
    std::lock_guard lock(mu_);
    if (loading_cancel_requested_ && recovery_phase_ != RecoveryPhase::Stopped)
// 2026-09-21: retain original diagnostic format for comparison.
//       fprintf(stderr, "TCP loading cancel: sent=%d acknowledged=%d rejected=%d\n",
      fprintf(stderr, "%s loading cancel: sent=%d acknowledged=%d rejected=%d\n",kTransportName,
              loading_cancel_sent_, loading_cancel_acknowledged_, loading_cancel_rejected_);
    running_ = false;
    if (config_.native_product) {
      close_native_attempt_locked();clear_transport_payload_locked();
      recovery_phase_ = RecoveryPhase::Stopped;
    } else if (writer_) writer_->Close();
  }


// 2026-09-09: handshake is quiescent; enqueue Ready only after GameEnv initialization
//   bool connect() {
//     boost::system::error_code ec;
//     tcp::resolver resolver(io_);
//     auto endpoints = resolver.resolve(host_, std::to_string(port_), ec);
//     if (ec) {
//       fprintf(stderr, "Resolve failed: %s\n", ec.message().c_str());
//       return false;
//     }
//     asio::connect(socket_, endpoints, ec);
//     if (ec) {
//       fprintf(stderr, "Connect failed: %s\n", ec.message().c_str());
//       return false;
//     }
//     recv_buf_.clear();
//     if (!receive_session_start()) return false;
//     // 2026-09-09: the server waits for Connect before assigning a player slot.
//     const uint8_t connect_message = std::to_underlying(frame_sync::MessageType::Connect);
//     asio::write(socket_, asio::buffer(&connect_message, 1), ec);
//     if (ec) return false;
//     if (!receive_slot_assignment()) return false;
//     init_game_env();
//     send_ready();
//     do_read();
//
//     // Start recording replay (ms-17.4)
//     replay_recorder_.StartRecording(seed_, "unknown",
//                                      static_cast<uint32_t>(left_agents_) + right_agents_);
//     return true;
//   }
  bool connect() {
    // 2026-09-14: native product sessions use the explicit recoverable protocol.
    if (config_.native_product) return connect_recovery();
    if constexpr (!std::is_same_v<Socket,tcp::socket>) {
      return false;
    } else {
    boost::system::error_code ec;
    tcp::resolver resolver(io_);
    auto endpoints = resolver.resolve(host_, std::to_string(port_), ec);
    if (ec) return false;
// 2026-09-13: product input packets must not wait for small-write coalescing across 20 ms frame cutoffs.
//     asio::connect(*socket_, endpoints, ec);
//     if (ec) return false;
    asio::connect(*socket_, endpoints, ec);
    if (ec) return false;
    if (config_.native_product) {
      socket_->set_option(tcp::no_delay(true),ec);
      if (ec) return false;
    }
    recv_buf_.clear();
    // 2026-09-13: reject mismatched protocol families before engine initialization.
    // if (!receive_session_start()) return false;
    // const uint8_t connect_message = std::to_underlying(frame_sync::MessageType::Connect);
    // asio::write(*socket_, asio::buffer(&connect_message, 1), ec);
    if (config_.native_product) {
      const auto hello=frame_sync::NativeMatchContract::Header();
      asio::write(*socket_,asio::buffer(hello),ec);
      if(ec)return false;
    }
    if (!receive_session_start()) return false;
    if (!config_.native_product) {
      const uint8_t connect_message = std::to_underlying(frame_sync::MessageType::Connect);
      asio::write(*socket_, asio::buffer(&connect_message, 1), ec);
    }
    if (ec || !receive_slot_assignment()) return false;
// 2026-09-21: share the product session state across TCP and reliable UDP.
//     writer_ = std::make_unique<frame_sync::BoundedTCPWriter>(socket_);
    writer_ = std::make_unique<frame_sync::BasicBoundedStreamWriter<Socket>>(socket_);
    init_game_env();
    running_ = true;
    if (!send_ready()) return false;
    do_read();
    replay_recorder_.StartRecording(seed_, "default_11v11", static_cast<uint32_t>(left_agents_) + right_agents_);
    return true;
    }
  }

  // 2026-09-13: presentation is created on the same thread that ticks and renders.
  // void render(std::int64_t now) { presentation_->Render(now); }
  void render(std::int64_t now) { EnsurePresentation(now); presentation_->Render(now); }

  enum class StepResult {
    kNormal,
    kWaitForAuthority,
    kRollback,
    kCatchup,
  };

  // 2026-09-09: shared, full-frame reconciliation replaces divergent slot loops.
  //   StepResult tick(const frame_sync::SlotInput& my_input) {
  //     // Use adaptive prediction cap instead of fixed MAX_PREDICT_AHEAD_FRAMES
  //     int max_predict = adaptive_cap_.GetMaxPredictAhead();
  //
  //     int frames_to_process = client_state_.catchup_count(
  //         last_confirmed_frame_, current_frame_id_);
  //     if (frames_to_process < 0) {
  //       return StepResult::kWaitForAuthority;
  //     }
  //     if (frames_to_process == 0) frames_to_process = 1;
  //
  //     auto lag = current_frame_id_ - last_confirmed_frame_;
  //     if (lag >= static_cast<frame_sync::frame_id_t>(max_predict)) {
  //       return StepResult::kWaitForAuthority;
  //     }
  //     if (frames_without_packet_ >= frame_sync::MAX_FRAMES_WITHOUT_PACKET) {
  //       return StepResult::kWaitForAuthority;
  //     }
  //
  //     StepResult result = StepResult::kNormal;
  //     for (int f = 0; f < frames_to_process; ++f) {
  //       if (engine_.save_state) {
  //         client_state_.save_snapshot(current_frame_id_, my_input,
  //                                    engine_.save_state);
  //       }
  //       if (engine_.step) {
  //         engine_.step(my_input);
  //       }
  //       predicted_inputs_[current_frame_id_] = my_input;
  //       ++current_frame_id_;
  //       ++frames_without_packet_;
  //
  //       if (frames_to_process > 1) {
  //         result = StepResult::kCatchup;
  //       }
  //     }
  //
  //     frame_sync::frame_id_t auth_fid;
  //     std::vector<frame_sync::SlotInput> auth_inputs;
  //     while (pop_authoritative_frame(&auth_fid, &auth_inputs)) {
  //       if (auth_fid <= last_confirmed_frame_) continue;
  //
  //       if (auth_fid < current_frame_id_) {
  //         if (engine_.restore_state && engine_.step) {
  //           bool ok = client_state_.rollback_to(
  //               auth_fid, auth_inputs[my_slot_index_],
  //               engine_.restore_state, engine_.step);
  //           if (ok) {
  //             for (auto f = auth_fid + 1; f < current_frame_id_; ++f) {
  //               auto it = predicted_inputs_.find(f);
  //               if (it != predicted_inputs_.end() && engine_.step) {
  //                 engine_.step(it->second);
  //               }
  //             }
  //             result = StepResult::kRollback;
  //             prediction_tracker_.IncrementRollbackCount();
  //           }
  //         }
  //       } else {
  //         if (engine_.step) {
  //           for (size_t i = 0; i < auth_inputs.size(); ++i) {
  //             engine_.step(auth_inputs[i]);
  //           }
  //         }
  //         current_frame_id_ = auth_fid + 1;
  //       }
  //
  //       last_confirmed_frame_ = auth_fid;
  //       server_frame_ = auth_fid;
  //       frames_without_packet_ = 0;
  //     }
  //
  //     auto now = std::chrono::steady_clock::now();
  //     double now_ms = std::chrono::duration<double, std::milli>(
  //         now.time_since_epoch()).count();
  //     client_state_.record_frame_arrival(now_ms);
  //     client_state_.evict_old(current_frame_id_);
  //
  //     // Update adaptive modules with network conditions
  //     double rtt = client_state_.avg_frame_interval_ms() * 2.0;
  //     double jitter = client_state_.jitter_ms();
  //     adaptive_cap_.UpdateNetworkConditions(rtt, 0.0);
  //     adaptive_cap_.UpdatePredictionAccuracy(prediction_tracker_.GetRecentAccuracy());
  //     adaptive_cap_.UpdateFrameTime(16.67, jitter);
  //     jitter_buffer_.Update(jitter, rtt);
  //
  //     // Record replay frame (ms-17.4)
  //     if (replay_recorder_.IsRecording()) {
  //       std::vector<frame_sync::SlotInput> all_inputs(
  //           left_agents_ + right_agents_, frame_sync::SlotInput::Default());
  //       // Fill in our slot's input
  //       if (!my_slots_.empty() && my_slot_index_ < all_inputs.size()) {
  //         all_inputs[my_slot_index_] = my_input;
  //       }
  //       replay_recorder_.RecordFrame(current_frame_id_ - 1, 0, all_inputs);
  //     }
  //
  //     return result;
  //   }
  //
  // 2026-09-13: retain the fixed-input API through the same reconciliation body.
  StepResult tick(const frame_sync::SlotInput& my_input) {
    return tick_with_input_provider([&](frame_sync::frame_id_t) { return my_input; });
  }

  // UI owner calls this once per logic opportunity. Reliable transports own
  // retransmission; already admitted frames never consume another pending edge.
// 2026-09-13: publish from the received authority boundary before GameEnv catchup; prediction reads exact sent history.
//   StepResult tick_buffered(frame_sync::NativeInputBuffer& buffer) {
//     try {
// 2026-09-13: accept existing single-owner buffers and the synchronized window buffer.
//   StepResult tick_buffered(frame_sync::NativeInputBuffer& buffer) {
  template<class InputBuffer>
  StepResult tick_buffered(InputBuffer& buffer) {
    try {
// 2026-09-13: share publication with the worker; prediction only reads the exact sent value.
//       if (config_.native_product) {
//         poll();
//         if (!is_running() || my_slots_.empty()) return StepResult::kWaitForAuthority;
//         frame_sync::frame_id_t authority_count;
//         { std::lock_guard lock(mu_); authority_count=received_authority_count_; }
//         frame_sync::PublishNativeInput(local_input_history_,confirmed_count(),authority_count,
//             simulation_ ? simulation_->next_frame() : 0,
//             [&](frame_sync::frame_id_t) { return buffer.Take(); },
//             [&](frame_sync::frame_id_t frame,const frame_sync::SlotInput& input) {
//               std::array<frame_sync::SlotInput,frame_sync::kMaxControlledSlots> inputs;
//               std::fill_n(inputs.begin(),my_slots_.size(),input);
//               return send_frame_input(frame,my_slots_.data(),inputs.data(),static_cast<uint16_t>(my_slots_.size()));
//             });
//         poll(); // start/flush queued writes before StepWithInput, snapshots, hashes or rendering
//         return tick_with_input_provider([&](frame_sync::frame_id_t frame) {
//           local_input_history_.Confirm(simulation_->confirmed_count());
//           return local_input_history_.Find(frame).value_or(frame_sync::SlotInput::Default());
//         });
//       }
      if (config_.native_product) {
        install_recovery_on_owner([&] { (void)buffer.Take(); });
        { std::lock_guard lock(mu_);if (!running_ || !recovery_can_tick_locked()) return StepResult::kWaitForAuthority; }

        native_publication_.Advance(simulation_ ? simulation_->next_frame() : 0,confirmed_count());
        pump_input(buffer);
        if (!is_running() || my_slots_.empty()) return StepResult::kWaitForAuthority;
        return tick_with_input_provider([&](frame_sync::frame_id_t frame) {
          return native_publication_.Read(frame,simulation_->confirmed_count());
        });
      }
      return tick_with_input_provider([&](frame_sync::frame_id_t frame) {
        local_input_history_.Confirm(simulation_->confirmed_count());
        if (my_slots_.empty()) return frame_sync::SlotInput::Default();
        const auto [input, fresh] = local_input_history_.ForFrame(
            frame, [&](frame_sync::frame_id_t) { return buffer.Take(); });
        if (fresh) {
          std::array<frame_sync::SlotInput, frame_sync::kMaxControlledSlots> inputs;
          std::fill_n(inputs.begin(), my_slots_.size(), input);
          if (!send_frame_input(frame, my_slots_.data(), inputs.data(),
                                static_cast<uint16_t>(my_slots_.size())))
            throw std::runtime_error("Failed to enqueue admitted local input");
        }
        return input;
      });
    } catch (const std::exception& error) {
      std::lock_guard<std::mutex> lock(mu_);
      fail_locked(error.what());
      return StepResult::kWaitForAuthority;
    }
  }

// 2026-09-13: continue receive and one-time submission during slow draws and reconciliation.
//   template<class InputProvider>
//   StepResult tick_with_input_provider(InputProvider&& provider) {
  // Transport-only entry point: no SDL, presentation or FrameSimulation access.
  template<class InputBuffer>
  // 2026-09-14: recover native sessions while preserving the legacy path.
  //   void pump_input(InputBuffer& buffer) {
  //     poll();
  //     if (!config_.native_product || !is_running() || my_slots_.empty()) return;
  //     frame_sync::frame_id_t authority_count;
  //     { std::lock_guard lock(mu_);authority_count=received_authority_count_; }
  //     // 2026-09-13: authority receipt refines a clock; it does not clock every publication.
  // //     native_publication_.Publish(authority_count,
  //     native_publication_.PublishTimed(authority_count,
  //         [&](frame_sync::frame_id_t) { return buffer.Take(); },
  //         [&](frame_sync::frame_id_t frame,const frame_sync::SlotInput& input) {
  //           std::array<frame_sync::SlotInput,frame_sync::kMaxControlledSlots> inputs;
  //           std::fill_n(inputs.begin(),my_slots_.size(),input);
  //           return send_frame_input(frame,my_slots_.data(),inputs.data(),static_cast<uint16_t>(my_slots_.size()));
  //         });
  //     poll();
  //   }
  void pump_input(InputBuffer& buffer) {
    poll();
    if (!config_.native_product) return;
    {
      std::lock_guard input_lock(native_input_mu_);
      frame_sync::frame_id_t authority_count;uint64_t generation;
      {
        std::lock_guard lock(mu_);
        if (!running_ || recovery_phase_ != RecoveryPhase::Streaming || my_slots_.empty()) return;
        authority_count = received_authority_count_;generation = transport_generation_;
      }
      bool send_aborted = false;
      try {
        native_publication_.PublishTimed(authority_count,
          [&](frame_sync::frame_id_t) { return buffer.Take(); },
          [&](frame_sync::frame_id_t frame,const frame_sync::SlotInput& input) {
            std::array<frame_sync::SlotInput,frame_sync::kMaxControlledSlots> inputs;
            std::fill_n(inputs.begin(),my_slots_.size(),input);
            const bool sent = send_frame_input(frame,my_slots_.data(),inputs.data(),
                                               static_cast<uint16_t>(my_slots_.size()),generation);
            send_aborted = !sent;return sent;
          }, native_input_budget_ms_.load());
      } catch (...) {
        if (!send_aborted) throw;
        // A stale/transient send is cleared by owner reset before the next Accepted.
      }
    }
    poll();
  }

  template<class InputProvider>
  StepResult tick_with_input_provider(InputProvider&& provider) {
    if (!running_) return StepResult::kWaitForAuthority;
    // 2026-09-13: initialize before constructing callbacks owned by reconciliation.
    if (config_.native_product) {
      std::lock_guard lock(mu_);
      if (!recovery_can_tick_locked()) return StepResult::kWaitForAuthority;
    }

    EnsurePresentation(frame_sync::NativeNow());
    if (!simulation_) simulation_ = std::make_unique<frame_sync::FrameSimulation>(
        engine_, static_cast<size_t>(left_agents_) + right_agents_);
    frame_sync::frame_id_t fid;
    std::vector<frame_sync::SlotInput> inputs;
    while (pop_authoritative_frame(&fid, &inputs)) {
// 2026-09-09: invalid authority cannot be ignored while prediction continues
//       if (!simulation_->QueueAuthority(fid, std::move(inputs)))
//         fprintf(stderr, "Invalid authoritative frame %u\n", fid);
      if (!simulation_->QueueAuthority(fid, inputs)) {
        std::lock_guard lock(mu_);
        fail_locked("authority outside reconciliation window");
        return StepResult::kWaitForAuthority;
      }
    }
    {
      std::lock_guard<std::mutex> lock(mu_);
      for (double arrival : arrival_times_) client_state_.record_frame_arrival(arrival);
      arrival_times_.clear();
    }
    // 2026-09-13: previous Tick(my_input, ...) sampled before authority catchup.
    presentation_->BeginTick(frame_sync::NativeNow());
    auto tick = simulation_->TickWithInputProvider(provider, my_slots_, adaptive_cap_.GetMaxPredictAhead());
    presentation_->CommitTick(frame_sync::NativeNow());
// 2026-09-13: share simulation progress through the synchronized history boundary.
//     current_frame_id_ = simulation_->next_frame();
    current_frame_id_ = simulation_->next_frame();
    if (config_.native_product)
      native_publication_.Advance(simulation_->next_frame(),simulation_->confirmed_count());
    last_confirmed_frame_ = simulation_->confirmed_count() == 0 ? 0 : simulation_->confirmed_count() - 1;
    {
      std::lock_guard<std::mutex> lock(mu_);
      for (auto it = pending_hashes_.begin(); it != pending_hashes_.end();) {
        auto matches = simulation_->VerifyHash(it->first, it->second);
        if (!matches.has_value()) {
          // 2026-09-14: native recovery cannot silently discard a missing authoritative proof.
          // if (it->first < simulation_->confirmed_count()) it = pending_hashes_.erase(it);
          if (it->first < simulation_->confirmed_count()) {
            if (config_.native_product) { fail_locked("authoritative hash proof unavailable");return StepResult::kWaitForAuthority; }
            it = pending_hashes_.erase(it);
          }
          else ++it;
          continue;
        }
// 2026-09-09: stop on determinism failure instead of continuing a divergent match
//         if (!*matches) fprintf(stderr, "State hash mismatch at frame %u\n", it->first);
        if (!*matches) {
          fail_locked("state hash mismatch");
          return StepResult::kWaitForAuthority;
        }
        ++verified_hashes_;
        it = pending_hashes_.erase(it);
      }
    }
    for (const auto& confirmed : tick.confirmed) {
      if (confirmed.was_predicted) {
        prediction_tracker_.RecordOutcome(confirmed.frame, confirmed.prediction_correct);
      }
      // 2026-09-14: persist genuine recovered segments; retain legacy replay behavior.
      // if (replay_recorder_.IsRecording())
      //   replay_recorder_.RecordFrame(confirmed.frame, confirmed.hash, confirmed.inputs);
      if (config_.native_product) {
        if (recovery_journal_ && recovery_journal_->IsRecording()) {
          if (!recovery_journal_->RecordFrame(confirmed.frame,confirmed.hash,confirmed.inputs) &&
              recovery_journal_->GetStopReason() == frame_sync::ReplayStopReason::InvalidInput)
            throw std::runtime_error("Confirmed input regressed the recovery replay timeline");
          report_replay_capacity();
        }
      } else if (replay_recorder_.IsRecording())
        replay_recorder_.RecordFrame(confirmed.frame,confirmed.hash,confirmed.inputs);
    }
    adaptive_cap_.UpdatePredictionAccuracy(prediction_tracker_.GetRecentAccuracy());
    if (tick.rolled_back) return StepResult::kRollback;
    if (tick.confirmed.size() > 1) return StepResult::kCatchup;
    if (!tick.predicted && tick.confirmed.empty()) return StepResult::kWaitForAuthority;
    return StepResult::kNormal;
  }

// 2026-09-09: bound input payload and queue before dispatch; expose send failure
//   void send_frame_input(frame_sync::frame_id_t frame_id,
//                         const uint16_t* slot_indices,
//                         const frame_sync::SlotInput* inputs,
//                         uint16_t num_slots) {
//     std::vector<uint8_t> buf(256);
//     size_t n = frame_sync::PackClientFrameInput(
//         frame_id, slot_indices, inputs, num_slots, buf.data(), buf.size());
//     if (n == 0) return;
//     boost::system::error_code ec;
//     asio::write(socket_, asio::buffer(buf.data(), n), ec);
//   }
  // 2026-09-14: recover native sessions while preserving the legacy path.
  //   bool send_frame_input(frame_sync::frame_id_t frame_id,
  //                         const uint16_t* slot_indices, const frame_sync::SlotInput* inputs,
  //                         uint16_t num_slots) {
  //     std::lock_guard lock(mu_);
  //     if (!running_) return false;
  //     if (!slot_indices || !inputs || num_slots == 0 || num_slots != my_slots_.size() || num_slots > 22) {
  //       fail_locked("invalid outbound input count"); return false;
  //     }
  //     for (uint16_t i = 0; i < num_slots; ++i)
  //       if (slot_indices[i] != my_slots_[i] || !frame_sync::IsValidSlotInput(inputs[i])) {
  //         fail_locked("invalid outbound slot or input"); return false;
  //       }
  //     std::array<uint8_t, 7 + 22 * (2 + frame_sync::SLOT_INPUT_BYTES)> bytes;
  //     const auto length = frame_sync::PackClientFrameInput(frame_id, slot_indices, inputs, num_slots,
  //                                                          bytes.data(), bytes.size());
  //     if (!writer_->TrySend(bytes.data(), length)) { fail_locked("send queue capacity or transport failure"); return false; }
  //     return true;
  //   }
  bool send_frame_input(frame_sync::frame_id_t frame_id,
                        const uint16_t* slot_indices,const frame_sync::SlotInput* inputs,
                        uint16_t num_slots,uint64_t expected_generation = 0) {
    std::lock_guard lock(mu_);
    if (!running_) return false;
    if (config_.native_product && (recovery_phase_ != RecoveryPhase::Streaming ||
        (expected_generation && expected_generation != transport_generation_))) return false;
    if (!slot_indices || !inputs || num_slots == 0 || num_slots != my_slots_.size() || num_slots > 22) {
      fail_locked("invalid outbound input count");return false;
    }
    for (uint16_t i=0;i<num_slots;++i)
      if (slot_indices[i] != my_slots_[i] || !frame_sync::IsValidSlotInput(inputs[i])) {
        fail_locked("invalid outbound slot or input");return false;
      }
    std::array<uint8_t,7+22*(2+frame_sync::SLOT_INPUT_BYTES)> bytes;
    const auto length = frame_sync::PackClientFrameInput(frame_id,slot_indices,inputs,num_slots,
                                                         bytes.data(),bytes.size());
    if (!writer_->TrySend(bytes.data(),length)) {
      transport_lost_locked("send queue capacity or transport failure");return false;
    }
    return true;
  }

  bool pop_authoritative_frame(frame_sync::frame_id_t* frame_id,
                               std::vector<frame_sync::SlotInput>* inputs) {
    std::lock_guard<std::mutex> lock(mu_);
    if (auth_queue_.empty()) return false;
    *frame_id = auth_queue_.front().first;
// 2026-09-09: release queue byte accounting when ownership transfers to reconciliation
//     *inputs = auth_queue_.front().second;
//     auth_queue_.pop();
    auth_bytes_ -= frame_sync::RetainedBytes(auth_queue_.front().second);
    *inputs = std::move(auth_queue_.front().second);
    auth_queue_.pop();
    return true;
  }

  const std::vector<uint16_t>& my_slots() const { return my_slots_; }
  uint32_t seed() const { return seed_; }
  uint16_t left_agents() const { return left_agents_; }
  uint16_t right_agents() const { return right_agents_; }
  frame_sync::frame_id_t current_frame_id() const { return current_frame_id_; }
  frame_sync::frame_id_t last_confirmed_frame() const { return last_confirmed_frame_; }
  // 2026-09-09: reconciliation owns the rollback counter.
  // int rollback_count() const { return client_state_.rollback_count(); }
  int rollback_count() const { return simulation_ ? simulation_->rollback_count() : 0; }
  
  // Phase 16 stats
  double prediction_accuracy() const { return prediction_tracker_.GetRecentAccuracy(100); }
  int adaptive_max_predict() const { return adaptive_cap_.GetMaxPredictAhead(); }
  double jitter_ms() const { return client_state_.jitter_ms(); }
  // 2026-09-14: recover native sessions while preserving the legacy path.
  //   double smoothed_rtt() const { return latency_comp_.GetSmoothedRTT(); }
  double smoothed_rtt() const {
    return config_.native_product ? native_rtt_ms_.load() : latency_comp_.GetSmoothedRTT();
  }
  double latency_offset() const { return latency_comp_.GetAdjustedOffset(); }

  // 2026-09-09: replay state belongs to the client, not main().
// 2026-09-10: check every I/O stage and keep the prior replay until publication.
//   void save_replay() {
//   // Auto-save replay (ms-17.4)
//   // 2026-09-09: reaching the recording cap stops collection but the prefix must
//   // still be saved when the client exits.
//   // if (replay_recorder_.IsRecording()) {
//   if (replay_recorder_.GetFrameCount() != 0) {
//     replay_recorder_.StopRecording();
//     std::string replay_data = replay_recorder_.Serialize();
//     std::string path = "replay_" + std::to_string(seed_) + ".bin";
//     FILE* f = fopen(path.c_str(), "wb");
//     if (f) {
//       fwrite(replay_data.data(), 1, replay_data.size(), f);
//       fclose(f);
//       fprintf(stderr, "Replay saved: %s (%zu frames, %zu bytes)\n",
//               path.c_str(), replay_recorder_.GetFrameCount(), replay_data.size());
//     } else {
//       fprintf(stderr, "Failed to save replay to %s\n", path.c_str());
//     }
//   }
// 
//   }
  // 2026-09-13: retain recording when saving a prefix during a live match.
//   bool save_replay() {
//     if (replay_recorder_.GetFrameCount() == 0) return true;
//     replay_recorder_.StopRecording();
//     const std::string path = "replay_" + std::to_string(seed_) + ".bin";
//     try {
//       // 2026-09-13: retain atomic streaming with aggregate storage admission.
//       // const auto result = frame_sync::SaveReplayFile(replay_recorder_, path);
//       const auto result = frame_sync::SaveManagedReplayFile(replay_recorder_, path);
//       if (!result) {
//         fprintf(stderr, "Replay save failed: %s (stage=%s, committed=%d, error=%s, cleanup=%s)\n",
//                 path.c_str(), result.stage, result.committed ? 1 : 0,
//                 result.error.message().c_str(), result.cleanup_error.message().c_str());
//         if (result.cleanup_error)
//           fprintf(stderr, "Replay temporary cleanup requires retry: %s\n", result.temporary_path.c_str());
//         return false;
//       }
//       fprintf(stderr, "Replay saved: %s (%zu frames, %zu bytes)\n",
//               path.c_str(), replay_recorder_.GetFrameCount(), result.bytes);
//       return true;
//     } catch (const std::exception& error) {
//       fprintf(stderr, "Replay save failed: %s (%s)\n", path.c_str(), error.what());
//       return false;
//     }
//   }

  template<class Window> void initialize_on_owner(Window& window) {
    if (!config_.native_product || initial_load_finished_.load()) return;
    window.Title("Football Multiplayer | Loading match...");
    // 2026-09-14: read UI/transport cancellation only at owned resource checkpoints.
    std::string_view previous_loading_stage;
    GameLoadScope loading([&](std::string_view stage) {
      window.Poll();  // The game worker checks ownership; SDL remains on its caller.
// 2026-09-15: start cancellation before potentially expensive resource destruction.
//       if (window.buffer().quit_requested()) throw GameLoadCancelled();
      if (window.buffer().quit_requested()) {
        // The IO pump can release the seat while owned resources unwind.
        std::lock_guard lock(mu_);
        request_loading_cancel_locked();
        throw GameLoadCancelled();
      }
      {
        std::lock_guard lock(mu_);
        if (failed_ || !running_) throw std::runtime_error("Connection stopped while loading");
        if (loading_deadline_ == RecoveryClock::time_point{} ||
            RecoveryClock::now() >= loading_deadline_)
          throw std::runtime_error("Initial resource loading deadline expired");
      }
      if (stage != previous_loading_stage) {
        fprintf(stderr,"Native loading phase: %.*s\n",int(stage.size()),stage.data());
        previous_loading_stage = stage;
      }
    });
    env_->reset(*initial_scenario_,false);
    env_->state = GameState::game_running;
    // 2026-09-14: consume loading-screen gameplay taps; held state and UI commands stay available.
    window.buffer().Take();
    initial_load_finished_ = true;
    fprintf(stderr,"GameEnv initialized: %uv%u, seed=%u\n",left_agents_,right_agents_,seed_);
    fprintf(stderr,"Native resources loaded on game owner\n");
  }
  const char* connection_status() {
    std::lock_guard lock(mu_);
    if (!config_.native_product) return "Connected";
    switch (recovery_phase_) {
      case RecoveryPhase::Streaming:return "Connected";
      case RecoveryPhase::Loading:return "Loading match...";
      case RecoveryPhase::Cancelling:return "Leaving match...";
      case RecoveryPhase::Connecting:
      case RecoveryPhase::AwaitSession:
      case RecoveryPhase::Retrying:return "Reconnecting...";
      case RecoveryPhase::AwaitSnapshot:
      case RecoveryPhase::Restoring:
      case RecoveryPhase::Installing:
      case RecoveryPhase::AwaitAccepted:return "Restoring match...";
      default:return "Disconnected";
    }
  }

  bool save_replay(bool finish = true) {
    // 2026-09-13: saved product replays include the validated physical time contract.
    // return frame_sync::SaveNativeReplay(replay_recorder_, seed_, finish);
    if (config_.native_product) return save_recovery_replay(finish);
    const frame_sync::NativeMatchContract contract(seed_,left_agents_,right_agents_);
    return frame_sync::SaveNativeReplay(replay_recorder_, seed_, finish,config_.native_product ? &contract : nullptr);
  }

 private:
  // 2026-09-14: recover native sessions while preserving the legacy path.
  //   void fail_locked(const char* reason) {
  //     if (!running_) return;
  //     running_ = false; failed_ = true;
  //     fprintf(stderr, "TCP connection stopped: %s\n", reason);
  //     if (writer_) writer_->Close();
  //     std::vector<uint8_t>().swap(recv_buf_);
  //     decltype(auth_queue_)().swap(auth_queue_); auth_bytes_ = 0;
  //     pending_hashes_.clear(); arrival_times_.clear();
  //   }
  void fail_locked(const char* reason) {
    if (!running_) return;
    running_ = false;failed_ = true;
// 2026-09-21: retain original diagnostic format for comparison.
//     fprintf(stderr,"TCP connection stopped: %s\n",reason);
    fprintf(stderr,"%s connection stopped: %s\n",kTransportName,reason);
    if (config_.native_product) close_native_attempt_locked();
    else if (writer_) writer_->Close();
    clear_transport_payload_locked();recovery_phase_ = RecoveryPhase::Stopped;
  }
  // 2026-09-14: recover native sessions while preserving the legacy path.
  //   bool invalid_message() { fail_locked("invalid or unexpected message"); return false; }
  bool invalid_message() {
// 2026-09-21: retain original diagnostic format for comparison.
//     fprintf(stderr,"TCP invalid message: type=%u phase=%u buffered=%zu transport=%llu\n",
    fprintf(stderr,"%s invalid message: type=%u phase=%u buffered=%zu transport=%llu\n",kTransportName,
            recv_buf_.empty() ? 0U : unsigned(recv_buf_[0]),unsigned(recovery_phase_),recv_buf_.size(),
            static_cast<unsigned long long>(transport_generation_));
    fail_locked("invalid or unexpected message");return false;
  }
  // The transport only queues data. Presentation and engine mutation remain
  // confined to the game owner, including their first initialization.
  void EnsurePresentation(std::int64_t now) {
    if (presentation_) return;
    auto presentation = std::make_unique<frame_sync::NativePresentation<GameEnv>>(
        *env_, config_.render,
        std::chrono::nanoseconds(frame_sync::NativeLoopClock::Period(config_.frame_rate_hz)));
    auto callbacks = presentation->Wrap(frame_sync::MakeGameEnvCallbacks(env_));
    presentation->Initialize(now);
    engine_ = std::move(callbacks);
    presentation_ = std::move(presentation);
  }
  void init_game_env() {
    // 2026-08-31: Ensure env vars are set before start_game() reads them.
    // getenv() may return NULL if env was set in parent shell but not inherited.
    // 2026-09-09: GameEnv already discovers data/font paths; remove machine-specific overrides.
    // if (!getenv("GFOOTBALL_DATA_DIR")) {
    // setenv("GFOOTBALL_DATA_DIR", "/home/zuchangqu/project/football/engine/data", 1);
    // }
    // if (!getenv("GFOOTBALL_FONT")) {
    // setenv("GFOOTBALL_FONT",
    // "/home/zuchangqu/project/football/engine/data/media/fonts/alegreya/AlegreyaSansSC-ExtraBold.ttf",
    // 1);
    // }
    env_->game_config.render = config_.render;
    // 2026-09-13: native window clients present directly; legacy capture stays on.
    env_->game_config.capture_frames = !config_.native_product;
    // 2026-09-13: engine configuration follows the confirmed product cadence.
    // env_->game_config.physics_steps_per_frame = 10;
    env_->game_config.physics_steps_per_frame = config_.native_product ? frame_sync::NativeMatchContract::kPhysicsSteps : 10;

// 2026-09-09: empty teams cannot initialize a real match.
// auto scenario = ScenarioConfig::make();
// scenario->left_agents = left_agents_;
// scenario->right_agents = right_agents_;
// scenario->game_engine_random_seed = seed_;
    // 2026-09-13: duration and formation come from the same product descriptor.
    // auto scenario = frame_sync::MakeDefaultScenario(left_agents_, right_agents_, seed_);
    auto scenario = config_.native_product ? frame_sync::MakeNativeMatchScenario(frame_sync::NativeMatchContract(seed_,left_agents_,right_agents_))
                                           : frame_sync::MakeDefaultScenario(left_agents_, right_agents_, seed_);
    // 2026-09-14: create runtime/window here; reset installs resources on the game worker.
    // env_->start_game(*scenario);
    // env_->state = GameState::game_running;
    if (config_.native_product) {
      env_->prepare_game(*scenario);
      initial_scenario_ = std::move(scenario);
    } else {
      env_->start_game(*scenario);
      env_->state = GameState::game_running;
    }
    // 2026-09-13: initialization runs on the first game-owner operation.
    // presentation_->Initialize(frame_sync::NativeNow());

    // 2026-09-14: resource-ready telemetry is emitted after the owner reset.
    // fprintf(stderr, "GameEnv initialized: %uv%u, seed=%u\n",
    fprintf(stderr, "GameEnv runtime prepared: %uv%u, seed=%u\n",
            left_agents_, right_agents_, seed_);
  }

// 2026-09-09: validate server-controlled dimensions before initializing GameEnv
//   bool receive_session_start() {
//     uint8_t buf[32];
//     size_t n = read_exact(buf, 1 + frame_sync::SESSION_START_PARAMS_BYTES);
//     if (n == 0) return false;
//     return frame_sync::UnpackSessionStart(buf, n, &seed_, &left_agents_,
//                                           &right_agents_) != 0;
//   }
  // 2026-09-13: product descriptor validates version, cadence, duration and ownership.
  // bool receive_session_start() {
  bool receive_session_start() {
    if(config_.native_product) {
      std::array<uint8_t,frame_sync::NativeMatchContract::kSessionBytes> bytes{};
      if(read_exact(bytes.data(),bytes.size())!=bytes.size())return false;
      frame_sync::NativeMatchContract contract;
      if(!frame_sync::NativeMatchContract::Decode(bytes,frame_sync::NativeMatchContract::kSession,contract))return false;
      seed_=contract.seed;left_agents_=contract.left;right_agents_=contract.right;
      return true;
    }
    std::array<uint8_t, 9> bytes;
    if (read_exact(bytes.data(), bytes.size()) != bytes.size()) return false;
    if (!frame_sync::UnpackSessionStart(bytes.data(), bytes.size(), &seed_, &left_agents_, &right_agents_)) return false;
    return left_agents_ <= 11 && right_agents_ <= 11 && left_agents_ + right_agents_ > 0;
  }

// 2026-09-09: bound slot payload and reject duplicate/foreign slot assignments
//   bool receive_slot_assignment() {
//     uint8_t buf[64];
//     size_t n = read_exact(buf, 1 + 2);
//     if (n < 3) return false;
//     if (buf[0] != std::to_underlying(frame_sync::MessageType::SlotAssignment))
//       return false;
//     uint16_t num;
//     memcpy(&num, buf + 1, 2);
//     if (num > 32) return false;
//     n = read_exact(buf, num * 2);
//     if (n != num * 2) return false;
//     my_slots_.resize(num);
//     for (uint16_t i = 0; i < num; ++i)
//       memcpy(&my_slots_[i], buf + i * 2, 2);
//     if (!my_slots_.empty()) my_slot_index_ = my_slots_[0];
//     return true;
//   }
  bool receive_slot_assignment() {
    std::array<uint8_t, 3 + 22 * 2> bytes;
    if (read_exact(bytes.data(), 3) != 3 || bytes[0] != std::to_underlying(frame_sync::MessageType::SlotAssignment)) return false;
    uint16_t count; std::memcpy(&count, bytes.data() + 1, 2);
    const auto total = left_agents_ + right_agents_;
    if (count == 0 || count > total || count > 22 || read_exact(bytes.data() + 3, count * 2) != count * 2) return false;
    std::vector<uint16_t> slots;
    if (!frame_sync::UnpackSlotAssignment(bytes.data(), 3 + count * 2, &slots)) return false;
    std::array<bool, 22> used{};
    for (auto slot : slots) {
      if (slot >= total || used[slot]) return false;
      used[slot] = true;
    }
    my_slots_ = std::move(slots); my_slot_index_ = my_slots_[0];
    return true;
  }

// 2026-09-09: bound quiescent handshake reads instead of waiting forever for partial headers
//   size_t read_exact(uint8_t* buf, size_t need) {
//     size_t got = 0;
//     while (got < need) {
//       boost::system::error_code ec;
//       size_t n = asio::read(socket_, asio::buffer(buf + got, need - got), ec);
//       if (ec || n == 0) return 0;
//       got += n;
//     }
//     return got;
//   }
  size_t read_exact(uint8_t* bytes, size_t need) {
    if constexpr (!std::is_same_v<Socket,tcp::socket>) {
      return 0;
    } else {
    boost::system::error_code ec;
    socket_->non_blocking(true, ec);
    if (ec) return 0;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    size_t got = 0;
    while (got < need && std::chrono::steady_clock::now() < deadline) {
      got += socket_->read_some(asio::buffer(bytes + got, need - got), ec);
      if (ec == asio::error::would_block || ec == asio::error::try_again) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1)); continue;
      }
      if (ec) break;
    }
    boost::system::error_code ignored;
    socket_->non_blocking(false, ignored);
    return got == need && !ec ? got : 0;
    }
  }

// 2026-09-09: Ready uses the same ordered bounded writer as frame inputs
//   void send_ready() {
//     uint8_t buf[4];
//     size_t n = frame_sync::PackReady(buf, sizeof(buf));
//     asio::write(socket_, asio::buffer(buf, n));
//   }
  // 2026-09-13: Ready echoes the complete descriptor after GameEnv startup.
  // bool send_ready() {
  bool send_ready() {
    if(config_.native_product) {
      const auto ready=frame_sync::NativeMatchContract(seed_,left_agents_,right_agents_).Packet(frame_sync::NativeMatchContract::kReady);
      if(writer_->TrySend(ready.data(),ready.size()))return true;
      std::lock_guard lock(mu_);fail_locked("Native Ready send failed");return false;
    }
    const uint8_t ready = std::to_underlying(frame_sync::MessageType::Ready);
    if (writer_->TrySend(&ready, 1)) return true;
    std::lock_guard lock(mu_); fail_locked("Ready send failed"); return false;
  }

// 2026-09-09: one owned read buffer and an independent receive-capacity limit
//   void do_read() {
//     auto buf = std::make_shared<std::vector<uint8_t>>(4096);
//     socket_.async_read_some(
//         asio::buffer(*buf),
//         [this, buf](boost::system::error_code ec, std::size_t length) {
//           if (ec) return;
//           std::lock_guard<std::mutex> lock(mu_);
//           recv_buf_.insert(recv_buf_.end(), buf->begin(), buf->begin() + length);
//           while (parse_one_message()) {}
//           do_read();
//         });
//   }
  // 2026-09-14: recover native sessions while preserving the legacy path.
  //   void do_read() {
  //     auto bytes = std::make_shared<std::array<uint8_t, 4096>>();
  //     if (!writer_->AsyncReadSome(asio::buffer(*bytes), [this, bytes](boost::system::error_code ec, size_t length) {
  //           std::lock_guard lock(mu_);
  //           if (!running_) return;
  //           if (ec) { fail_locked("connection closed or stream read failed"); return; }
  //           if (!frame_sync::AppendBoundedBytes(recv_buf_, bytes->data(), length, 8192)) {
  //             fail_locked("receive capacity exceeded"); return;
  //           }
  //           while (running_ && parse_one_message()) {}
  //           if (running_) do_read();
  //         })) {
  //       fail_locked("read dispatch failed");
  //     }
  //   }
  void do_read() {
    auto bytes = std::make_shared<std::array<uint8_t,4096>>();
    const auto generation = transport_generation_;
    if (!writer_->AsyncReadSome(asio::buffer(*bytes),
        [this,bytes,generation](boost::system::error_code error,size_t length) {
          std::lock_guard lock(mu_);
          if (!running_ || (config_.native_product && generation != transport_generation_)) return;
          if (error) { transport_lost_locked("connection closed or stream read failed");return; }
          if (!frame_sync::AppendBoundedBytes(recv_buf_,bytes->data(),length,8192)) {
            fail_locked("receive capacity exceeded");return;
          }
          recovery_last_activity_ = RecoveryClock::now();
          while (running_ && parse_one_message()) {}
          if (running_ && (!config_.native_product || generation == transport_generation_)) do_read();
        })) transport_lost_locked("read dispatch failed");
  }

// 2026-09-09: validate framing before allocation; fail explicitly instead of silently losing authority
//   bool parse_one_message() {
//     if (recv_buf_.empty()) return false;
//     uint8_t type = recv_buf_[0];
//
//     if (type == std::to_underlying(frame_sync::MessageType::AuthoritativeFrame)) {
//       if (recv_buf_.size() < 7u) return false;
//       uint16_t num_slots;
//       memcpy(&num_slots, recv_buf_.data() + 5, 2);
//       size_t need = 7 + num_slots * frame_sync::SLOT_INPUT_BYTES;
//       if (recv_buf_.size() < need) return false;
//       frame_sync::frame_id_t fid;
//       std::vector<frame_sync::SlotInput> inputs;
//       size_t used = frame_sync::UnpackAuthoritativeFrame(
//           recv_buf_.data(), recv_buf_.size(), &fid, &inputs);
//       if (used == 0) return false;
//       if (auth_queue_.size() < 1024) auth_queue_.emplace(fid, std::move(inputs));
//       if (arrival_times_.size() < 1024) arrival_times_.push_back(
//           std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now().time_since_epoch()).count());
//       recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + used);
//       return true;
//     }
//
//     if (type == std::to_underlying(frame_sync::MessageType::StateHash)) {
//       if (recv_buf_.size() < frame_sync::STATE_HASH_PACK_BYTES) return false;
//       frame_sync::frame_id_t fid;
//       uint64_t hash;
//       size_t used = frame_sync::UnpackStateHash(
//           recv_buf_.data(), recv_buf_.size(), &fid, &hash);
//       if (used == 0) return false;
//
//       // Record server hash and check prediction accuracy
//       // 2026-09-09: keep IO-thread writes out of simulation state.
//       // client_state_.record_server_hash(fid, hash);
//       if (pending_hashes_.size() < 1024) pending_hashes_.emplace(fid, hash);
//
//       // Record prediction (we predict our state hash matches server's)
//       // The actual comparison happens when we receive the hash
//       // prediction_tracker_.RecordPrediction(fid, hash);  // Removed: this compared server data to itself.
//
//       recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + used);
//       return true;
//     }
//
//     // Handle Heartbeat (ms-17.1: latency compensation)
//     if (type == std::to_underlying(frame_sync::MessageType::Heartbeat)) {
//       if (recv_buf_.size() < frame_sync::HEARTBEAT_PACKET_BYTES) return false;
//
//       // 2026-09-09: the protocol decodes into heartbeat_t, not two output parameters.
//       frame_sync::heartbeat_t heartbeat;
//       size_t used = frame_sync::UnpackHeartbeat(
//           recv_buf_.data(), recv_buf_.size(), &heartbeat);
//       if (used == 0) return false;
//
//       // 2026-09-09: a one-way heartbeat cannot measure RTT. Remove fabricated 50 ms samples.
// //       // Record RTT measurement
// //       double now_ms = std::chrono::duration<double, std::milli>(
// //           std::chrono::steady_clock::now().time_since_epoch()).count();
// //       latency_comp_.RecordRTT(now_ms - 50.0, now_ms);  // Approximate RTT
// //
//       recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + used);
//       return true;
//     }
//
//     recv_buf_.erase(recv_buf_.begin());
//     return true;
//   }
  bool parse_one_message() {
    if (recv_buf_.empty()) return false;
    if (config_.native_product) {
      if (recv_buf_[0] >= static_cast<uint8_t>(frame_sync::NativeRecoveryKind::Hello) &&
// 2026-09-15: parse authenticated cancellation receipts without accepting arbitrary record types.
//           recv_buf_[0] <= static_cast<uint8_t>(frame_sync::NativeRecoveryKind::LoadReceipt))
          recv_buf_[0] <= static_cast<uint8_t>(frame_sync::NativeRecoveryKind::LoadCancelled))
        return parse_recovery_message_locked();
      // 2026-09-14: a loading lease carries only control records and heartbeat echoes.
      if ((recovery_phase_ == RecoveryPhase::Loading && recv_buf_[0] != std::to_underlying(frame_sync::MessageType::Heartbeat)) ||
          recovery_phase_ == RecoveryPhase::Connecting || recovery_phase_ == RecoveryPhase::AwaitSession ||
          recovery_phase_ == RecoveryPhase::Retrying ||
          (recovery_phase_ == RecoveryPhase::AwaitSnapshot && !recovery_snapshot_ &&
           recv_buf_[0] != std::to_underlying(frame_sync::MessageType::Heartbeat)))
        return invalid_message();
    }

    const auto type = static_cast<frame_sync::MessageType>(recv_buf_[0]);
    if (type == frame_sync::MessageType::AuthoritativeFrame) {
      if (recv_buf_.size() < 7) return false;
      uint16_t count; std::memcpy(&count, recv_buf_.data() + 5, 2);
      if (count != left_agents_ + right_agents_ || count > 22) return invalid_message();
      const auto need = 7 + count * frame_sync::SLOT_INPUT_BYTES;
      if (recv_buf_.size() < need) return false;
      frame_sync::frame_id_t frame; std::vector<frame_sync::SlotInput> inputs;
      if (!frame_sync::UnpackAuthoritativeFrame(recv_buf_.data(), need, &frame, &inputs) ||
          !std::all_of(inputs.begin(), inputs.end(), frame_sync::IsValidSlotInput)) return invalid_message();
      const auto bytes = frame_sync::RetainedBytes(inputs);
      if (auth_queue_.size() >= frame_sync::kMaxBufferedAuthorityFrames ||
          bytes > frame_sync::kMaxBufferedInputBytes - auth_bytes_ || arrival_times_.size() >= 1024) {
        fail_locked("authority queue capacity exceeded"); return false;
      }
// 2026-09-13: native reliable authority must be contiguous before it can advance input scheduling.
//       auth_queue_.emplace(frame, std::move(inputs)); auth_bytes_ += bytes;
      if (config_.native_product) {
        if (frame!=received_authority_count_ || frame==UINT32_MAX) return invalid_message();
        ++received_authority_count_;
      }
      auth_queue_.emplace(frame, std::move(inputs)); auth_bytes_ += bytes;
      arrival_times_.push_back(std::chrono::duration<double, std::milli>(
          std::chrono::steady_clock::now().time_since_epoch()).count());
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + need); return true;
    }
    if (type == frame_sync::MessageType::StateHash) {
      if (recv_buf_.size() < frame_sync::STATE_HASH_PACK_BYTES) return false;
      frame_sync::frame_id_t frame; uint64_t hash;
      if (!frame_sync::UnpackStateHash(recv_buf_.data(), recv_buf_.size(), &frame, &hash)) return invalid_message();
      const auto found = pending_hashes_.find(frame);
      if ((found != pending_hashes_.end() && found->second != hash) ||
          (found == pending_hashes_.end() && pending_hashes_.size() >= 1024)) {
        fail_locked("conflicting hash or hash queue capacity exceeded"); return false;
      }
      pending_hashes_[frame] = hash;
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + frame_sync::STATE_HASH_PACK_BYTES); return true;
    }
    if (type == frame_sync::MessageType::Heartbeat) {
      if (recv_buf_.size() < frame_sync::HEARTBEAT_PACK_BYTES) return false;
      if (config_.native_product) {
        frame_sync::heartbeat_t heartbeat{};
        if (!frame_sync::UnpackHeartbeat(recv_buf_.data(),recv_buf_.size(),&heartbeat)) return invalid_message();
        if (recovery_ping_pending_ && heartbeat.timestamp_ms == recovery_ping_.timestamp_ms &&
            heartbeat.frame_id == recovery_ping_.frame_id) {
          const auto milliseconds = std::chrono::duration<double,std::milli>(
              RecoveryClock::now()-recovery_last_ping_).count();
          const auto prior = native_rtt_ms_.load();
          native_rtt_variation_ms_ = prior > 0
              ? native_rtt_variation_ms_ * .75 + std::abs(milliseconds-prior) * .25
              : milliseconds * .5;
          const double smoothed = prior > 0 ? prior*.875+milliseconds*.125 : milliseconds;
          native_rtt_ms_ = smoothed;
          native_input_budget_ms_ = smoothed + 4*native_rtt_variation_ms_;
          ++recovery_heartbeat_echoes_;recovery_ping_pending_ = false;
        }
      }

      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + frame_sync::HEARTBEAT_PACK_BYTES); return true;
    }
    if (type == frame_sync::MessageType::TakeoverNotify || type == frame_sync::MessageType::HandbackNotify) {
      if (recv_buf_.size() < frame_sync::TAKEOVER_NOTIFY_BYTES) return false;
      uint16_t slot; std::memcpy(&slot, recv_buf_.data() + 1, 2);
      if (slot >= left_agents_ + right_agents_) return invalid_message();
      bot_slots_[slot] = type == frame_sync::MessageType::TakeoverNotify;
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + frame_sync::TAKEOVER_NOTIFY_BYTES); return true;
    }
    // This initial-connect client has not requested a snapshot or negotiated a
    // delta stream. Unexpected message types are a protocol failure.
    return invalid_message();
  }

  // Members
// 2026-09-09: private poll execution prevents callbacks outliving client UI state
//   asio::io_context& io_;
//   tcp::socket socket_;
  // Private context is destroyed last, after all never-dispatched callbacks.

  // 2026-09-14: physical transport attempts are isolated from the authoritative simulation.
  using RecoveryClock = std::chrono::steady_clock;
  // 2026-09-14: separate resource loading from network readiness.
  // enum class RecoveryPhase { Stopped, Connecting, AwaitSession, AwaitSnapshot, Restoring,
  enum class RecoveryPhase { Stopped, Connecting, AwaitSession, Loading, AwaitSnapshot, Restoring,
// 2026-09-15: cancellation cannot publish input or schedule connection retries.
//                              Installing, AwaitAccepted, Streaming, Retrying };
                             Installing, AwaitAccepted, Streaming, Retrying, Cancelling };
  bool recovery_can_tick_locked() const {
    return recovery_phase_ == RecoveryPhase::AwaitAccepted || recovery_phase_ == RecoveryPhase::Streaming;
  }
  // 2026-09-15: the server decides whether an admission has already become a match.
  // Offline or unacknowledged cancellation retains only the existing server lease.
  void request_loading_cancel_locked() {
    if (!config_.native_product || loading_cancel_requested_ ||
        recovery_phase_ == RecoveryPhase::Stopped || recovery_acceptances_ != 0)
      return;
    loading_cancel_requested_ = true;
    loading_cancel_until_ = RecoveryClock::now() + std::chrono::milliseconds(100);
    const bool connected_admission = recovery_phase_ == RecoveryPhase::Loading ||
        recovery_phase_ == RecoveryPhase::Restoring ||
        recovery_phase_ == RecoveryPhase::Installing ||
        recovery_phase_ == RecoveryPhase::AwaitAccepted;
    if (!connected_admission || !running_ || !recovery_grant_ || !writer_ || writer_->is_closed()) {
      running_ = false;
      close_native_attempt_locked();
      return;
    }
    const auto packet = frame_sync::pack_recovery_load_control(
        frame_sync::NativeRecoveryKind::LoadCancel, *recovery_grant_);
    recovery_phase_ = RecoveryPhase::Cancelling;
    loading_cancel_sent_ = writer_->TrySend(packet.bytes.data(), packet.size);
    if (!loading_cancel_sent_) {
      running_ = false;
      close_native_attempt_locked();
    }
  }
  void clear_transport_payload_locked() {
    std::vector<uint8_t>().swap(recv_buf_);
    decltype(auth_queue_)().swap(auth_queue_);auth_bytes_ = 0;
    pending_hashes_.clear();arrival_times_.clear();bot_slots_.fill(false);
    recovery_snapshot_.reset();recovery_assembler_.reset();
    recovery_ping_pending_ = false;recovery_last_ping_ = {};native_rtt_ms_ = 0;
    native_rtt_variation_ms_ = 0;native_input_budget_ms_ = 0;
  }
  void close_native_attempt_locked() {
    ++transport_generation_;
    recovery_resolver_.cancel();
    if (recovery_dialer_) recovery_dialer_->Cancel();
    boost::system::error_code ignored;
    recovery_timer_.cancel();
    if (writer_) writer_->Close();
// 2026-09-21: share the product session state across TCP and reliable UDP.
//     if (socket_) { socket_->cancel(ignored);socket_->close(ignored); }
    if (socket_) {
      if constexpr (std::is_same_v<Socket,tcp::socket>) socket_->cancel(ignored);
      socket_->close(ignored);
    }
  }
  void transport_lost_locked(const char* reason) {
    if (!config_.native_product) { fail_locked(reason);return; }
// 2026-09-15: a user exit never reconnects or renews the recovery budget.
//     if (!running_ || recovery_phase_ == RecoveryPhase::Retrying) return;
    if (loading_cancel_requested_) {
      running_ = false;
      close_native_attempt_locked();
      return;
    }
    if (!running_ || recovery_phase_ == RecoveryPhase::Retrying) return;
    const auto now = RecoveryClock::now();
    if (recovery_phase_ == RecoveryPhase::Streaming || recovery_phase_ == RecoveryPhase::Loading) {
      recovery_deadline_ = now + std::chrono::seconds(30);
      recovery_delay_ = std::chrono::milliseconds(100);
    }
    if (now >= recovery_deadline_) { fail_locked("reconnection deadline exceeded");return; }
    close_native_attempt_locked();clear_transport_payload_locked();
    recovery_phase_ = RecoveryPhase::Retrying;
    const auto generation = transport_generation_;
// 2026-09-21: retain original diagnostic format for comparison.
//     fprintf(stderr,"TCP reconnect pending: %s\n",reason);
    fprintf(stderr,"%s reconnect pending: %s\n",kTransportName,reason);
    recovery_timer_.expires_after(recovery_delay_);
    recovery_delay_ = std::min(recovery_delay_ * 2,std::chrono::milliseconds(1000));
    recovery_timer_.async_wait([this,generation](boost::system::error_code error) {
      std::lock_guard lock(mu_);
      if (error || !running_ || generation != transport_generation_ ||
          recovery_phase_ != RecoveryPhase::Retrying) return;
      if (RecoveryClock::now() >= recovery_deadline_) { fail_locked("reconnection deadline exceeded");return; }
      begin_native_attempt_locked();
    });
  }
// 2026-09-21: share the product session state across TCP and reliable UDP.
//   void begin_native_attempt_locked() {
//     ++transport_generation_;const auto generation = transport_generation_;
//     ++recovery_attempts_;recovery_phase_ = RecoveryPhase::Connecting;
//     recovery_phase_since_ = RecoveryClock::now();
//     socket_ = std::make_shared<tcp::socket>(io_);
//     const auto candidate = socket_;
//     recovery_resolver_.async_resolve(host_,std::to_string(port_),
//       [this,candidate,generation](boost::system::error_code error,tcp::resolver::results_type endpoints) {
//         std::lock_guard lock(mu_);
//         if (!running_ || generation != transport_generation_) return;
//         if (error) { transport_lost_locked("address resolution failed");return; }
//         asio::async_connect(*candidate,endpoints,
//           [this,candidate,generation](boost::system::error_code connected,const tcp::endpoint&) {
//             std::lock_guard lock(mu_);
//             if (!running_ || generation != transport_generation_) return;
//             if (connected) { transport_lost_locked("connection attempt failed");return; }
//             candidate->set_option(tcp::no_delay(true),connected);
//             if (connected) { transport_lost_locked("connection setup failed");return; }
//             writer_ = std::make_unique<frame_sync::BoundedTCPWriter>(candidate);
//             recovery_phase_ = RecoveryPhase::AwaitSession;
//             recovery_phase_since_ = recovery_last_activity_ = RecoveryClock::now();
//             const auto hello = recovery_grant_ ? frame_sync::pack_recovery_resume(*recovery_grant_)
//                                               : frame_sync::pack_recovery_load_hello(true);
//             if (!writer_->TrySend(hello.bytes.data(),hello.size)) {
//               transport_lost_locked("session request send failed");return;
//             }
//             do_read();
//           });
//       });
//   }
  void start_native_session_locked(const std::shared_ptr<Socket>& candidate) {
    socket_ = candidate;
    writer_ = std::make_unique<frame_sync::BasicBoundedStreamWriter<Socket>>(candidate);
    recovery_phase_ = RecoveryPhase::AwaitSession;
    recovery_phase_since_ = recovery_last_activity_ = RecoveryClock::now();
    const auto hello = recovery_grant_ ? frame_sync::pack_recovery_resume(*recovery_grant_)
                                      : frame_sync::pack_recovery_load_hello(true);
    if (!writer_->TrySend(hello.bytes.data(),hello.size)) {
      transport_lost_locked("session request send failed");return;
    }
    do_read();
  }
  void begin_native_attempt_locked() {
    ++transport_generation_;const auto generation = transport_generation_;
    ++recovery_attempts_;recovery_phase_ = RecoveryPhase::Connecting;
    recovery_phase_since_ = RecoveryClock::now();
    if constexpr (std::is_same_v<Socket,tcp::socket>) {
      socket_ = std::make_shared<Socket>(io_);
      const auto candidate = socket_;
      recovery_resolver_.async_resolve(host_,std::to_string(port_),
        [this,candidate,generation](boost::system::error_code error,tcp::resolver::results_type endpoints) {
          std::lock_guard lock(mu_);
          if (!running_ || generation != transport_generation_) return;
          if (error) { transport_lost_locked("address resolution failed");return; }
          asio::async_connect(*candidate,endpoints,
            [this,candidate,generation](boost::system::error_code connected,const tcp::endpoint&) {
              std::lock_guard lock(mu_);
              if (!running_ || generation != transport_generation_) return;
              if (connected) { transport_lost_locked("connection attempt failed");return; }
              candidate->set_option(tcp::no_delay(true),connected);
              if (connected) { transport_lost_locked("connection setup failed");return; }
              start_native_session_locked(candidate);
            });
        });
    } else {
      recovery_dialer_->async_connect(host_,port_,
        [this,generation](boost::system::error_code error,frame_sync::NativeUDPSocket socket) {
          std::lock_guard lock(mu_);
          if (!running_ || generation != transport_generation_) return;
          if (error) { transport_lost_locked("UDP connection attempt failed");return; }
          start_native_session_locked(std::make_shared<Socket>(std::move(socket)));
        });
    }
  }
// 2026-09-15: the bounded cancellation drain owns shutdown once requested.
//   void maintain_recovery_locked() {
//     if (!running_) return;
  void maintain_recovery_locked() {
    if (!running_ || loading_cancel_requested_) return;
    const auto now = RecoveryClock::now();
    // 2026-09-14: liveness and reconnection stay bounded during the separate resource budget.
    if (recovery_phase_ == RecoveryPhase::Loading && now >= loading_deadline_) {
      fail_locked("initial resource loading deadline exceeded");return;
    }
    // if (recovery_phase_ != RecoveryPhase::Streaming && now >= recovery_deadline_) {
    if (recovery_phase_ != RecoveryPhase::Streaming && recovery_phase_ != RecoveryPhase::Loading &&
        now >= recovery_deadline_) {
      fail_locked("reconnection deadline exceeded");return;
    }
    if ((recovery_phase_ == RecoveryPhase::Connecting || recovery_phase_ == RecoveryPhase::AwaitSession) &&
        now - recovery_phase_since_ >= std::chrono::seconds(5)) {
      transport_lost_locked("connection or session timeout");return;
    }
    if ((recovery_phase_ == RecoveryPhase::Streaming || recovery_phase_ == RecoveryPhase::Loading) &&
        now - recovery_last_activity_ >= std::chrono::seconds(3)) {
      transport_lost_locked("server stream timed out");return;
    }
    if (recovery_assembler_ && recovery_assembler_->expired(now)) {
      transport_lost_locked("snapshot transfer timed out");return;
    }
    if (recovery_phase_ != RecoveryPhase::Connecting && recovery_phase_ != RecoveryPhase::Retrying &&
        writer_ && writer_->is_closed()) { transport_lost_locked("stream write failed or timed out");return; }
    // 2026-09-14: connection liveness and RTT remain observable while the frame owner catches up.
    if (recovery_phase_ != RecoveryPhase::Connecting && recovery_phase_ != RecoveryPhase::AwaitSession &&
        recovery_phase_ != RecoveryPhase::Retrying && writer_ &&
        now - recovery_last_ping_ >= std::chrono::milliseconds(500)) {
      std::array<uint8_t,frame_sync::HEARTBEAT_PACK_BYTES> bytes;
      recovery_ping_.frame_id = received_authority_count_;
      recovery_ping_.timestamp_ms = static_cast<uint32_t>(
          std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count());
      const auto length = frame_sync::PackHeartbeat(recovery_ping_.frame_id,recovery_ping_.timestamp_ms,
                                                    bytes.data(),bytes.size());
      recovery_last_ping_ = now;recovery_ping_pending_ = true;
      if (!writer_->TrySend(bytes.data(),length)) transport_lost_locked("heartbeat send failed");
    }
  }
  bool connect_recovery() {
    {
      std::lock_guard lock(mu_);
      running_ = true;
      recovery_deadline_ = RecoveryClock::now() + std::chrono::seconds(30);
      begin_native_attempt_locked();
    }
    // Initial setup precedes the window loop; only this owner initializes GameEnv.
    for (;;) {
      poll();
      { std::lock_guard lock(mu_);if (!running_) return false;if (recovery_grant_) break; }
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    // 2026-09-14: graphics bootstrap may itself block; the transport owns no engine/SDL calls.
    {
      frame_sync::NativeTransportPump setup([this]{ poll(); },true);
      init_game_env();
      setup.Stop();setup.Check();
    }
    recovery_journal_ = std::make_unique<frame_sync::NativeRecoveryJournal>(
        frame_sync::NativeMatchContract(seed_,left_agents_,right_agents_));
    // 2026-09-14: NativeWindowInput starts the graphical game/GL worker after connect().
    // install_recovery_on_owner([] {});
    // First tick_buffered installs and sends Ready on that same owner as later restores.
    return running_;
  }
  bool parse_recovery_message_locked() {
    using Kind = frame_sync::NativeRecoveryKind;
    const auto size = frame_sync::native_recovery_wire::record_size(recv_buf_);
    if (size < 0) return invalid_message();
    if (!size) return false;
    const std::span<const uint8_t> bytes(recv_buf_.data(),size);
    const auto kind = static_cast<Kind>(bytes[0]);
    // 2026-09-15: retain validation while terminal control records drain.
    if (recovery_phase_ == RecoveryPhase::Cancelling) {
      if (kind == Kind::LoadCancelled) {
        const auto proof = frame_sync::decode_recovery_load_control(bytes, Kind::LoadCancelled);
        if (!proof || !recovery_grant_ || proof->slot != recovery_grant_->slot ||
            proof->generation != recovery_grant_->generation ||
            !frame_sync::native_secret_equal(proof->match, recovery_grant_->match) ||
            !frame_sync::native_secret_equal(proof->secret, recovery_grant_->secret))
          return invalid_message();
        loading_cancel_acknowledged_ = true;
      } else if (kind == Kind::Rejected) {
        if (!frame_sync::decode_recovery_rejected(bytes)) return invalid_message();
        loading_cancel_rejected_ = true;
      } else if (kind == Kind::Accepted) {
        // Ready may have won the server mutex; its following rejection is authoritative.
        const auto accepted = frame_sync::decode_recovery_accepted(bytes);
        if (!accepted || !recovery_grant_ || accepted->first != recovery_grant_->generation ||
            accepted->second != recovery_ready_boundary_) return invalid_message();
      } else return invalid_message();
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + size);
      return true;
    }
    if (kind == Kind::Session) {
      const auto session = frame_sync::decode_recovery_session(bytes);
      if (!session || recovery_phase_ != RecoveryPhase::AwaitSession) return invalid_message();
      const auto slots = session->slot_mask ? session->slot_mask : uint32_t{1} << session->grant.slot;
      if (recovery_grant_) {
        uint32_t prior_slots = 0;
        for (const auto slot : my_slots_) prior_slots |= uint32_t{1} << slot;
        if (slots != prior_slots) return invalid_message();
        if (session->match != frame_sync::NativeMatchContract(seed_,left_agents_,right_agents_) ||
            session->grant.match != recovery_grant_->match || session->grant.slot != recovery_grant_->slot ||
            session->grant.generation <= recovery_grant_->generation) return invalid_message();
      } else {
        seed_ = session->match.seed;left_agents_ = session->match.left;right_agents_ = session->match.right;
        my_slots_.clear();
        for (uint16_t slot = 0; slot < left_agents_ + right_agents_; ++slot)
          if (slots & (uint32_t{1} << slot)) my_slots_.push_back(slot);
        my_slot_index_ = session->grant.slot;
      }
      recovery_grant_ = session->grant;
      // 2026-09-14: an opening lease never becomes live input ownership.
      // recovery_phase_ = session->restoring ? RecoveryPhase::AwaitSnapshot : RecoveryPhase::Restoring;
      if (session->loading && recovery_acceptances_) return invalid_message();
      if (!session->loading && !initial_load_finished_.load()) return invalid_message();
      recovery_phase_ = session->loading ? RecoveryPhase::Loading :
                        session->restoring ? RecoveryPhase::AwaitSnapshot : RecoveryPhase::Restoring;
      if (session->loading) {
        if (loading_deadline_ == RecoveryClock::time_point{})
          loading_deadline_ = RecoveryClock::now()+frame_sync::kNativeInitialLoadingTimeout;
        const auto receipt=frame_sync::pack_recovery_load_control(frame_sync::NativeRecoveryKind::LoadReceipt,*recovery_grant_);
        if (!writer_->TrySend(receipt.bytes.data(),receipt.size)) {
          transport_lost_locked("loading receipt send failed");return false;
        }
      }
      recovery_phase_since_ = RecoveryClock::now();
      recovery_assembler_ = session->restoring ?
          std::make_unique<frame_sync::NativeRecoveryAssembler>(session->grant.generation) : nullptr;
      received_authority_count_ = 0;
    } else if (kind == Kind::Snapshot) {
      const auto metadata = frame_sync::decode_recovery_snapshot(bytes);
      if (!metadata || recovery_phase_ != RecoveryPhase::AwaitSnapshot || !recovery_assembler_ ||
          recovery_snapshot_ || metadata->generation != recovery_grant_->generation ||
          metadata->next_frame > UINT32_MAX - 1024 ||
          recovery_assembler_->begin(*metadata,RecoveryClock::now()) != frame_sync::NativeRecoveryReceive::Accepted)
        return invalid_message();
      recovery_snapshot_ = *metadata;received_authority_count_ = metadata->next_frame;
    } else if (kind == Kind::Chunk) {
      const auto chunk = frame_sync::decode_recovery_chunk(bytes);
      if (!chunk || !recovery_assembler_ || !recovery_snapshot_ ||
          recovery_phase_ != RecoveryPhase::AwaitSnapshot) return invalid_message();
      const auto result = recovery_assembler_->push(*chunk,RecoveryClock::now());
      if (result == frame_sync::NativeRecoveryReceive::Complete) recovery_phase_ = RecoveryPhase::Restoring;
      else if (result != frame_sync::NativeRecoveryReceive::Accepted &&
               result != frame_sync::NativeRecoveryReceive::Duplicate) return invalid_message();
    } else if (kind == Kind::Accepted) {
      const auto accepted = frame_sync::decode_recovery_accepted(bytes);
      if (!accepted || !recovery_grant_ || accepted->first != recovery_grant_->generation ||
          accepted->second < recovery_ready_boundary_ || accepted->second > received_authority_count_)
        return invalid_message();
      if (recovery_phase_ == RecoveryPhase::Streaming) {
        if (accepted->second != recovery_accepted_boundary_) return invalid_message();
      } else {
        if (recovery_phase_ != RecoveryPhase::AwaitAccepted) return invalid_message();
        recovery_phase_ = RecoveryPhase::Streaming;recovery_accepted_boundary_ = accepted->second;
        ++recovery_acceptances_;
// 2026-09-21: retain original diagnostic format for comparison.
//         fprintf(stderr,"TCP recovery accepted: attempt=%zu slot=%u frame=%u generation=%llu\n",
        fprintf(stderr,"%s recovery accepted: attempt=%zu slot=%u frame=%u generation=%llu\n",kTransportName,
                recovery_attempts_,unsigned(recovery_grant_->slot),accepted->second,
                static_cast<unsigned long long>(recovery_grant_->generation));
      }
    } else if (kind == Kind::Rejected) {
      if (!frame_sync::decode_recovery_rejected(bytes)) return invalid_message();
      fail_locked("server refused session recovery");return false;
    } else return invalid_message();
    recv_buf_.erase(recv_buf_.begin(),recv_buf_.begin()+size);
    return true;
  }


  // Called only by the game/frame owner, never by the IO pump.
  template<class ResetInput>
  bool install_recovery_on_owner(ResetInput&& reset_input) {

    {
      std::lock_guard lock(mu_);
      if (running_ && recovery_phase_ == RecoveryPhase::Loading && initial_load_finished_.load()) {
        // A lost initial completion packet may re-enter Loading, but never after an accepted frame.
        if (simulation_) {
          if (recovery_acceptances_ || simulation_->confirmed_count())
            throw std::runtime_error("Live simulation re-entered initial loading");
          simulation_.reset();
        }
        const auto complete=frame_sync::pack_recovery_load_control(
            frame_sync::NativeRecoveryKind::LoadComplete,*recovery_grant_);
        if (!writer_->TrySend(complete.bytes.data(),complete.size)) {
          transport_lost_locked("loading completion send failed");return false;
        }
        recovery_phase_=RecoveryPhase::Restoring;
        recovery_deadline_=RecoveryClock::now()+std::chrono::seconds(30);
      }
    }
    uint64_t generation;frame_sync::NativeRecoveryGrant grant;
    std::optional<frame_sync::NativeRecoverySnapshot> metadata;
    std::optional<std::vector<uint8_t>> state;
    {
      std::lock_guard lock(mu_);
      if (!running_ || recovery_phase_ != RecoveryPhase::Restoring) return false;
      generation = transport_generation_;grant = *recovery_grant_;metadata = recovery_snapshot_;
      if (metadata) {
        state = recovery_assembler_->take(RecoveryClock::now());
        if (!state) { transport_lost_locked("complete snapshot expired before installation");return false; }
      }
      recovery_phase_ = RecoveryPhase::Installing;
    }
    EnsurePresentation(frame_sync::NativeNow());
    presentation_->BeginTick(frame_sync::NativeNow());
    if (state) engine_.restore_state(*state);
    const auto hash = engine_.compute_hash();
    const uint32_t boundary = metadata ? metadata->next_frame : 0;
    if (metadata && hash != metadata->state_hash) throw std::runtime_error("Restored native state hash differs from server");
    if (!metadata && simulation_) throw std::runtime_error("Resumed native session omitted authoritative snapshot");
    simulation_ = std::make_unique<frame_sync::FrameSimulation>(
        engine_,static_cast<size_t>(left_agents_)+right_agents_,frame_sync::SnapshotBudget{},boundary);
    // Serialize reset with the pump's generation capture, sampling and publication.
    // Lock order is native_input_mu_ -> publication mutex -> client mu_, never the reverse.
    {
      std::lock_guard input_lock(native_input_mu_);
      native_publication_.Reset(boundary);
      if (metadata) std::invoke(std::forward<ResetInput>(reset_input));
    }
    current_frame_id_ = boundary;last_confirmed_frame_ = boundary ? boundary-1 : 0;
    prediction_tracker_.Reset();adaptive_cap_.Reset();
    if (metadata && recovery_journal_ && recovery_journal_->IsRecording()) {
      if (!recovery_journal_->Checkpoint(*metadata,std::move(*state)) &&
          recovery_journal_->GetStopReason() == frame_sync::ReplayStopReason::InvalidInput)
        throw std::runtime_error("Recovery snapshot regressed the replay timeline");
      report_replay_capacity();
    }
    presentation_->CommitTick(frame_sync::NativeNow());
    {
      std::lock_guard lock(mu_);
      if (!running_ || generation != transport_generation_ || recovery_phase_ != RecoveryPhase::Installing) return false;
      frame_sync::NativeRecoveryReady ready;ready.grant = grant;ready.next_frame = boundary;ready.state_hash = hash;
      const auto packet = frame_sync::pack_recovery_ready(ready);
      recovery_ready_boundary_ = boundary;recovery_phase_ = RecoveryPhase::AwaitAccepted;
      if (!writer_->TrySend(packet.bytes.data(),packet.size)) {
        transport_lost_locked("recovery readiness send failed");return false;
      }
    }
    return true;
  }
  void report_replay_capacity() {
    if (recovery_journal_ && !replay_capacity_reported_ &&
        recovery_journal_->GetStopReason() == frame_sync::ReplayStopReason::Capacity) {
      replay_capacity_reported_ = true;
      fprintf(stderr,"Replay recording reached its storage limit; the recorded prefix remains available.\n");
    }
  }
  bool save_recovery_replay(bool finish) {
    if (!recovery_journal_ || !recovery_journal_->HasReplayContent()) return true;
    if (finish) recovery_journal_->StopRecording();
    const auto path = "replay_"+std::to_string(seed_)+".bin";
    try {
      const auto result = frame_sync::SaveManagedReplayFile(*recovery_journal_,path);
      if (!result) {
        fprintf(stderr,"Replay save failed: %s (stage=%s, committed=%d, error=%s, cleanup=%s)\n",
                path.c_str(),result.stage,result.committed ? 1 : 0,result.error.message().c_str(),
                result.cleanup_error.message().c_str());
        return false;
      }
      fprintf(stderr,"Replay saved: %s (%zu frames, %zu bytes)\n",
              path.c_str(),recovery_journal_->GetFrameCount(),result.bytes);
      size_t attempts,acceptances,echoes;
      { std::lock_guard lock(mu_);attempts = recovery_attempts_;acceptances = recovery_acceptances_;echoes = recovery_heartbeat_echoes_; }
// 2026-09-21: retain original diagnostic format for comparison.
//       fprintf(stderr,"TCP heartbeat: echoes=%zu rtt_ms=%.3f\n",echoes,native_rtt_ms_.load());
      fprintf(stderr,"%s heartbeat: echoes=%zu rtt_ms=%.3f\n",kTransportName,echoes,native_rtt_ms_.load());
// 2026-09-21: retain original diagnostic format for comparison.
//       fprintf(stderr,"TCP recovery replay: checkpoints=%zu next_frame=%u attempts=%zu acceptances=%zu\n",
      fprintf(stderr,"%s recovery replay: checkpoints=%zu next_frame=%u attempts=%zu acceptances=%zu\n",kTransportName,
              recovery_journal_->checkpoint_count(),recovery_journal_->next_frame(),attempts,acceptances);
      return true;
    } catch (const std::exception& error) {
      fprintf(stderr,"Replay save failed: %s (%s)\n",path.c_str(),error.what());return false;
    }
  }

  asio::io_context io_;

  // 2026-09-14: native reconnection state is guarded by mu_; engine/journal stay on the frame owner.
  tcp::resolver recovery_resolver_{io_};
  std::unique_ptr<frame_sync::NativeUDPDialer> recovery_dialer_;
  asio::steady_timer recovery_timer_{io_};
  std::mutex native_input_mu_;
  RecoveryPhase recovery_phase_ = RecoveryPhase::Stopped;
  RecoveryClock::time_point recovery_deadline_{}, recovery_phase_since_{}, recovery_last_activity_{};
  std::chrono::milliseconds recovery_delay_{100};
  uint64_t transport_generation_ = 0;
  std::optional<frame_sync::NativeRecoveryGrant> recovery_grant_;
  std::optional<frame_sync::NativeRecoverySnapshot> recovery_snapshot_;
  std::unique_ptr<frame_sync::NativeRecoveryAssembler> recovery_assembler_;
  uint32_t recovery_ready_boundary_ = 0,recovery_accepted_boundary_ = 0;
  size_t recovery_attempts_ = 0,recovery_acceptances_ = 0;
  std::unique_ptr<frame_sync::NativeRecoveryJournal> recovery_journal_;
  bool replay_capacity_reported_ = false;
  // 2026-09-14: scenario stays on the initialization/game owner; IO only reads completion.
  std::shared_ptr<ScenarioConfig> initial_scenario_;
  std::atomic<bool> initial_load_finished_{false};
  RecoveryClock::time_point loading_deadline_{};
  // 2026-09-15: guarded by mu_, including the bounded stop dispatcher.
  RecoveryClock::time_point loading_cancel_until_{};
  bool loading_cancel_requested_ = false, loading_cancel_sent_ = false;
  bool loading_cancel_acknowledged_ = false, loading_cancel_rejected_ = false;

  // 2026-09-14: a bounded outstanding ping; stale echoes never affect a newer transport generation.
  frame_sync::heartbeat_t recovery_ping_{};
  RecoveryClock::time_point recovery_last_ping_{};
  bool recovery_ping_pending_ = false;
  size_t recovery_heartbeat_echoes_ = 0;
  std::atomic<double> native_rtt_ms_{0.0};
  // Variation is owned by the transport mutex; only the derived budget is shared.
  double native_rtt_variation_ms_ = 0;
  std::atomic<double> native_input_budget_ms_{0.0};

// 2026-09-21: share the product session state across TCP and reliable UDP.
//   std::shared_ptr<tcp::socket> socket_;
  std::shared_ptr<Socket> socket_;
// 2026-09-21: share the product session state across TCP and reliable UDP.
//   std::unique_ptr<frame_sync::BoundedTCPWriter> writer_;
  std::unique_ptr<frame_sync::BasicBoundedStreamWriter<Socket>> writer_;
// 2026-09-13: transport failure and stop are visible while the owner draws.
//   bool running_ = false, failed_ = false;
  std::atomic<bool> running_{false}, failed_{false};
  size_t auth_bytes_ = 0, verified_hashes_ = 0;
  std::array<bool, 22> bot_slots_{};
  std::string host_;
  unsigned short port_;
// 2026-09-13: guard IO execution separately from bounded receive state.
//   std::mutex mu_;
  std::mutex mu_;
  std::mutex poll_mu_;
  std::vector<uint8_t> recv_buf_;
  std::queue<std::pair<frame_sync::frame_id_t, std::vector<frame_sync::SlotInput>>> auth_queue_;
  std::vector<uint16_t> my_slots_;
  uint16_t my_slot_index_ = 0;
  uint32_t seed_ = 0;
  uint16_t left_agents_ = 0, right_agents_ = 0;

  GameEnv* env_;
  frame_sync::MultiplayerConfig config_;
  std::unique_ptr<frame_sync::NativePresentation<GameEnv>> presentation_;
  frame_sync::EngineCallbacks engine_;
  std::unique_ptr<frame_sync::FrameSimulation> simulation_;
  // 2026-09-13: same single-owner lifetime as the reconciliation state.
// 2026-09-13: IO updates the received boundary under mu_; the simulation may still be catching up.
//   frame_sync::LocalInputHistory local_input_history_;
// 2026-09-13: retain one history shared by publication and prediction, not a second input queue.
//   frame_sync::LocalInputHistory local_input_history_;
  frame_sync::LocalInputHistory local_input_history_;
  frame_sync::NativePublishedHistory native_publication_{local_input_history_};
  frame_sync::frame_id_t received_authority_count_ = 0;
  std::map<frame_sync::frame_id_t, uint64_t> pending_hashes_;

  frame_sync::frame_id_t current_frame_id_ = 0;
  frame_sync::frame_id_t last_confirmed_frame_ = 0;
  int frames_without_packet_ = 0;
  std::unordered_map<frame_sync::frame_id_t, frame_sync::SlotInput> predicted_inputs_;

  frame_sync::ClientState client_state_;

  // Phase 16 modules
  frame_sync::Interpolator interpolator_;                      ///< Frame interpolation/extrapolation
  frame_sync::PredictionAccuracyTracker prediction_tracker_;   ///< Prediction accuracy tracking
  frame_sync::AdaptivePredictionCap adaptive_cap_;             ///< Adaptive prediction cap
  std::vector<double> arrival_times_;  // guarded by mu_
  frame_sync::AdaptiveJitterBuffer jitter_buffer_;             ///< Adaptive jitter buffer
  frame_sync::LatencyCompensator latency_comp_;                ///< Latency compensation (ms-17.1)
  frame_sync::ReplayRecorder replay_recorder_;                  ///< Replay recording (ms-17.4)
  frame_sync::NetworkDiagnostics net_diag_;                     ///< Network diagnostics (ms-17.5)
  frame_sync::frame_id_t server_frame_ = 0;                                ///< Latest server frame number
};

// 2026-09-21: both products instantiate the same loading/recovery/replay implementation.
using IntegratedFrameSyncClient = BasicIntegratedFrameSyncClient<tcp::socket>;
using IntegratedFrameSyncUDPClient = BasicIntegratedFrameSyncClient<frame_sync::NativeUDPSocket>;

// ===== Main with SDL2 rendering =====

// 2026-09-13: replaced duplicated input/render loop; retained previous implementation.
// int main(int argc, char* argv[]) {
//   if (argc < 3) {
//     fprintf(stderr,
//         "Usage: %s <host> <port> [left_agents] [right_agents] [seed] [--headless]\n"
//         "\nKeyboard controls (for your controlled slot):\n"
//         "  WASD / Arrow keys  - Move\n"
//         "  Z - Short pass     X - High pass     C - Long pass\n"
//         "  V - Shoot          B - Sliding        Space - Pressure\n"
//         "  Shift - Sprint     Tab - Switch       M - Dribble\n"
//         "  ESC - Quit\n",
//         argv[0]);
//     return 1;
//   }
// 
//   frame_sync::NetworkDiagnostics net_diag;
//   frame_sync::MultiplayerConfig config;
//   config.host = argv[1];
//   config.port = static_cast<unsigned short>(std::stoi(argv[2]));
//   if (argc >= 4) config.left_agents = static_cast<uint16_t>(std::stoi(argv[3]));
//   if (argc >= 5) config.right_agents = static_cast<uint16_t>(std::stoi(argv[4]));
//   if (argc >= 6) config.seed = static_cast<uint32_t>(std::stoul(argv[5]));
//   config.is_server = false;
//   config.render = true;
// 
//   for (int i = 1; i < argc; ++i) {
//     if (std::string(argv[i]) == "--headless") {
//       config.render = false;
//     }
//   }
// 
//   fprintf(stderr, "Connecting to %s:%u (%uv%u, seed=%u, render=%s)\n",
//           config.host.c_str(), config.port,
//           config.left_agents, config.right_agents, config.seed,
//           config.render ? "on" : "off");
// 
//   // Initialize game environment
//   GameEnv env;
// 
//   asio::io_context io;
//   IntegratedFrameSyncClient client(io, config.host, config.port, &env, config);
// 
//   if (!client.connect()) {
//     fprintf(stderr, "Failed to connect\n");
//     return 1;
//   }
// 
//   fprintf(stderr, "Connected! My slots: %zu, seed=%u\n",
//           client.my_slots().size(), client.seed());
// 
//   // Initialize SDL for event handling (already initialized by GameEnv when render=true)
//   if (config.render) {
//     // SDL is already initialized by OpenGLRenderer3D::CreateContextSdl()
//     // We just need to pump events
//   }
// 
//   // Main game loop
//   // 2026-08-31 ms-1.7: 渲染平滑 — 解耦逻辑和渲染帧率
//   auto logic_period = std::chrono::milliseconds(1000 / config.frame_rate_hz);
//   auto render_period = std::chrono::milliseconds(1000 / config.render_rate_hz);
//   KeyboardState kb_state;
//   frame_sync::SlotInput my_input = frame_sync::SlotInput::Default();
//   bool running = true;
// 
//   // FPS tracking
//   int frame_count = 0;
//   auto fps_timer = std::chrono::steady_clock::now();
//   double current_fps = 0.0;
// 
//   // Timing for decoupled logic/render
//   auto last_logic_time = std::chrono::steady_clock::now();
//   auto last_render_time = std::chrono::steady_clock::now();
// 
//   while (running) {
//     // 2026-09-09: service the asynchronous socket reads on every iteration.
// // 2026-09-09: poll the client-owned IO and stop the application on transport failure
// //     io.poll();
//     client.poll();
//     if (!client.is_running()) break;
//     auto now = std::chrono::steady_clock::now();
// 
//     // Process SDL events (always, for responsiveness)
//     if (config.render) {
//       SDL_Event event;
//       while (SDL_PollEvent(&event)) {
//         switch (event.type) {
//           case SDL_QUIT:
//             running = false;
//             break;
//           case SDL_KEYDOWN:
//             if (event.key.keysym.sym == SDLK_ESCAPE) {
//               running = false;
//             }
//             break;
//         }
//       }
// 
//       // Read keyboard state for movement/actions
//       const Uint8* keys = SDL_GetKeyboardState(nullptr);
//       kb_state.update(keys);
//       my_input = kb_state.to_slot_input();
//     }
// 
//     // Logic tick (runs at frame_rate_hz, e.g., 10Hz)
//     auto logic_elapsed = now - last_logic_time;
//     if (logic_elapsed >= logic_period) {
//       last_logic_time = now;
// 
//       // Send input for current frame with correct slot indices
//       std::vector<frame_sync::SlotInput> local_inputs(client.my_slots().size(), my_input);
//       if (!client.my_slots().empty()) {
//         client.send_frame_input(client.current_frame_id(),
//                                 client.my_slots().data(),
//                                 local_inputs.data(),
//                                 static_cast<uint16_t>(client.my_slots().size()));
//       }
// 
//       // Run prediction tick
//       auto result = client.tick(my_input);
//       if (!client.is_running()) break;
//       using enum IntegratedFrameSyncClient::StepResult;
// 
//       switch (result) {
//         case kRollback:
//           fprintf(stderr, "Rollback at frame %u (total: %d)\n",
//                   client.current_frame_id(), client.rollback_count());
//           break;
//         case kWaitForAuthority:
//           break;
//         default:
//           break;
//       }
// 
//       // Save interpolation state after logic tick
//       if (config.render) {
//         // 2026-09-09: public env calls no longer leave an implicit TLS selection.
//         ContextHolder render_context(&env);
//         GetGameTask()->GetMatch()->SaveInterpolationState();
//       }
//     }
// 
//     // Render (runs at render_rate_hz, e.g., 60Hz)
//     auto render_elapsed = now - last_render_time;
//     if (config.render && render_elapsed >= render_period) {
//       last_render_time = now;
// 
//       // Calculate interpolation factor (0 = previous frame, 1 = current frame)
//       float t = static_cast<float>(std::chrono::duration<double>(now - last_logic_time).count()) /
//                 static_cast<float>(std::chrono::duration<double>(logic_period).count());
//       t = std::clamp(t, 0.0f, 1.0f);
// 
//       // Use interpolated rendering
//       // 2026-09-09: select this environment for direct Match rendering calls.
//       ContextHolder render_context(&env);
//       GetGameTask()->GetMatch()->PutInterpolated(t);
//       env.render();
// 
//       // Update window title with FPS and match info
//       frame_count++;
//       auto fps_now = std::chrono::steady_clock::now();
//       auto fps_elapsed = std::chrono::duration<double>(fps_now - fps_timer).count();
//       if (fps_elapsed >= 1.0) {
//         current_fps = frame_count / fps_elapsed;
//         frame_count = 0;
//         fps_timer = fps_now;
// 
//         // Update network diagnostics (ms-17.5)
//         net_diag.Update(client.smoothed_rtt(), client.jitter_ms(),
//                          client.prediction_accuracy(),
//                          0, client.rollback_count(),
//                          static_cast<int>(client.current_frame_id()));
// 
//         char title[256];
//         snprintf(title, sizeof(title),
//                  "Football MP | FPS: %.0f | Frame: %u | %s",
//                  current_fps, client.current_frame_id(),
//                  net_diag.FormatOverlay().c_str());
//         SDL_Window* win = SDL_GL_GetCurrentWindow();
//         if (win) SDL_SetWindowTitle(win, title);
//       }
// 
//       // Swap buffers
//       SDL_Window* win = SDL_GL_GetCurrentWindow();
//       if (win) SDL_GL_SwapWindow(win);
//     }
// 
//     // Maintain frame rate (use the faster of logic and render rates)
//     auto elapsed = std::chrono::steady_clock::now() - now;
//     auto min_period = std::min(logic_period, render_period);
//     if (elapsed < min_period)
//       std::this_thread::sleep_for(min_period - elapsed);
//   }
// 
//   fprintf(stderr, "Shutting down...\n");
//   fprintf(stderr, "TCP session confirmed=%u verified_hashes=%zu failed=%d\n",
//           client.confirmed_count(), client.verified_hashes(), client.failed() ? 1 : 0);
// 
// // 2026-09-09: preserve completed replay prefix and expose failed network sessions to automation
// //   client.save_replay();
// //
// //   return 0;
// // 2026-09-10: make failed persistence observable to the caller.
// //   client.save_replay();
// //   client.stop();
// //   return client.failed() ? 1 : 0;
//   const bool replay_saved = client.save_replay();
//   client.stop();
//   return client.failed() || !replay_saved ? 1 : 0;
// }
int main(int argc, char* argv[]) {
  try {
    const auto [config, frames] = frame_sync::NativeClientOptions(argc, argv);
    GameEnv env;
    asio::io_context io;
// 2026-09-21: share the product session state across TCP and reliable UDP.
//     IntegratedFrameSyncClient client(io, config.host, config.port, &env, config);
#if defined(FOOTBALL_NATIVE_UDP_CLIENT)
    IntegratedFrameSyncUDPClient client(io, config.host, config.port, &env, config);
#else
    IntegratedFrameSyncClient client(io, config.host, config.port, &env, config);
#endif
    if (!client.connect()) {
      fprintf(stderr, "Failed to connect\n");
      return 1;
    }
// 2026-09-21: share the product session state across TCP and reliable UDP.
//     return frame_sync::RunNativeClient(env, client, config, frames, "TCP");
#if defined(FOOTBALL_NATIVE_UDP_CLIENT)
    return frame_sync::RunNativeClient(env, client, config, frames, "UDP");
#else
    return frame_sync::RunNativeClient(env, client, config, frames, "TCP");
#endif
  } catch (const std::exception& error) {
// 2026-09-21: share the product session state across TCP and reliable UDP.
//     fprintf(stderr, "Native TCP client failed: %s\n", error.what());
    fprintf(stderr, "Native client failed: %s\n", error.what());
    return 1;
  }
}
