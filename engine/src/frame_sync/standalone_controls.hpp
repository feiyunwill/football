// 2026-09-09: the standalone host and integration probe share real SDL lifecycle handling.
#ifndef FOOTBALL_STANDALONE_CONTROLS_HPP
#define FOOTBALL_STANDALONE_CONTROLS_HPP

#include "game_env.hpp"
#include <SDL.h>

namespace frame_sync {
inline bool HandleStandaloneEvent(GameEnv& environment, const SDL_Event& event) {
  if (event.type == SDL_QUIT ||
      (event.type == SDL_KEYDOWN && event.key.keysym.sym == SDLK_q && !event.key.repeat)) {
    environment.finish();
    return false;
  }
  if (event.type == SDL_KEYDOWN && !event.key.repeat &&
      (event.key.keysym.sym == SDLK_ESCAPE || event.key.keysym.sym == SDLK_p)) {
    if (environment.state == game_paused) environment.resume();
    else if (environment.state == game_running) environment.pause();
  }
  if (event.type == SDL_WINDOWEVENT && event.window.event == SDL_WINDOWEVENT_FOCUS_LOST &&
      environment.state == game_running)
    environment.pause();
  return true;
}
}  // namespace frame_sync
#endif
