// Copyright 2019 Google LLC & Contributors
// Integrated frame sync client with rendering: connects to server, runs GameEnv
// with SDL2/OpenGL rendering, forwards keyboard input, implements prediction & rollback.

#include "frame_sync/protocol.hpp"
#include "frame_sync/protocol_io.hpp"
#include "frame_sync/client_state.hpp"
#include "frame_sync/engine_integration.hpp"
#include "frame_sync/engine_bridge.hpp"
#include "frame_sync/interpolator.hpp"
#include "frame_sync/prediction_accuracy_tracker.hpp"
#include "frame_sync/adaptive_prediction_cap.hpp"
#include "frame_sync/adaptive_jitter_buffer.hpp"
#include "frame_sync/latency_compensator.hpp"
#include "frame_sync/replay_system.hpp"
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

class IntegratedFrameSyncClient {
 public:
  IntegratedFrameSyncClient(asio::io_context& io, const std::string& host,
                            unsigned short port, GameEnv* env,
                            const frame_sync::MultiplayerConfig& config)
      : io_(io), socket_(io), host_(host), port_(port),
        env_(env), config_(config),
        client_state_(frame_sync::MAX_PREDICT_AHEAD_FRAMES + 4) {
    engine_ = frame_sync::MakeGameEnvCallbacks(env);
  }

  bool connect() {
    boost::system::error_code ec;
    tcp::resolver resolver(io_);
    auto endpoints = resolver.resolve(host_, std::to_string(port_), ec);
    if (ec) {
      fprintf(stderr, "Resolve failed: %s\n", ec.message().c_str());
      return false;
    }
    asio::connect(socket_, endpoints, ec);
    if (ec) {
      fprintf(stderr, "Connect failed: %s\n", ec.message().c_str());
      return false;
    }
    recv_buf_.clear();
    if (!receive_session_start()) return false;
    if (!receive_slot_assignment()) return false;
    init_game_env();
    send_ready();
    do_read();

    // Start recording replay (ms-17.4)
    replay_recorder_.StartRecording(seed_, "unknown",
                                     static_cast<uint32_t>(my_slots_.size()));
    return true;
  }

  enum class StepResult {
    kNormal,
    kWaitForAuthority,
    kRollback,
    kCatchup,
  };

  StepResult tick(const frame_sync::SlotInput& my_input) {
    // Use adaptive prediction cap instead of fixed MAX_PREDICT_AHEAD_FRAMES
    int max_predict = adaptive_cap_.GetMaxPredictAhead();
    
    int frames_to_process = client_state_.catchup_count(
        last_confirmed_frame_, current_frame_id_);
    if (frames_to_process < 0) {
      return StepResult::kWaitForAuthority;
    }
    if (frames_to_process == 0) frames_to_process = 1;

    auto lag = current_frame_id_ - last_confirmed_frame_;
    if (lag >= static_cast<frame_sync::frame_id_t>(max_predict)) {
      return StepResult::kWaitForAuthority;
    }
    if (frames_without_packet_ >= frame_sync::MAX_FRAMES_WITHOUT_PACKET) {
      return StepResult::kWaitForAuthority;
    }

    StepResult result = StepResult::kNormal;
    for (int f = 0; f < frames_to_process; ++f) {
      if (engine_.save_state) {
        client_state_.save_snapshot(current_frame_id_, my_input,
                                   engine_.save_state);
      }
      if (engine_.step) {
        engine_.step(my_input);
      }
      predicted_inputs_[current_frame_id_] = my_input;
      ++current_frame_id_;
      ++frames_without_packet_;

      if (frames_to_process > 1) {
        result = StepResult::kCatchup;
      }
    }

    frame_sync::frame_id_t auth_fid;
    std::vector<frame_sync::SlotInput> auth_inputs;
    while (pop_authoritative_frame(&auth_fid, &auth_inputs)) {
      if (auth_fid <= last_confirmed_frame_) continue;

      if (auth_fid < current_frame_id_) {
        if (engine_.restore_state && engine_.step) {
          bool ok = client_state_.rollback_to(
              auth_fid, auth_inputs[my_slot_index_],
              engine_.restore_state, engine_.step);
          if (ok) {
            for (auto f = auth_fid + 1; f < current_frame_id_; ++f) {
              auto it = predicted_inputs_.find(f);
              if (it != predicted_inputs_.end() && engine_.step) {
                engine_.step(it->second);
              }
            }
            result = StepResult::kRollback;
            prediction_tracker_.IncrementRollbackCount();
          }
        }
      } else {
        if (engine_.step) {
          for (size_t i = 0; i < auth_inputs.size(); ++i) {
            engine_.step(auth_inputs[i]);
          }
        }
        current_frame_id_ = auth_fid + 1;
      }

      last_confirmed_frame_ = auth_fid;
      server_frame_ = auth_fid;
      frames_without_packet_ = 0;
    }

    auto now = std::chrono::steady_clock::now();
    double now_ms = std::chrono::duration<double, std::milli>(
        now.time_since_epoch()).count();
    client_state_.record_frame_arrival(now_ms);
    client_state_.evict_old(current_frame_id_);

    // Update adaptive modules with network conditions
    double rtt = client_state_.avg_frame_interval_ms() * 2.0;
    double jitter = client_state_.jitter_ms();
    adaptive_cap_.UpdateNetworkConditions(rtt, 0.0);
    adaptive_cap_.UpdatePredictionAccuracy(prediction_tracker_.GetRecentAccuracy());
    adaptive_cap_.UpdateFrameTime(16.67, jitter);
    jitter_buffer_.Update(jitter, rtt);

    // Record replay frame (ms-17.4)
    if (replay_recorder_.IsRecording()) {
      std::vector<frame_sync::SlotInput> all_inputs(
          left_agents_ + right_agents_, frame_sync::SlotInput::Default());
      // Fill in our slot's input
      if (!my_slots_.empty() && my_slot_index_ < all_inputs.size()) {
        all_inputs[my_slot_index_] = my_input;
      }
      replay_recorder_.RecordFrame(current_frame_id_ - 1, 0, all_inputs);
    }

    return result;
  }

