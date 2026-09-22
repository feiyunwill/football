#include "frame_sync/native_presentation.hpp"
#include "frame_sync/native_client_loop.hpp"
#include "frame_sync/native_replay.hpp"
// 2026-09-13: common product scenario construction.
// #include "frame_sync/default_scenario.hpp"  // 2026-09-09: common deterministic initial state.
#include "frame_sync/default_scenario.hpp"  // 2026-09-09: common deterministic initial state.
#include "frame_sync/native_match_scenario.hpp"
// Copyright 2026 Google LLC & Contributors
// Integrated frame sync client over reliable UDP with real engine (GameEnv).
// Combines UDP transport (ReliableUDPChannel) with rendering, keyboard input,
// and client-side prediction & rollback.
//
// Build: cmake --build . -j 1 --target integrated_client_udp
// Run:   GFOOTBALL_DATA_DIR=../data ./integrated_client_udp <host> <port> [--headless]

#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"
#include "frame_sync/reliable_udp.hpp"
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
#include "game_env.hpp"
#include "main.hpp"
#include "gfootball_actions.h"

#include <utility>
#include <boost/asio.hpp>
#include <SDL.h>
#include <array>
#include <stdexcept>
#include <algorithm>
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
using udp = asio::ip::udp;

// ===== Keyboard → SlotInput mapping =====
struct KeyboardState {
  float dir_x = 0.f;
  float dir_y = 0.f;
  uint16_t buttons = 0;

