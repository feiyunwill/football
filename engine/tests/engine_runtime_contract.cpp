// 2026-09-09: exercise production queue ownership, rendering recovery and logging.
#include "frame_sync/default_scenario.hpp"
#include "game_env.hpp"
#include "types/messagequeue.hpp"
#include "systems/graphics/rendering/interface_renderer3d.hpp"
#include <GL/gl.h>
#include <atomic>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <thread>

namespace {
size_t assertions = 0;
void Require(bool value, const char* message) {
  ++assertions;
  if (!value) throw std::runtime_error(message);
}
template<class Exception, class F> void Reject(F&& fn, const char* reason) {
  bool rejected = false;
  try { fn(); } catch (const Exception&) { rejected = true; }
  Require(rejected, reason);
}
void Queues() {
  using blunted::MessageQueue;
  Reject<std::invalid_argument>([] { MessageQueue<int> queue(0); }, "zero capacity accepted");
  Reject<std::invalid_argument>([] { MessageQueue<int> queue(65537); }, "oversized count accepted");
  Reject<std::invalid_argument>([] { MessageQueue<int> queue(2, 1); }, "insufficient storage accepted");
  Reject<std::invalid_argument>([] { MessageQueue<int> queue(2, 16777217); }, "oversized byte budget accepted");
  MessageQueue<int> queue(7, 1024);
  const size_t storage = queue.StorageBytes();
  bool available = true;
  Require(queue.GetMessage(available) == 0 && !available, "empty scalar was not initialized");
  int next = 0;
  for (int cycle = 0; cycle < 1000; ++cycle) {
    for (int i = 0; i < 7; ++i) queue.PushMessage(next + i, false);
    Reject<std::length_error>([&] { queue.PushMessage(-1); }, "full queue silently dropped an item");
    for (int i = 0; i < 3; ++i)
      Require(queue.GetMessage(available) == next++ && available, "queue reordered initial items");
    for (int i = 0; i < 3; ++i) queue.PushMessage(next + 4 + i, false);
    for (int i = 0; i < 7; ++i)
      Require(queue.GetMessage(available) == next++ && available, "ring wrap reordered items");
    Require(queue.Size() == 0 && queue.StorageBytes() == storage, "draining grew storage");
  }
  MessageQueue<std::unique_ptr<int>> owned(2);
  owned.PushMessage(std::make_unique<int>(17));
  auto value = owned.GetMessage(available);
  Require(value && *value == 17 && available && owned.Size() == 0, "move-only ownership lost");
  std::weak_ptr<int> weak;
  {
    MessageQueue<std::shared_ptr<int>> refs(2);
    auto item = std::make_shared<int>(3); weak = item;
    refs.PushMessage(item); refs.PushMessage(item);
    Require(item.use_count() == 3, "queue did not retain references");
    refs.Clear(); Require(item.use_count() == 1, "Clear retained resource references");
    refs.PushMessage(item); item.reset();
    Require(!weak.expired(), "queued ownership ended early");
  }
  Require(weak.expired(), "queue destruction retained its resources");
}
std::string Rendering() {
  GameEnv env;
  env.game_config.render = true;
  env.game_config.render_resolution_x = 320;
  env.game_config.render_resolution_y = 180;
  auto scenario = frame_sync::MakeDefaultScenario(1, 1, 42);
  env.start_game(*scenario); env.state = game_running; env.step();
  std::string renderer;
  {
    ContextHolder guard(&env);
    renderer = reinterpret_cast<const char*>(glGetString(GL_RENDERER));
    auto& queue = env.context->graphicsSystem.GetOverlay2DQueue();
    Require(queue.Size() == 0, "normal render left queued textures");
    env.context->scene2D->PokeObjects(blunted::e_ObjectType_Image2D, blunted::e_SystemType_Graphics);
    Require(queue.Size() > 0, "actual HUD did not produce overlay commands");
    bool available = false;
    auto entry = queue.GetMessage(available);
    Require(available && entry.texture, "actual HUD command has no texture");
    queue.Clear();
    const auto refs = entry.texture->GetRefCount();
    const auto storage = queue.StorageBytes();
    Require(queue.Capacity() == 4096 && storage <= 1024 * 1024, "production queue is not bounded");
    const auto digest = env.get_state_digest();
    for (int cycle = 0; cycle < 4; ++cycle) {
      for (size_t i = 0; i < queue.Capacity(); ++i) queue.PushMessage(entry, false);
      Require(entry.texture->GetRefCount() == refs + queue.Capacity(), "actual texture references were not queued");
      const auto tracker_nesting = env.context->tracker_disabled;
      Reject<std::length_error>([&] { env.render(); }, "actual HUD overflow did not fail rendering");
      Require(queue.Size() == 0 && queue.StorageBytes() == storage, "failed render retained its queue");
      Require(entry.texture->GetRefCount() == refs, "failed render leaked actual texture ownership");
      Require(env.context->tracker_disabled == tracker_nesting, "render exception unbalanced tracker nesting");
      Require(env.get_state_digest() == digest, "failed render changed logical match state");
      env.render();
      Require(queue.Size() == 0 && env.get_state_digest() == digest, "next render did not recover cleanly");
      Require(glGetError() == GL_NO_ERROR, "render recovery produced GL errors");
    }
  }
  Require(GetGame() == nullptr, "render contract leaked TLS context");
  auto pixels = env.get_frame();
  Require(pixels.size() == 320 * 180 * 3, "recovered frame dimensions changed");
  size_t different = 0;
  for (size_t offset = 3; offset < pixels.size(); offset += 3)
    different += pixels.compare(offset, 3, pixels, 0, 3) != 0;
  Require(different > 100, "recovered image is blank");
  return renderer;
}
void Logs() {
  std::vector<std::jthread> threads;
  for (int worker = 0; worker < 8; ++worker)
    threads.emplace_back([worker] {
      for (int line = 0; line < 64; ++line)
        blunted::Log(blunted::e_Warning, "runtime_contract", "concurrent",
                     "worker=" + std::to_string(worker) + " record=" + std::to_string(line));
    });
  threads.clear();
  blunted::Log(blunted::e_Error, std::string(1024, 'C'), std::string(1024, 'M'), std::string(8 * 1024 * 1024, 'X'));
  blunted::Log(blunted::e_Error, "runtime_contract", "newline", "one\ntwo\rthree");
}
}
int main(int argc, char** argv) {
  try {
    if (argc == 2 && std::string(argv[1]) == "--fatal") {
      blunted::Log(blunted::e_FatalError, "runtime_contract", "fatal", "intentional fatal termination");
      return 9;
    }
    if (argc == 2 && std::string(argv[1]) == "--logs") { Logs(); return 0; }
    Queues();
    std::string renderer;
    if (argc == 2 && std::string(argv[1]) == "--render") renderer = Rendering();
    std::cout << "{\"passed\":true,\"assertions\":" << assertions
              << ",\"skipped\":0,\"renderer\":\"" << renderer << "\"}" << std::endl;
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "runtime contract failed: " << error.what() << std::endl;
    return 1;
  }
}
