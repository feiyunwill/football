#include "game_load.hpp"
// 2026-09-13: TCP and UDP share input publication, pacing and presentation.
#pragma once
// 2026-09-13: own a joined transport worker inside the window input lifetime.
// #include "frame_sync/native_loop.hpp"
#include "frame_sync/native_loop.hpp"
#include "frame_sync/native_transport_pump.hpp"
#include "frame_sync/engine_integration.hpp"
#include <charconv>
#include <cstdio>

namespace frame_sync {
inline uint32_t NativeNumber(const std::string& text, uint32_t maximum) {
  uint32_t value = 0;
  const auto parsed = std::from_chars(text.data(), text.data() + text.size(), value);
  if (parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size() || value > maximum)
    throw std::invalid_argument("Invalid numeric argument");
  return value;
}
inline std::pair<MultiplayerConfig, uint32_t> NativeClientOptions(int argc, char** argv) {
  if (argc < 3) throw std::invalid_argument(
      "usage: client host port [left right seed] [--headless] [--frames N]");
  MultiplayerConfig config;
  // 2026-09-13: native product mains explicitly select 50 Hz.
  // config.host = argv[1];
  config.native_product = true;
  config.frame_rate_hz = NativeMatchContract::kHz;
  config.host = argv[1];
  config.port = NativeNumber(argv[2], 65535);
  if (config.host.empty() || config.port == 0) throw std::invalid_argument("Host and positive port required");
  uint32_t frames = 0;
  std::vector<std::string> positional;
  for (int i = 3; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "--headless") config.render = false;
    else if (arg == "--frames" && i + 1 < argc) {
      frames = NativeNumber(argv[++i], UINT32_MAX - 1024);
      if (!frames) throw std::invalid_argument("Frame limit must be positive");
    } else if (arg.starts_with("--")) throw std::invalid_argument("Unknown or incomplete option");
    else positional.push_back(arg);
  }
  if (positional.size() > 3) throw std::invalid_argument("Too many session arguments");
  if (positional.size() > 0) config.left_agents = NativeNumber(positional[0], 11);
  if (positional.size() > 1) config.right_agents = NativeNumber(positional[1], 11);
  if (positional.size() > 2) config.seed = NativeNumber(positional[2], UINT32_MAX);
  return {config, frames};
}
template<class Client>
int RunNativeClient(GameEnv& env, Client& client, const MultiplayerConfig& config,
                    uint32_t frame_limit, const char* protocol) {
  NativeWindowInput window(env);
  // 2026-09-13: window and devices stay on the caller; game and GL share one worker.
  int result = 0;
  window.Run([&] {
   // 2026-09-14: start the cadence only after resource initialization.
   // NativeLoopClock clock(NativeNow(), config.frame_rate_hz, config.render_rate_hz);
// 2026-09-13: product transport continues during expensive UI work.
//   bool controls_paused = false, save_ok = true;
  NativeTransportPump transport([&]{ client.pump_input(window.buffer()); },config.native_product);
   // 2026-09-14: UI stays on its creator and IO stays live while this game owner loads.
   // 2026-09-14: user cancellation unwinds resources while keeping the UI runtime alive.
   // if constexpr (requires { client.initialize_on_owner(window); }) client.initialize_on_owner(window);
   try {
     if constexpr (requires { client.initialize_on_owner(window); }) client.initialize_on_owner(window);
   } catch (const GameLoadCancelled&) {
     transport.Stop();
     transport.Check();
     fprintf(stderr,"%s session confirmed=%u verified_hashes=%zu failed=%d\n",
             protocol,client.confirmed_count(),client.verified_hashes(),client.failed() ? 1 : 0);
     // 2026-09-15: receipt validation can fail during the bounded stop dispatcher.
     // result = client.failed() ? 1 : 0;
     // client.stop();
     client.stop();
     result = client.failed() ? 1 : 0;
     return;
   }
  NativeLoopClock clock(NativeNow(), config.frame_rate_hz, config.render_rate_hz);
  bool controls_paused = false, save_ok = true;
  std::string previous_connection_status;
  int pictures = 0;
  auto fps_start = NativeNow();
  // 2026-09-14: session setup may precede recovery acceptance.
  // fprintf(stderr, "Connected! My slots: %zu, seed=%u\n", client.my_slots().size(), client.seed());
  fprintf(stderr, "Session initialized! My slots: %zu, seed=%u\n", client.my_slots().size(), client.seed());
  fprintf(stderr, "Controls: WASD/arrows move; Z/X/C pass; V shoot; Shift sprint; Tab switch; "
                  "M dribble; K pause controls; P save replay; Q/Escape quit.\n");
// 2026-09-13: surface worker exceptions on the owner.
//   while (client.is_running()) {
  while (client.is_running()) {
    transport.Check();
    if (clock.PollDue(NativeNow())) {
      client.poll();
      if (!client.is_running()) break;
      // 2026-09-14: recovery keeps window events responsive and exposes an immediate status.
      if constexpr (requires { client.connection_status(); }) {
        const std::string status = client.connection_status();
        if (status != previous_connection_status) {
          previous_connection_status = status;
          const auto title = "Football Multiplayer | " + status;
          window.Title(title.c_str());
        }
      }

      window.Poll();
      const auto commands = window.buffer().TakeCommands();
      if (commands[0]) break;
      if (commands[2]) {
        controls_paused = !controls_paused;
        window.buffer().SetSuspended(controls_paused);
      }
      if (commands[1]) save_ok = client.save_replay(false) && save_ok;
    }
// 2026-09-13: immediately process another bounded authority batch after slow rendering.
//     if (clock.LogicDue(NativeNow())) {
    if (clock.LogicDue(NativeNow()) || client.has_pending_authority()) {
      client.tick_buffered(window.buffer());
      client.poll();  // publish this tick's enqueued input without waiting for another display tick
      if (!client.is_running()) break;
      if (frame_limit && client.confirmed_count() >= frame_limit) break;
    }
// 2026-09-13: catch up received authority before presenting another stale frame.
//     if (config.render && clock.RenderDue(NativeNow())) {
    if (config.render && !client.has_pending_authority() && clock.RenderDue(NativeNow())) {
// 2026-09-13: sample UI input at bounded render work opportunities.
//       client.render(NativeNow());
      window.Render([&] { client.render(NativeNow()); });
      ++pictures;
      const auto now = NativeNow();
      if (now - fps_start >= 1000000000) {
        char title[160];
        const auto fps = pictures * 1000000000.0 / double(now - fps_start);
        snprintf(title, sizeof(title), controls_paused ?
            "Football Multiplayer | Controls paused (K to resume)" : "Football Multiplayer | FPS: %.0f", fps);
        if constexpr (requires { client.connection_status(); }) {
          const std::string_view status = client.connection_status();
          if (status != "Connected")
            snprintf(title,sizeof(title),"Football Multiplayer | %s",client.connection_status());
        }

        window.Title(title);
        pictures = 0; fps_start = now;
      }
    }
    clock.Wait(true, config.render);
  }
// 2026-09-13: join before final replay save and transport close; unwinding also joins.
//   fprintf(stderr, "%s session confirmed=%u verified_hashes=%zu failed=%d\n",
  transport.Stop();
  transport.Check();
  fprintf(stderr, "%s session confirmed=%u verified_hashes=%zu failed=%d\n",
          protocol, client.confirmed_count(), client.verified_hashes(), client.failed() ? 1 : 0);
  save_ok = client.save_replay() && save_ok;
  const bool failed = client.failed();
  client.stop();
  // 2026-09-13: return only after the game worker has joined.
  // return failed || !save_ok ? 1 : 0;
  // 2026-09-15: include failures discovered while draining cancellation.
  // result = failed || !save_ok ? 1 : 0;
  result = failed || client.failed() || !save_ok ? 1 : 0;
  });
  return result;
}
}  // namespace frame_sync