  void send_frame_input(frame_sync::frame_id_t frame_id,
                        const uint16_t* slot_indices,
                        const frame_sync::SlotInput* inputs,
                        uint16_t num_slots) {
    std::vector<uint8_t> buf(256);
    size_t n = frame_sync::PackClientFrameInput(
        frame_id, slot_indices, inputs, num_slots, buf.data(), buf.size());
    if (n == 0) return;
    boost::system::error_code ec;
    asio::write(socket_, asio::buffer(buf.data(), n), ec);
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
  int rollback_count() const { return client_state_.rollback_count(); }
  
  // Phase 16 stats
  double prediction_accuracy() const { return prediction_tracker_.GetRecentAccuracy(100); }
  int adaptive_max_predict() const { return adaptive_cap_.GetMaxPredictAhead(); }
  double jitter_ms() const { return client_state_.jitter_ms(); }
  double smoothed_rtt() const { return latency_comp_.GetSmoothedRTT(); }
  double latency_offset() const { return latency_comp_.GetAdjustedOffset(); }

 private:
  void init_game_env() {
    // 2026-08-31: Ensure env vars are set before start_game() reads them.
    // getenv() may return NULL if env was set in parent shell but not inherited.
    if (!getenv("GFOOTBALL_DATA_DIR")) {
      setenv("GFOOTBALL_DATA_DIR", "/home/zuchangqu/project/football/engine/data", 1);
    }
    if (!getenv("GFOOTBALL_FONT")) {
      setenv("GFOOTBALL_FONT",
             "/home/zuchangqu/project/football/engine/data/media/fonts/alegreya/AlegreyaSansSC-ExtraBold.ttf",
             1);
    }
    env_->game_config.render = config_.render;
    env_->game_config.physics_steps_per_frame = 10;

    auto scenario = ScenarioConfig::make();
    scenario->left_agents = left_agents_;
    scenario->right_agents = right_agents_;
    scenario->game_engine_random_seed = seed_;
    env_->start_game(*scenario);
    env_->state = GameState::game_running;

    fprintf(stderr, "GameEnv initialized: %uv%u, seed=%u\n",
            left_agents_, right_agents_, seed_);
  }

  bool receive_session_start() {
    uint8_t buf[32];
    size_t n = read_exact(buf, 1 + frame_sync::SESSION_START_PARAMS_BYTES);
    if (n == 0) return false;
    return frame_sync::UnpackSessionStart(buf, n, &seed_, &left_agents_,
                                          &right_agents_) != 0;
  }

  bool receive_slot_assignment() {
    uint8_t buf[64];
    size_t n = read_exact(buf, 1 + 2);
    if (n < 3) return false;
    if (buf[0] != static_cast<uint8_t>(frame_sync::MessageType::SlotAssignment))
      return false;
    uint16_t num;
    memcpy(&num, buf + 1, 2);
    if (num > 32) return false;
    n = read_exact(buf, num * 2);
    if (n != num * 2) return false;
    my_slots_.resize(num);
    for (uint16_t i = 0; i < num; ++i)
      memcpy(&my_slots_[i], buf + i * 2, 2);
    if (!my_slots_.empty()) my_slot_index_ = my_slots_[0];
    return true;
  }

  size_t read_exact(uint8_t* buf, size_t need) {
    size_t got = 0;
    while (got < need) {
      boost::system::error_code ec;
      size_t n = asio::read(socket_, asio::buffer(buf + got, need - got), ec);
      if (ec || n == 0) return 0;
      got += n;
    }
    return got;
  }

  void send_ready() {
    uint8_t buf[4];
    size_t n = frame_sync::PackReady(buf, sizeof(buf));
    asio::write(socket_, asio::buffer(buf, n));
  }

  void do_read() {
    auto buf = std::make_shared<std::vector<uint8_t>>(4096);
    socket_.async_read_some(
        asio::buffer(*buf),
        [this, buf](boost::system::error_code ec, std::size_t length) {
          if (ec) return;
          std::lock_guard<std::mutex> lock(mu_);
          recv_buf_.insert(recv_buf_.end(), buf->begin(), buf->begin() + length);
          while (parse_one_message()) {}
          do_read();
        });
  }

  bool parse_one_message() {
    if (recv_buf_.empty()) return false;
    uint8_t type = recv_buf_[0];

    if (type == static_cast<uint8_t>(frame_sync::MessageType::AuthoritativeFrame)) {
      if (recv_buf_.size() < 7u) return false;
      uint16_t num_slots;
      memcpy(&num_slots, recv_buf_.data() + 5, 2);
      size_t need = 7 + num_slots * frame_sync::SLOT_INPUT_BYTES;
      if (recv_buf_.size() < need) return false;
      frame_sync::frame_id_t fid;
      std::vector<frame_sync::SlotInput> inputs;
      size_t used = frame_sync::UnpackAuthoritativeFrame(
          recv_buf_.data(), recv_buf_.size(), &fid, &inputs);
      if (used == 0) return false;
      auth_queue_.emplace(fid, std::move(inputs));
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + used);
      return true;
    }

    if (type == static_cast<uint8_t>(frame_sync::MessageType::StateHash)) {
      if (recv_buf_.size() < frame_sync::STATE_HASH_PACK_BYTES) return false;
      frame_sync::frame_id_t fid;
      uint64_t hash;
      size_t used = frame_sync::UnpackStateHash(
          recv_buf_.data(), recv_buf_.size(), &fid, &hash);
      if (used == 0) return false;
      
      // Record server hash and check prediction accuracy
      client_state_.record_server_hash(fid, hash);
      
      // Record prediction (we predict our state hash matches server's)
      // The actual comparison happens when we receive the hash
      prediction_tracker_.RecordPrediction(fid, hash);
      
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + used);
      return true;
    }