  void update(const Uint8* keys) {
    dir_x = 0.f;
    dir_y = 0.f;
    if (keys[SDL_SCANCODE_LEFT] || keys[SDL_SCANCODE_A]) dir_x -= 1.f;
    if (keys[SDL_SCANCODE_RIGHT] || keys[SDL_SCANCODE_D]) dir_x += 1.f;
    if (keys[SDL_SCANCODE_UP] || keys[SDL_SCANCODE_W]) dir_y += 1.f;
    if (keys[SDL_SCANCODE_DOWN] || keys[SDL_SCANCODE_S]) dir_y -= 1.f;

    float len = std::sqrt(dir_x * dir_x + dir_y * dir_y);
    if (len > 1.f) {
      dir_x /= len;
      dir_y /= len;
    }

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

// ===== IntegratedFrameSyncClientUDP =====

class IntegratedFrameSyncClientUDP {
 public:
  IntegratedFrameSyncClientUDP(asio::io_context& io, const std::string& host,
                               unsigned short port, GameEnv* env,
                               const frame_sync::MultiplayerConfig& config)
      : io_(io), socket_(io), host_(host), port_(port),
        env_(env), config_(config),
        client_state_(frame_sync::MAX_PREDICT_AHEAD_FRAMES + 4) {
    // 2026-09-13: the client owns presentation longer than its wrapped engine callbacks.
    // engine_ = frame_sync::MakeGameEnvCallbacks(env);
    if (!env_) throw std::invalid_argument("Client requires an environment");
    // 2026-09-13: defer presentation until the game owner first uses the initialized match.
//     presentation_ = std::make_unique<frame_sync::NativePresentation<GameEnv>>(
//         *env_, config_.render, std::chrono::nanoseconds(frame_sync::NativeLoopClock::Period(config_.frame_rate_hz)));
//     engine_ = presentation_->Wrap(frame_sync::MakeGameEnvCallbacks(env));
  }

  ~IntegratedFrameSyncClientUDP() { stop(); }
  IntegratedFrameSyncClientUDP(const IntegratedFrameSyncClientUDP&) = delete;
  IntegratedFrameSyncClientUDP& operator=(const IntegratedFrameSyncClientUDP&) = delete;
  IntegratedFrameSyncClientUDP(IntegratedFrameSyncClientUDP&&) = delete;
  IntegratedFrameSyncClientUDP& operator=(IntegratedFrameSyncClientUDP&&) = delete;
  // 2026-09-13: the owner dispatches bounded IO; no background thread can outlive rendering.
// 2026-09-13: only one owner may restart or dispatch this IO context at a time.
//   void poll() {
//     io_.restart();
  void poll() {
    std::lock_guard dispatch(poll_mu_);
    io_.restart();
    for (size_t i = 0; i < 64 && io_.poll_one() != 0; ++i) {}
  }
// 2026-09-13: serialize transport close with in-flight dispatch; the main loop joins its pump first.
//   void stop() {
//     std::lock_guard lock(mu_);
  void stop() {
    std::lock_guard dispatch(poll_mu_);
    std::lock_guard lock(mu_);
    running_ = false;
    if (channel_) channel_->Close();
    retransmit_timer_.cancel();
    boost::system::error_code ignored;
    socket_.close(ignored);
  }
  bool failed() const { return failed_; }
  size_t verified_hashes() const { return verified_hashes_; }
  bool save_replay(bool finish = true) {
    // 2026-09-13: saved product replays include the validated physical time contract.
    // return frame_sync::SaveNativeReplay(replay_recorder_, seed_, finish);
    const frame_sync::NativeMatchContract contract(seed_,left_agents_,right_agents_);
    return frame_sync::SaveNativeReplay(replay_recorder_, seed_, finish,config_.native_product ? &contract : nullptr);
  }

  bool connect() {
    boost::system::error_code ec;
    udp::resolver resolver(io_);
    auto endpoints = resolver.resolve(udp::v4(), host_, std::to_string(port_), ec);
    if (ec || endpoints.empty()) {
      fprintf(stderr, "Resolve failed: %s\n", ec ? ec.message().c_str() : "no endpoints");
      return false;
    }
    server_endpoint_ = *endpoints.begin();
    socket_.open(udp::v4(), ec);
    if (ec) { fprintf(stderr, "Open failed: %s\n", ec.message().c_str()); return false; }
    socket_.bind(udp::endpoint(udp::v4(), 0), ec);
    if (ec) { fprintf(stderr, "Bind failed: %s\n", ec.message().c_str()); return false; }

    // Send Connect so server creates our session
    // 2026-09-13: native product bootstrap declares its family and cadence.
    // uint8_t connect_byte = std::to_underlying(frame_sync::MessageType::Connect);
    // socket_.send_to(asio::buffer(&connect_byte, 1), server_endpoint_, 0, ec);
    if(config_.native_product) {
      const auto hello=frame_sync::NativeMatchContract::Header();
      socket_.send_to(asio::buffer(hello),server_endpoint_,0,ec);
    } else {
      uint8_t connect_byte = std::to_underlying(frame_sync::MessageType::Connect);
      socket_.send_to(asio::buffer(&connect_byte, 1), server_endpoint_, 0, ec);
    }
    if (ec) { fprintf(stderr, "Connect send failed: %s\n", ec.message().c_str()); return false; }

    do_receive();
    do_retransmit_timer();

    // Wait for SessionStart + SlotAssignment and send Ready (with timeout)
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // while (!ready_sent_ && std::chrono::steady_clock::now() < deadline) {
// 2026-09-09: Ready means the real engine can consume frames, including slow startup.
//     while (running_ && !ready_sent_ && std::chrono::steady_clock::now() < deadline) {
    // 2026-09-13: assignment cannot precede a validated product session.
    // bool assignment_received = false;
// 2026-09-13: retry a dropped connectionless hello within the existing bounded handshake deadline.
//     bool assignment_received = false, contract_received = false;
    bool assignment_received = false, contract_received = false;
    auto next_hello=std::chrono::steady_clock::now()+std::chrono::milliseconds(200);
    while (running_ && !assignment_received && std::chrono::steady_clock::now() < deadline) {
      io_.run_one();
      std::lock_guard<std::mutex> lock(mu_);
// 2026-09-13: retry only bootstrap; the reliable stream owns session retransmission.
//       // 2026-09-13: validate all descriptor fields before slot allocation or native startup.
      if (config_.native_product && !contract_received && std::chrono::steady_clock::now()>=next_hello) {
        const auto hello=frame_sync::NativeMatchContract::Header();
        socket_.send_to(asio::buffer(hello),server_endpoint_,0,ec);
        if (ec) { fail_transport_locked(); return false; }
        next_hello=std::chrono::steady_clock::now()+std::chrono::milliseconds(200);
      }
      // 2026-09-13: validate all descriptor fields before slot allocation or native startup.
      // while (recv_buf_.size() >= 1u + frame_sync::SESSION_START_PARAMS_BYTES &&
      if(config_.native_product && !contract_received && !recv_buf_.empty()) {
        if(recv_buf_[0]!=frame_sync::NativeMatchContract::kSession) {fail_transport_locked();return false;}
        if(recv_buf_.size()<frame_sync::NativeMatchContract::kSessionBytes)continue;
        frame_sync::NativeMatchContract contract;
        if(!frame_sync::NativeMatchContract::Decode({recv_buf_.data(),32},frame_sync::NativeMatchContract::kSession,contract))
          {fail_transport_locked();return false;}
        seed_=contract.seed;left_agents_=contract.left;right_agents_=contract.right;contract_received=true;
        recv_buf_.erase(recv_buf_.begin(),recv_buf_.begin()+32);
      }
      while (!config_.native_product && recv_buf_.size() >= 1u + frame_sync::SESSION_START_PARAMS_BYTES &&
             recv_buf_[0] == std::to_underlying(frame_sync::MessageType::SessionStart)) {
        frame_sync::UnpackSessionStart(recv_buf_.data(), recv_buf_.size(),
                                       &seed_, &left_agents_, &right_agents_);
        recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() +
                        static_cast<std::ptrdiff_t>(1 + frame_sync::SESSION_START_PARAMS_BYTES));
      }
      if (recv_buf_.size() >= 3u &&
          recv_buf_[0] == std::to_underlying(frame_sync::MessageType::SlotAssignment)) {
        uint16_t num;
        memcpy(&num, recv_buf_.data() + 1, 2);
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // size_t need = 3 + num * 2;
        if (num == 0 || num > frame_sync::kMaxControlledSlots ||
            left_agents_ > 11 || right_agents_ > 11 || num > left_agents_ + right_agents_) {
          fail_transport_locked();
          return false;
        }
        size_t need = 3 + num * 2;
        if (recv_buf_.size() >= need) {
          my_slots_.resize(num);
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // for (uint16_t i = 0; i < num; ++i)
  // memcpy(&my_slots_[i], recv_buf_.data() + 3 + i * 2, 2);
          std::array<bool, frame_sync::kMaxControlledSlots> assigned{};
          for (uint16_t i = 0; i < num; ++i) {
            memcpy(&my_slots_[i], recv_buf_.data() + 3 + i * 2, 2);
            const auto slot = my_slots_[i];
            if (slot >= left_agents_ + right_agents_ || assigned[slot]) {
              fail_transport_locked();
              return false;
            }
            assigned[slot] = true;
          }
          recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + static_cast<std::ptrdiff_t>(need));
// 2026-09-09: Ready means the real engine can consume frames, including slow startup.
//           send_ready();
          assignment_received = true;
  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // ready_sent_ = true;
// 2026-09-09: Ready means the real engine can consume frames, including slow startup.
//           ready_sent_ = running_;
          // Transport ACKs already acknowledge the received assignment.
          break;
        }
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
// 2026-09-09: Ready means the real engine can consume frames, including slow startup.
//     if (!ready_sent_) {
    if (!assignment_received) {
      fprintf(stderr, "Timeout waiting for SessionStart/SlotAssignment\n");
      return false;
    }
    // 2026-09-01: 握手成功后初始化 GameEnv，否则 tick() 中 get_state() 会因
    // context=nullptr crash（之前缺失此步骤导致 Segfault）。
// 2026-09-09: Ready means the real engine can consume frames, including slow startup.
//     init_game_env();
//     return true;
    init_game_env();
    {
      std::lock_guard<std::mutex> lock(mu_);
      send_ready();
      ready_sent_ = running_;
    }
    if (ready_sent_) replay_recorder_.StartRecording(seed_, "default_11v11",
        static_cast<uint32_t>(left_agents_) + right_agents_);
    return ready_sent_;
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
  //     int frames_to_process = client_state_.catchup_count(
  //         last_confirmed_frame_, current_frame_id_);
  //     if (frames_to_process < 0) {
  //       return StepResult::kWaitForAuthority;
  //     }
  //     if (frames_to_process == 0) frames_to_process = 1;
  //
  //     auto lag = current_frame_id_ - last_confirmed_frame_;
  //     if (lag >= static_cast<frame_sync::frame_id_t>(
  //             frame_sync::MAX_PREDICT_AHEAD_FRAMES)) {
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
  //       frames_without_packet_ = 0;
  //     }
  //
  //     auto now = std::chrono::steady_clock::now();
  //     double now_ms = std::chrono::duration<double, std::milli>(
  //         now.time_since_epoch()).count();
  //     client_state_.record_frame_arrival(now_ms);
  //     client_state_.evict_old(current_frame_id_);
  //
  //     return result;
  //   }
  //
  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // StepResult tick(const frame_sync::SlotInput& my_input) {
  // if (!simulation_)
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
      fprintf(stderr, "UDP input admission failed: %s\n", error.what());
      fail_transport_locked();
      return StepResult::kWaitForAuthority;
    }
  }

// 2026-09-13: continue receive and one-time submission during slow draws and reconciliation.
//   template<class InputProvider>
//   StepResult tick_with_input_provider(InputProvider&& provider) {
  // Transport-only entry point: no SDL, presentation or FrameSimulation access.
  template<class InputBuffer>
  void pump_input(InputBuffer& buffer) {
    poll();
    if (!config_.native_product || !is_running() || my_slots_.empty()) return;
    frame_sync::frame_id_t authority_count;
    { std::lock_guard lock(mu_);authority_count=received_authority_count_; }
    // 2026-09-13: authority receipt refines a clock; it does not clock every publication.
//     native_publication_.Publish(authority_count,
    native_publication_.PublishTimed(authority_count,
        [&](frame_sync::frame_id_t) { return buffer.Take(); },
        [&](frame_sync::frame_id_t frame,const frame_sync::SlotInput& input) {
          std::array<frame_sync::SlotInput,frame_sync::kMaxControlledSlots> inputs;
          std::fill_n(inputs.begin(),my_slots_.size(),input);
          return send_frame_input(frame,my_slots_.data(),inputs.data(),static_cast<uint16_t>(my_slots_.size()));
        });
    poll();
  }

  template<class InputProvider>
  StepResult tick_with_input_provider(InputProvider&& provider) {
    if (!running_) return StepResult::kWaitForAuthority;
    // 2026-09-13: initialize before constructing callbacks owned by reconciliation.
    EnsurePresentation(frame_sync::NativeNow());
    if (!simulation_) simulation_ = std::make_unique<frame_sync::FrameSimulation>(
        engine_, static_cast<size_t>(left_agents_) + right_agents_);
    frame_sync::frame_id_t fid;
    std::vector<frame_sync::SlotInput> inputs;
    while (pop_authoritative_frame(&fid, &inputs)) {
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // if (!simulation_->QueueAuthority(fid, std::move(inputs)))
  // fprintf(stderr, "Invalid authoritative frame %u\n", fid);
      if (!simulation_->QueueAuthority(fid, inputs)) {
        std::lock_guard<std::mutex> lock(mu_);
        fail_transport_locked();
        return StepResult::kWaitForAuthority;
      }
    }
    // 2026-09-13: previous Tick(my_input, ...) sampled before authority catchup.
    presentation_->BeginTick(frame_sync::NativeNow());
    auto tick = simulation_->TickWithInputProvider(provider, my_slots_, frame_sync::MAX_PREDICT_AHEAD_FRAMES);
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
          if (it->first < simulation_->confirmed_count()) it = pending_hashes_.erase(it);
          else ++it;
          continue;
        }
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // if (!*matches) fprintf(stderr, "State hash mismatch at frame %u\n", it->first);
        if (!*matches) {
          fprintf(stderr, "State hash mismatch at frame %u\n", it->first);
          fail_transport_locked();
          return StepResult::kWaitForAuthority;
        }
        ++verified_hashes_;
        it = pending_hashes_.erase(it);
      }
    }
    for (const auto& confirmed : tick.confirmed)
      if (replay_recorder_.IsRecording())
        replay_recorder_.RecordFrame(confirmed.frame, confirmed.hash, confirmed.inputs);
    if (tick.rolled_back) return StepResult::kRollback;
    if (tick.confirmed.size() > 1) return StepResult::kCatchup;
    if (!tick.predicted && tick.confirmed.empty()) return StepResult::kWaitForAuthority;
    return StepResult::kNormal;
  }

  // 2026-09-13: propagate send rejection and match the TCP slot contract.
  // Previous return type was void; a missing channel silently returned.
  bool send_frame_input(frame_sync::frame_id_t frame_id,
                        const uint16_t* slot_indices,
                        const frame_sync::SlotInput* inputs,
                        uint16_t num_slots) {
    std::lock_guard<std::mutex> lock(mu_);
    if (!running_ || !channel_) return false;
    if (!slot_indices || !inputs || num_slots == 0 ||
        num_slots != my_slots_.size() || num_slots > frame_sync::kMaxControlledSlots) {
      fail_transport_locked();
      return false;
    }
    for (uint16_t i = 0; i < num_slots; ++i) {
      if (slot_indices[i] != my_slots_[i] || !frame_sync::IsValidSlotInput(inputs[i])) {
        fail_transport_locked();
        return false;
      }
    }
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // std::vector<uint8_t> buf(256);
    std::array<uint8_t, 7 + frame_sync::kMaxControlledSlots * (2 + frame_sync::SLOT_INPUT_BYTES)> buf{};
    size_t n = frame_sync::PackClientFrameInput(
        frame_id, slot_indices, inputs, num_slots, buf.data(), buf.size());
  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // if (n) channel_->Send(buf.data(), n);
    // 2026-09-13: previous failure path had no result for the input supplier.
    // if (!n || !channel_->Send(buf.data(), n)) fail_transport_locked();
    if (!n || !channel_->Send(buf.data(), n)) {
      fail_transport_locked();
      return false;
    }
    return true;
  }

  bool pop_authoritative_frame(frame_sync::frame_id_t* frame_id,
                               std::vector<frame_sync::SlotInput>* inputs) {
    std::lock_guard<std::mutex> lock(mu_);
    if (auth_queue_.empty()) return false;
    *frame_id = auth_queue_.front().first;
    *inputs = auth_queue_.front().second;
    auth_queue_.pop();
    return true;
  }

  const std::vector<uint16_t>& my_slots() const { return my_slots_; }
  uint32_t seed() const { return seed_; }
  uint16_t left_agents() const { return left_agents_; }
  uint16_t right_agents() const { return right_agents_; }
  frame_sync::frame_id_t current_frame_id() const { return current_frame_id_; }
  frame_sync::frame_id_t last_confirmed_frame() const { return last_confirmed_frame_; }
  frame_sync::frame_id_t confirmed_count() const {
    return simulation_ ? simulation_->confirmed_count() : 0;
  }
  // 2026-09-09: reconciliation owns the rollback counter.
  // int rollback_count() const { return client_state_.rollback_count(); }
  int rollback_count() const { return simulation_ ? simulation_->rollback_count() : 0; }

