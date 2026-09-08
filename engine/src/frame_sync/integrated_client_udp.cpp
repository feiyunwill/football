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
#include "game_env.hpp"
#include "main.hpp"
#include "gfootball_actions.h"

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
    engine_ = frame_sync::MakeGameEnvCallbacks(env);
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
    uint8_t connect_byte = std::to_underlying(frame_sync::MessageType::Connect);
    socket_.send_to(asio::buffer(&connect_byte, 1), server_endpoint_, 0, ec);
    if (ec) { fprintf(stderr, "Connect send failed: %s\n", ec.message().c_str()); return false; }

    do_receive();
    do_retransmit_timer();

    // Wait for SessionStart + SlotAssignment and send Ready (with timeout)
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (!ready_sent_ && std::chrono::steady_clock::now() < deadline) {
      io_.run_one();
      std::lock_guard<std::mutex> lock(mu_);
      while (recv_buf_.size() >= 1u + frame_sync::SESSION_START_PARAMS_BYTES &&
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
        size_t need = 3 + num * 2;
        if (recv_buf_.size() >= need) {
          my_slots_.resize(num);
          for (uint16_t i = 0; i < num; ++i)
            memcpy(&my_slots_[i], recv_buf_.data() + 3 + i * 2, 2);
          recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + static_cast<std::ptrdiff_t>(need));
          send_ready();
          ready_sent_ = true;
          break;
        }
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    if (!ready_sent_) {
      fprintf(stderr, "Timeout waiting for SessionStart/SlotAssignment\n");
      return false;
    }
    // 2026-09-01: 握手成功后初始化 GameEnv，否则 tick() 中 get_state() 会因
    // context=nullptr crash（之前缺失此步骤导致 Segfault）。
    init_game_env();
    return true;
  }

  enum class StepResult {
    kNormal,
    kWaitForAuthority,
    kRollback,
    kCatchup,
  };

  StepResult tick(const frame_sync::SlotInput& my_input) {
    int frames_to_process = client_state_.catchup_count(
        last_confirmed_frame_, current_frame_id_);
    if (frames_to_process < 0) {
      return StepResult::kWaitForAuthority;
    }
    if (frames_to_process == 0) frames_to_process = 1;

    auto lag = current_frame_id_ - last_confirmed_frame_;
    if (lag >= static_cast<frame_sync::frame_id_t>(
            frame_sync::MAX_PREDICT_AHEAD_FRAMES)) {
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
      frames_without_packet_ = 0;
    }

    auto now = std::chrono::steady_clock::now();
    double now_ms = std::chrono::duration<double, std::milli>(
        now.time_since_epoch()).count();
    client_state_.record_frame_arrival(now_ms);
    client_state_.evict_old(current_frame_id_);

    return result;
  }

  void send_frame_input(frame_sync::frame_id_t frame_id,
                        const uint16_t* slot_indices,
                        const frame_sync::SlotInput* inputs,
                        uint16_t num_slots) {
    std::lock_guard<std::mutex> lock(mu_);
    if (!channel_) return;
    std::vector<uint8_t> buf(256);
    size_t n = frame_sync::PackClientFrameInput(
        frame_id, slot_indices, inputs, num_slots, buf.data(), buf.size());
    if (n) channel_->Send(buf.data(), n);
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

 private:
  void init_game_env() {
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

  void do_receive() {
    if (!running_) return;
    auto buf = std::make_shared<std::vector<uint8_t>>(4096);
    auto sender = std::make_shared<udp::endpoint>();
    socket_.async_receive_from(
        asio::buffer(*buf), *sender,
        [this, buf, sender](boost::system::error_code ec, std::size_t length) {
          if (ec) { do_receive(); return; }
          std::lock_guard<std::mutex> lock(mu_);
          if (!channel_) {
            channel_ = std::make_unique<frame_sync::ReliableUDPChannel>(
                socket_, *sender,
                [this](const uint8_t* d, size_t n) {
                  recv_buf_.insert(recv_buf_.end(), d, d + n);
                  while (parse_one_message()) {}
                });
          }
          if (channel_) channel_->HandleReceived(buf->data(), length);
          do_receive();
        });
  }

  void do_retransmit_timer() {
    retransmit_timer_.expires_after(std::chrono::milliseconds(20));
    retransmit_timer_.async_wait([this](boost::system::error_code ec) {
      if (ec || !running_) return;
      std::lock_guard<std::mutex> lock(mu_);
      if (channel_) channel_->TickRetransmit();
      do_retransmit_timer();
    });
  }

  bool parse_one_message() {
    if (recv_buf_.empty()) return false;
    uint8_t type = recv_buf_[0];

    // 2026-09-01: 连接阶段的消息由 connect() 直接解析，此处跳过避免吞掉。
    if (type == std::to_underlying(frame_sync::MessageType::SessionStart) ||
        type == std::to_underlying(frame_sync::MessageType::SlotAssignment) ||
        type == std::to_underlying(frame_sync::MessageType::Connect)) {
      return false;  // 让 connect() 处理
    }

    if (type == std::to_underlying(frame_sync::MessageType::AuthoritativeFrame)) {
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

    if (type == std::to_underlying(frame_sync::MessageType::StateHash)) {
      if (recv_buf_.size() < frame_sync::STATE_HASH_PACK_BYTES) return false;
      frame_sync::frame_id_t fid;
      uint64_t hash;
      size_t used = frame_sync::UnpackStateHash(
          recv_buf_.data(), recv_buf_.size(), &fid, &hash);
      if (used == 0) return false;
      client_state_.record_server_hash(fid, hash);
      recv_buf_.erase(recv_buf_.begin(), recv_buf_.begin() + used);
      return true;
    }

    recv_buf_.erase(recv_buf_.begin());
    return true;
  }

  void send_ready() {
    if (!channel_) return;
    uint8_t buf[4];
    size_t n = frame_sync::PackReady(buf, sizeof(buf));
    channel_->Send(buf, n);
  }

  // Members
  asio::io_context& io_;
  udp::socket socket_;
  asio::steady_timer retransmit_timer_{io_};
  udp::endpoint server_endpoint_;
  std::string host_;
  unsigned short port_;
  std::mutex mu_;
  std::unique_ptr<frame_sync::ReliableUDPChannel> channel_;
  std::vector<uint8_t> recv_buf_;
  std::queue<std::pair<frame_sync::frame_id_t, std::vector<frame_sync::SlotInput>>> auth_queue_;
  std::vector<uint16_t> my_slots_;
  uint16_t my_slot_index_ = 0;
  uint32_t seed_ = 0;
  uint16_t left_agents_ = 0, right_agents_ = 0;
  bool ready_sent_ = false;
  std::atomic<bool> running_{true};

  GameEnv* env_;
  frame_sync::MultiplayerConfig config_;
  frame_sync::EngineCallbacks engine_;

  frame_sync::frame_id_t current_frame_id_ = 0;
  frame_sync::frame_id_t last_confirmed_frame_ = 0;
  int frames_without_packet_ = 0;
  std::unordered_map<frame_sync::frame_id_t, frame_sync::SlotInput> predicted_inputs_;

  frame_sync::ClientState client_state_;
};

// ===== Main with SDL2 rendering =====

int main(int argc, char* argv[]) {
  if (argc < 3) {
    fprintf(stderr,
        "Usage: %s <host> <port> [--headless]\n"
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
  config.is_server = false;
  config.render = true;

  for (int i = 1; i < argc; ++i) {
    if (std::string(argv[i]) == "--headless") {
      config.render = false;
    }
  }

  fprintf(stderr, "Connecting to %s:%u (render=%s)\n",
          config.host.c_str(), config.port,
          config.render ? "on" : "off");

  GameEnv env;

  asio::io_context io;
  IntegratedFrameSyncClientUDP client(io, config.host, config.port, &env, config);

  if (!client.connect()) {
    fprintf(stderr, "Failed to connect\n");
    return 1;
  }

  fprintf(stderr, "Connected! My slots: %zu, seed=%u\n",
          client.my_slots().size(), client.seed());

  // Start IO thread for async receive/retransmit
  std::thread io_thread([&io]() { io.run(); });

  // Main game loop
  auto logic_period = std::chrono::milliseconds(1000 / config.frame_rate_hz);
  auto render_period = std::chrono::milliseconds(1000 / config.render_rate_hz);
  KeyboardState kb_state;
  frame_sync::SlotInput my_input = frame_sync::SlotInput::Default();
  bool running = true;

  int frame_count = 0;
  auto fps_timer = std::chrono::steady_clock::now();
  double current_fps = 0.0;

  auto last_logic_time = std::chrono::steady_clock::now();
  auto last_render_time = std::chrono::steady_clock::now();

  while (running) {
    auto now = std::chrono::steady_clock::now();

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

      const Uint8* keys = SDL_GetKeyboardState(nullptr);
      kb_state.update(keys);
      my_input = kb_state.to_slot_input();
    }

    auto logic_elapsed = now - last_logic_time;
    if (logic_elapsed >= logic_period) {
      last_logic_time = now;

      if (!client.my_slots().empty()) {
        client.send_frame_input(client.current_frame_id(),
                                client.my_slots().data(),
                                &my_input,
                                static_cast<uint16_t>(client.my_slots().size()));
      }

      auto result = client.tick(my_input);
      using enum IntegratedFrameSyncClientUDP::StepResult;

      switch (result) {
        case kRollback:
          fprintf(stderr, "Rollback at frame %u (total: %d)\n",
                  client.current_frame_id(), client.rollback_count());
          break;
        default:
          break;
      }

      if (config.render) {
        GetGameTask()->GetMatch()->SaveInterpolationState();
      }
    }

    auto render_elapsed = now - last_render_time;
    if (config.render && render_elapsed >= render_period) {
      last_render_time = now;

      float t = static_cast<float>(std::chrono::duration<double>(render_elapsed).count()) /
                static_cast<float>(std::chrono::duration<double>(logic_period).count());
      t = std::clamp(t, 0.0f, 1.0f);

      GetGameTask()->GetMatch()->PutInterpolated(t);
      env.render();

      frame_count++;
      auto fps_now = std::chrono::steady_clock::now();
      auto fps_elapsed = std::chrono::duration<double>(fps_now - fps_timer).count();
      if (fps_elapsed >= 1.0) {
        current_fps = frame_count / fps_elapsed;
        frame_count = 0;
        fps_timer = fps_now;

        char title[256];
        snprintf(title, sizeof(title),
                 "Football MP (UDP) | FPS: %.0f | Frame: %u | Rollbacks: %d",
                 current_fps, client.current_frame_id(), client.rollback_count());
        SDL_Window* win = SDL_GL_GetCurrentWindow();
        if (win) SDL_SetWindowTitle(win, title);
      }

      SDL_Window* win = SDL_GL_GetCurrentWindow();
      if (win) SDL_GL_SwapWindow(win);
    }

    auto elapsed = std::chrono::steady_clock::now() - now;
    auto min_period = std::min(logic_period, render_period);
    if (elapsed < min_period)
      std::this_thread::sleep_for(min_period - elapsed);
  }

  fprintf(stderr, "Shutting down...\n");
  io.stop();
  if (io_thread.joinable()) io_thread.join();
  return 0;
}
