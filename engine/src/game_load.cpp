#include "game_load.hpp"
#include <stdexcept>
namespace { thread_local GameLoadScope* current_load = nullptr; }
GameLoadScope::GameLoadScope(Callback callback) : callback_(std::move(callback)) {
  if (!callback_) throw std::invalid_argument("Loading callback must not be empty");
  previous_ = std::exchange(current_load,this);
}
GameLoadScope::~GameLoadScope() { current_load = previous_; }
void GameLoadCheckpoint(std::string_view stage) {
  if (current_load) current_load->callback_(stage);
}