// 2026-09-13: expose received-but-unapplied authority so rendering cannot indefinitely grow reconciliation lag.
//   bool is_running() const { return running_.load(); }
  bool is_running() const { return running_.load(); }
  // Called by the simulation owner only; transport receipt is protected by mu_.
  bool has_pending_authority() {
    std::lock_guard lock(mu_);
    return config_.native_product && received_authority_count_ > confirmed_count();
  }

 private:
  // The caller owns mu_. Cancellation callbacks are dispatched after returning.
  void fail_transport_locked() {
    if (!running_.exchange(false)) return;
    failed_ = true;
    // 2026-09-09: expose the transport reason in bounded per-disconnect diagnostics.
    // fprintf(stderr, "UDP connection stopped: reliable delivery failed\n");
// 2026-09-09: distinguish application rejection from a ready transport.
//     fprintf(stderr, "UDP connection stopped: %s\n", channel_ ?
//         frame_sync::UDPChannelStatusName(channel_->status()) : "invalid session");
    const auto status = channel_ ? channel_->status() : frame_sync::UDPChannelStatus::Closed;
    fprintf(stderr, "UDP connection stopped: %s\n",
        status == frame_sync::UDPChannelStatus::Ready ? "invalid or overloaded stream" :
        frame_sync::UDPChannelStatusName(status));
    if (channel_) channel_->Close();
    boost::system::error_code ignored;
    // 2026-09-09: installed Boost exposes only the no-argument timer overload.
    // retransmit_timer_.cancel(ignored);
    retransmit_timer_.cancel();
    socket_.cancel(ignored);
    std::vector<uint8_t>().swap(recv_buf_);
    decltype(auth_queue_)().swap(auth_queue_);
    pending_hashes_.clear();
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
    env_->start_game(*scenario);
    env_->state = GameState::game_running;
    // 2026-09-13: initialization runs on the first game-owner operation.
    // presentation_->Initialize(frame_sync::NativeNow());

    fprintf(stderr, "GameEnv initialized: %uv%u, seed=%u\n",
            left_agents_, right_agents_, seed_);
  }

  void do_receive() {
    if (!running_) return;
    auto buf = std::make_shared<std::vector<uint8_t>>(4096);
    auto sender = std::make_shared<udp::endpoint>();
    socket_.async_receive_from(
        asio::buffer(*buf), *sender,
        [this, buf, sender](boost::system::error_code ec, std::size_t length) {
          if (ec) { do_receive(); return; }
  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // std::lock_guard<std::mutex> lock(mu_);
  // if (!channel_) {
          std::lock_guard<std::mutex> lock(mu_);
          if (*sender != server_endpoint_) { do_receive(); return; }
          if (!channel_) {
            channel_ = std::make_unique<frame_sync::ReliableUDPChannel>(
                socket_, *sender,
                [this](const uint8_t* d, size_t n) {
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // recv_buf_.insert(recv_buf_.end(), d, d + n);
                  if (!frame_sync::AppendBoundedBytes(recv_buf_, d, n, 4096)) {
                    fail_transport_locked();
                    return;
                  }
                  while (parse_one_message()) {}
                });
          }
  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // if (channel_) channel_->HandleReceived(buf->data(), length);
          if (channel_ && !channel_->HandleReceived(buf->data(), length))
            fail_transport_locked();
          do_receive();
        });
  }

  void do_retransmit_timer() {
    retransmit_timer_.expires_after(std::chrono::milliseconds(20));
    retransmit_timer_.async_wait([this](boost::system::error_code ec) {
      if (ec || !running_) return;
      std::lock_guard<std::mutex> lock(mu_);
  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // if (channel_) channel_->TickRetransmit();
      if (channel_ && !channel_->TickRetransmit()) {
        fail_transport_locked();
        return;
      }
      // 2026-09-13: unique input publication can leave no data awaiting ACK.
      // Independent reliable heartbeats keep silent peer failure observable.
      const auto now = std::chrono::steady_clock::now();
      if (ready_sent_ && channel_ && now >= next_heartbeat_) {
        std::array<uint8_t, frame_sync::HEARTBEAT_PACKET_BYTES> packet{};
        const auto timestamp = static_cast<uint32_t>(
            std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count());
        const auto bytes = frame_sync::PackHeartbeat(current_frame_id_, timestamp, packet.data(), packet.size());
        if (!bytes || !channel_->Send(packet.data(), bytes)) {
          fail_transport_locked();
          return;
        }
        next_heartbeat_ = now + std::chrono::milliseconds(frame_sync::HEARTBEAT_INTERVAL_MS);
      }
      do_retransmit_timer();
    });
  }

  bool parse_one_message() {
    if (recv_buf_.empty()) return false;
    uint8_t type = recv_buf_[0];
    // 2026-09-09: consume complete control messages; payload bytes are not types.
    if (type == std::to_underlying(frame_sync::MessageType::Heartbeat)) {
      if (recv_buf_.size() < frame_sync::HEARTBEAT_PACKET_BYTES) return false;
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + frame_sync::HEARTBEAT_PACKET_BYTES);
      return true;
    }


    // 2026-09-14: these notices previously reached the one-byte fallback:
    // recv_buf_.erase(recv_buf_.begin());
    // return true;
    // Consume the entire record before reading another type.
    // Authority already contains the bot input; this notice must not alter local controls.
    if (type == std::to_underlying(frame_sync::MessageType::TakeoverNotify) ||
        type == std::to_underlying(frame_sync::MessageType::HandbackNotify)) {
      if (recv_buf_.size() < frame_sync::TAKEOVER_NOTIFY_BYTES) return false;
      uint16_t slot;
      frame_sync::frame_id_t frame;
      const auto used = type == std::to_underlying(frame_sync::MessageType::TakeoverNotify)
          ? frame_sync::UnpackTakeoverNotify(recv_buf_.data(), recv_buf_.size(), &slot, &frame)
          : frame_sync::UnpackHandbackNotify(recv_buf_.data(), recv_buf_.size(), &slot, &frame);
      if (!used || slot >= left_agents_ + right_agents_ ||
          (config_.native_product && frame != received_authority_count_)) {
        fail_transport_locked();
        return false;
      }
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + used);
      return true;
    }

    // 2026-09-01: 连接阶段的消息由 connect() 直接解析，此处跳过避免吞掉。
    // 2026-09-13: leave bootstrap descriptors for the owner handshake parser.
    // if (type == std::to_underlying(frame_sync::MessageType::SessionStart) ||
    if (type == frame_sync::NativeMatchContract::kSession ||
        type == std::to_underlying(frame_sync::MessageType::SessionStart) ||
        type == std::to_underlying(frame_sync::MessageType::SlotAssignment) ||
        type == std::to_underlying(frame_sync::MessageType::Connect)) {
      return false;  // 让 connect() 处理
    }

    if (type == std::to_underlying(frame_sync::MessageType::AuthoritativeFrame)) {
      if (recv_buf_.size() < 7u) return false;
      uint16_t num_slots;
      memcpy(&num_slots, recv_buf_.data() + 5, 2);
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // size_t need = 7 + num_slots * frame_sync::SLOT_INPUT_BYTES;
      if (num_slots == 0 || num_slots != left_agents_ + right_agents_ ||
          num_slots > frame_sync::kMaxControlledSlots) {
        fail_transport_locked();
        return false;
      }
      size_t need = 7 + num_slots * frame_sync::SLOT_INPUT_BYTES;
      if (recv_buf_.size() < need) return false;
      frame_sync::frame_id_t fid;
      std::vector<frame_sync::SlotInput> inputs;
      size_t used = frame_sync::UnpackAuthoritativeFrame(
          recv_buf_.data(), recv_buf_.size(), &fid, &inputs);
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // if (used == 0) return false;
      if (used == 0) { fail_transport_locked(); return false; }
      // 2026-09-09: bound queued authority while the logic thread is stalled.
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // if (auth_queue_.size() < 1024) auth_queue_.emplace(fid, std::move(inputs));
      if (auth_queue_.size() >= frame_sync::kMaxBufferedAuthorityFrames ||
          !std::all_of(inputs.begin(), inputs.end(), frame_sync::IsValidSlotInput)) {
        fail_transport_locked();
        return false;
      }
// 2026-09-13: reliable UDP delivery owns deduplication; gameplay authority advances contiguously.
//       auth_queue_.emplace(fid, std::move(inputs));
      if (config_.native_product) {
        if (fid!=received_authority_count_ || fid==UINT32_MAX) { fail_transport_locked(); return false; }
        ++received_authority_count_;
      }
      auth_queue_.emplace(fid, std::move(inputs));
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + used);
      return true;
    }

    if (type == std::to_underlying(frame_sync::MessageType::StateHash)) {
      if (recv_buf_.size() < frame_sync::STATE_HASH_PACK_BYTES) return false;
      frame_sync::frame_id_t fid;
      uint64_t hash;
      size_t used = frame_sync::UnpackStateHash(
          recv_buf_.data(), recv_buf_.size(), &fid, &hash);
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // if (used == 0) return false;
      if (used == 0) { fail_transport_locked(); return false; }
      // 2026-09-09: keep IO-thread writes out of simulation state.
      // client_state_.record_server_hash(fid, hash);
  // 2026-09-09: validate before allocation and stop on invalid/overloaded input.
  // if (pending_hashes_.size() < 1024) pending_hashes_.emplace(fid, hash);
      if (!pending_hashes_.contains(fid) &&
          pending_hashes_.size() >= frame_sync::kMaxBufferedAuthorityFrames) {
        fail_transport_locked();
        return false;
      }
      pending_hashes_.emplace(fid, hash);
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + used);
      return true;
    }

    recv_buf_.erase(recv_buf_.begin());
    return true;
  }

  // 2026-09-13: reliable Ready acknowledges the actual initialized contract.
  // void send_ready() {
  //   if (!channel_) return;
  void send_ready() {
    if (!channel_) return;
    if(config_.native_product) {
      const auto ready=frame_sync::NativeMatchContract(seed_,left_agents_,right_agents_).Packet(frame_sync::NativeMatchContract::kReady);
      if(!channel_->Send(ready.data(),ready.size()))fail_transport_locked();
      return;
    }
    uint8_t buf[4];
    size_t n = frame_sync::PackReady(buf, sizeof(buf));
  // 2026-09-09: handle transport failure instead of silently losing reliable data.
  // channel_->Send(buf, n);
    if (!n || !channel_->Send(buf, n)) fail_transport_locked();
  }

  // Members
  asio::io_context& io_;
  udp::socket socket_;
  asio::steady_timer retransmit_timer_{io_};
  udp::endpoint server_endpoint_;
  std::string host_;
  unsigned short port_;