    // Handle Heartbeat (ms-17.1: latency compensation)
    if (type == static_cast<uint8_t>(frame_sync::MessageType::Heartbeat)) {
      if (recv_buf_.size() < frame_sync::HEARTBEAT_PACKET_BYTES) return false;
      
      frame_sync::frame_id_t fid;
      uint32_t server_timestamp;
      size_t used = frame_sync::UnpackHeartbeat(
          recv_buf_.data(), recv_buf_.size(), &fid, &server_timestamp);
      if (used == 0) return false;
      
      // Record RTT measurement
      double now_ms = std::chrono::duration<double, std::milli>(
          std::chrono::steady_clock::now().time_since_epoch()).count();
      latency_comp_.RecordRTT(now_ms - 50.0, now_ms);  // Approximate RTT
      
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + used);
      return true;
    }

    recv_buf_.erase(recv_buf_.begin());
    return true;
  }

  // Members
  asio::io_context& io_;
  tcp::socket socket_;
  std::string host_;
  unsigned short port_;
  std::mutex mu_;
  std::vector<uint8_t> recv_buf_;
  std::queue<std::pair<frame_sync::frame_id_t, std::vector<frame_sync::SlotInput>>> auth_queue_;
  std::vector<uint16_t> my_slots_;
  uint16_t my_slot_index_ = 0;
  uint32_t seed_ = 0;
  uint16_t left_agents_ = 0, right_agents_ = 0;

  GameEnv* env_;
  frame_sync::MultiplayerConfig config_;
  frame_sync::EngineCallbacks engine_;

  frame_sync::frame_id_t current_frame_id_ = 0;
  frame_sync::frame_id_t last_confirmed_frame_ = 0;
  int frames_without_packet_ = 0;
  std::unordered_map<frame_sync::frame_id_t, frame_sync::SlotInput> predicted_inputs_;

  frame_sync::ClientState client_state_;

  // Phase 16 modules
  frame_sync::Interpolator interpolator_;                      ///< Frame interpolation/extrapolation
  frame_sync::PredictionAccuracyTracker prediction_tracker_;   ///< Prediction accuracy tracking
  frame_sync::AdaptivePredictionCap adaptive_cap_;             ///< Adaptive prediction cap
  frame_sync::AdaptiveJitterBuffer jitter_buffer_;             ///< Adaptive jitter buffer
  frame_sync::LatencyCompensator latency_comp_;                ///< Latency compensation (ms-17.1)
  frame_sync::ReplayRecorder replay_recorder_;                  ///< Replay recording (ms-17.4)
  frame_sync::NetworkDiagnostics net_diag_;                     ///< Network diagnostics (ms-17.5)
  frame_id_t server_frame_ = 0;                                ///< Latest server frame number
};