// 2026-09-13: guard IO execution separately from bounded receive state.
//   std::mutex mu_;
  std::mutex mu_;
  std::mutex poll_mu_;
  std::unique_ptr<frame_sync::ReliableUDPChannel> channel_;
  std::vector<uint8_t> recv_buf_;
  std::queue<std::pair<frame_sync::frame_id_t, std::vector<frame_sync::SlotInput>>> auth_queue_;
  std::vector<uint16_t> my_slots_;
  uint16_t my_slot_index_ = 0;
  uint32_t seed_ = 0;
  uint16_t left_agents_ = 0, right_agents_ = 0;
  bool ready_sent_ = false;
  std::chrono::steady_clock::time_point next_heartbeat_{};
  std::atomic<bool> running_{true};
// 2026-09-13: transport failure is visible while the owner draws.
//   bool failed_ = false;
  std::atomic<bool> failed_{false};
  size_t verified_hashes_ = 0;
  frame_sync::ReplayRecorder replay_recorder_;

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

// 2026-09-13: heartbeat reads the current frame independently of simulation.
//   frame_sync::frame_id_t current_frame_id_ = 0;
  std::atomic<frame_sync::frame_id_t> current_frame_id_{0};
  frame_sync::frame_id_t last_confirmed_frame_ = 0;
  int frames_without_packet_ = 0;
  std::unordered_map<frame_sync::frame_id_t, frame_sync::SlotInput> predicted_inputs_;

  frame_sync::ClientState client_state_;
};