// ===== Main with SDL2 rendering =====

int main(int argc, char* argv[]) {
  if (argc < 3) {
    fprintf(stderr,
        "Usage: %s <host> <port> [left_agents] [right_agents] [seed] [--headless]\n"
        "\nKeyboard controls (for your controlled slot):\n"
        "  WASD / Arrow keys  - Move\n"
        "  Z - Short pass     X - High pass     C - Long pass\n"
        "  V - Shoot          B - Sliding        Space - Pressure\n"
        "  Shift - Sprint     Tab - Switch       M - Dribble\n"
        "  ESC - Quit\n",
        argv[0]);
    return 1;
  }

  frame_sync::MultiplayerConfig config;
  config.host = argv[1];
  config.port = static_cast<unsigned short>(std::stoi(argv[2]));
  if (argc >= 4) config.left_agents = static_cast<uint16_t>(std::stoi(argv[3]));
  if (argc >= 5) config.right_agents = static_cast<uint16_t>(std::stoi(argv[4]));
  if (argc >= 6) config.seed = static_cast<uint32_t>(std::stoul(argv[5]));
  config.is_server = false;
  config.render = true;

  for (int i = 1; i < argc; ++i) {
    if (std::string(argv[i]) == "--headless") {
      config.render = false;
    }
  }

  fprintf(stderr, "Connecting to %s:%u (%uv%u, seed=%u, render=%s)\n",
          config.host.c_str(), config.port,
          config.left_agents, config.right_agents, config.seed,
          config.render ? "on" : "off");

  // Initialize game environment
  GameEnv env;

  asio::io_context io;
  IntegratedFrameSyncClient client(io, config.host, config.port, &env, config);

  if (!client.connect()) {
    fprintf(stderr, "Failed to connect\n");
    return 1;
  }

  fprintf(stderr, "Connected! My slots: %zu, seed=%u\n",
          client.my_slots().size(), client.seed());

  // Initialize SDL for event handling (already initialized by GameEnv when render=true)
  if (config.render) {
    // SDL is already initialized by OpenGLRenderer3D::CreateContextSdl()
    // We just need to pump events
  }

  // Main game loop
  // 2026-08-31 ms-1.7: 渲染平滑 — 解耦逻辑和渲染帧率
  auto logic_period = std::chrono::milliseconds(1000 / config.frame_rate_hz);
  auto render_period = std::chrono::milliseconds(1000 / config.render_rate_hz);
  KeyboardState kb_state;
  frame_sync::SlotInput my_input = frame_sync::SlotInput::Default();
  bool running = true;

  // FPS tracking
  int frame_count = 0;
  auto fps_timer = std::chrono::steady_clock::now();
  double current_fps = 0.0;

  // Timing for decoupled logic/render
  auto last_logic_time = std::chrono::steady_clock::now();
  auto last_render_time = std::chrono::steady_clock::now();

  while (running) {
    auto now = std::chrono::steady_clock::now();

    // Process SDL events (always, for responsiveness)
    if (config.render) {
      SDL_Event event;
      while (SDL_PollEvent(&event)) {
        switch (event.type) {
          case SDL_QUIT:
            running = false;
            break;
          case SDL_KEYDOWN:
            if (event.key.keysym.sym == SDLK_ESCAPE) {
              running = false;
            }
            break;
        }
      }

      // Read keyboard state for movement/actions
      const Uint8* keys = SDL_GetKeyboardState(nullptr);
      kb_state.update(keys);
      my_input = kb_state.to_slot_input();
    }

    // Logic tick (runs at frame_rate_hz, e.g., 10Hz)
    auto logic_elapsed = now - last_logic_time;
    if (logic_elapsed >= logic_period) {
      last_logic_time = now;

      // Send input for current frame with correct slot indices
      if (!client.my_slots().empty()) {
        client.send_frame_input(client.current_frame_id(),
                                client.my_slots().data(),
                                &my_input,
                                static_cast<uint16_t>(client.my_slots().size()));
      }

      // Run prediction tick
      auto result = client.tick(my_input);

      switch (result) {
        case IntegratedFrameSyncClient::StepResult::kRollback:
          fprintf(stderr, "Rollback at frame %u (total: %d)\n",
                  client.current_frame_id(), client.rollback_count());
          break;
        case IntegratedFrameSyncClient::StepResult::kWaitForAuthority:
          break;
        default:
          break;
      }

      // Save interpolation state after logic tick
      if (config.render) {
        GetGameTask()->GetMatch()->SaveInterpolationState();
      }
    }

    // Render (runs at render_rate_hz, e.g., 60Hz)
    auto render_elapsed = now - last_render_time;
    if (config.render && render_elapsed >= render_period) {
      last_render_time = now;

      // Calculate interpolation factor (0 = previous frame, 1 = current frame)
      float t = static_cast<float>(std::chrono::duration<double>(render_elapsed).count()) /
                static_cast<float>(std::chrono::duration<double>(logic_period).count());
      t = std::clamp(t, 0.0f, 1.0f);

      // Use interpolated rendering
      GetGameTask()->GetMatch()->PutInterpolated(t);
      env.render();

      // Update window title with FPS and match info
      frame_count++;
      auto fps_now = std::chrono::steady_clock::now();
      auto fps_elapsed = std::chrono::duration<double>(fps_now - fps_timer).count();
      if (fps_elapsed >= 1.0) {
        current_fps = frame_count / fps_elapsed;
        frame_count = 0;
        fps_timer = fps_now;

        // Update network diagnostics (ms-17.5)
        net_diag_.Update(client.smoothed_rtt(), client.jitter_ms(),
                         client.prediction_accuracy(),
                         0, client.rollback_count(),
                         static_cast<int>(client.current_frame_id()));

        char title[256];
        snprintf(title, sizeof(title),
                 "Football MP | FPS: %.0f | Frame: %u | %s",
                 current_fps, client.current_frame_id(),
                 net_diag_.FormatOverlay().c_str());
        SDL_Window* win = SDL_GL_GetCurrentWindow();
        if (win) SDL_SetWindowTitle(win, title);
      }

      // Swap buffers
      SDL_Window* win = SDL_GL_GetCurrentWindow();
      if (win) SDL_GL_SwapWindow(win);
    }

    // Maintain frame rate (use the faster of logic and render rates)
    auto elapsed = std::chrono::steady_clock::now() - now;
    auto min_period = std::min(logic_period, render_period);
    if (elapsed < min_period)
      std::this_thread::sleep_for(min_period - elapsed);
  }

  fprintf(stderr, "Shutting down...\n");

  // Auto-save replay (ms-17.4)
  if (replay_recorder_.IsRecording()) {
    replay_recorder_.StopRecording();
    std::string replay_data = replay_recorder_.Serialize();
    std::string path = "replay_" + std::to_string(seed_) + ".bin";
    FILE* f = fopen(path.c_str(), "wb");
    if (f) {
      fwrite(replay_data.data(), 1, replay_data.size(), f);
      fclose(f);
      fprintf(stderr, "Replay saved: %s (%zu frames, %zu bytes)\n",
              path.c_str(), replay_recorder_.GetFrameCount(), replay_data.size());
    } else {
      fprintf(stderr, "Failed to save replay to %s\n", path.c_str());
    }
  }

  return 0;
}