// ===== Main with SDL2 rendering =====

// 2026-09-13: replaced duplicated input/render loop; retained previous implementation.
// int main(int argc, char* argv[]) {
//   if (argc < 3) {
//     fprintf(stderr,
//         "Usage: %s <host> <port> [--headless]\n"
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
//   frame_sync::MultiplayerConfig config;
//   config.host = argv[1];
//   config.port = static_cast<unsigned short>(std::stoi(argv[2]));
//   config.is_server = false;
//   config.render = true;
// 
//   for (int i = 1; i < argc; ++i) {
//     if (std::string(argv[i]) == "--headless") {
//       config.render = false;
//     }
//   }
// 
//   fprintf(stderr, "Connecting to %s:%u (render=%s)\n",
//           config.host.c_str(), config.port,
//           config.render ? "on" : "off");
// 
//   GameEnv env;
// 
//   asio::io_context io;
//   IntegratedFrameSyncClientUDP client(io, config.host, config.port, &env, config);
// 
//   if (!client.connect()) {
//     fprintf(stderr, "Failed to connect\n");
//     return 1;
//   }
// 
//   fprintf(stderr, "Connected! My slots: %zu, seed=%u\n",
//           client.my_slots().size(), client.seed());
// 
//   // Start IO thread for async receive/retransmit
//   std::thread io_thread([&io]() { io.run(); });
// 
//   // Main game loop
//   auto logic_period = std::chrono::milliseconds(1000 / config.frame_rate_hz);
//   auto render_period = std::chrono::milliseconds(1000 / config.render_rate_hz);
//   KeyboardState kb_state;
//   frame_sync::SlotInput my_input = frame_sync::SlotInput::Default();
//   bool running = true;
// 
//   int frame_count = 0;
//   auto fps_timer = std::chrono::steady_clock::now();
//   double current_fps = 0.0;
// 
//   auto last_logic_time = std::chrono::steady_clock::now();
//   auto last_render_time = std::chrono::steady_clock::now();
// 
//   // 2026-09-09: handle transport failure instead of silently losing reliable data.
//   // while (running) {
//   while (running && client.is_running()) {
//     auto now = std::chrono::steady_clock::now();
// 
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
//       const Uint8* keys = SDL_GetKeyboardState(nullptr);
//       kb_state.update(keys);
//       my_input = kb_state.to_slot_input();
//     }
// 
//     auto logic_elapsed = now - last_logic_time;
//     if (logic_elapsed >= logic_period) {
//       last_logic_time = now;
// 
//       std::vector<frame_sync::SlotInput> local_inputs(client.my_slots().size(), my_input);
//       if (!client.my_slots().empty()) {
//         client.send_frame_input(client.current_frame_id(),
//                                 client.my_slots().data(),
//                                 local_inputs.data(),
//                                 static_cast<uint16_t>(client.my_slots().size()));
//       }
// 
//       auto result = client.tick(my_input);
//       using enum IntegratedFrameSyncClientUDP::StepResult;
// 
//       switch (result) {
//         case kRollback:
//           fprintf(stderr, "Rollback at frame %u (total: %d)\n",
//                   client.current_frame_id(), client.rollback_count());
//           break;
//         default:
//           break;
//       }
// 
//       if (config.render) {
//         // 2026-09-09: public env calls no longer leave an implicit TLS selection.
//         ContextHolder render_context(&env);
//         GetGameTask()->GetMatch()->SaveInterpolationState();
//       }
//     }
// 
//     auto render_elapsed = now - last_render_time;
//     if (config.render && render_elapsed >= render_period) {
//       last_render_time = now;
// 
//       float t = static_cast<float>(std::chrono::duration<double>(now - last_logic_time).count()) /
//                 static_cast<float>(std::chrono::duration<double>(logic_period).count());
//       t = std::clamp(t, 0.0f, 1.0f);
// 
//       // 2026-09-09: select this environment for direct Match rendering calls.
//       ContextHolder render_context(&env);
//       GetGameTask()->GetMatch()->PutInterpolated(t);
//       env.render();
// 
//       frame_count++;
//       auto fps_now = std::chrono::steady_clock::now();
//       auto fps_elapsed = std::chrono::duration<double>(fps_now - fps_timer).count();
//       if (fps_elapsed >= 1.0) {
//         current_fps = frame_count / fps_elapsed;
//         frame_count = 0;
//         fps_timer = fps_now;
// 
//         char title[256];
//         snprintf(title, sizeof(title),
//                  "Football MP (UDP) | FPS: %.0f | Frame: %u | Rollbacks: %d",
//                  current_fps, client.current_frame_id(), client.rollback_count());
//         SDL_Window* win = SDL_GL_GetCurrentWindow();
//         if (win) SDL_SetWindowTitle(win, title);
//       }
// 
//       SDL_Window* win = SDL_GL_GetCurrentWindow();
//       if (win) SDL_GL_SwapWindow(win);
//     }
// 
//     auto elapsed = std::chrono::steady_clock::now() - now;
//     auto min_period = std::min(logic_period, render_period);
//     if (elapsed < min_period)
//       std::this_thread::sleep_for(min_period - elapsed);
//   }
// 
//   fprintf(stderr, "Shutting down...\n");
//   io.stop();
//   if (io_thread.joinable()) io_thread.join();
//   // 2026-09-09: distinguish lost transport from a normal user exit.
//   // return 0;
//   return client.is_running() ? 0 : 1;
// }
int main(int argc, char* argv[]) {
  try {
    const auto [config, frames] = frame_sync::NativeClientOptions(argc, argv);
    GameEnv env;
    asio::io_context io;
    IntegratedFrameSyncClientUDP client(io, config.host, config.port, &env, config);
    if (!client.connect()) {
      fprintf(stderr, "Failed to connect\n");
      return 1;
    }
    return frame_sync::RunNativeClient(env, client, config, frames, "UDP");
  } catch (const std::exception& error) {
    fprintf(stderr, "Native UDP client failed: %s\n", error.what());
    return 1;
  }
}
