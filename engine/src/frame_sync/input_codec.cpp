// Copyright 2019 Google LLC & Contributors
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "input_codec.hpp"
#include "../ai/ai_keyboard.hpp"
#include "../defines.hpp"
#include "../base/math/vector3.hpp"
#include <cstring>
#include <algorithm>
#include <array>
#include <stdexcept>

namespace frame_sync {

int SlotIndexToControllerIndex(int slot_index, int left_agents, int right_agents) {
  // 2026-09-09: do not map invalid bank sizes/slots into arbitrary controllers.
  if (left_agents < 0 || right_agents < 0 || left_agents > MAX_PLAYERS || right_agents > MAX_PLAYERS ||
      slot_index < 0 || slot_index >= left_agents + right_agents)
    throw std::out_of_range("Invalid frame input controller slot");
  if (slot_index < left_agents) {
    return slot_index;
  }
  return MAX_PLAYERS + (slot_index - left_agents);
}

size_t EncodeFrameInput(const std::vector<AIControlledKeyboard*>& controllers,
                        int left_agents,
                        int right_agents,
                        void* buffer,
                        size_t buffer_size) {
  // 2026-09-09: validate before summing caller-provided counts or indexing banks.
  // const int num_slots = left_agents + right_agents;
  if (left_agents < 0 || right_agents < 0 || left_agents > MAX_PLAYERS || right_agents > MAX_PLAYERS)
    return 0;
  const int num_slots = left_agents + right_agents;
  const size_t required = num_slots * SLOT_INPUT_BYTES;
  if (buffer_size < required || static_cast<int>(controllers.size()) < MAX_PLAYERS * 2) {
    return 0;
  }
  if (required && !buffer) return 0;
  for (int slot = 0; slot < num_slots; ++slot)
    if (!controllers[SlotIndexToControllerIndex(slot, left_agents, right_agents)]) return 0;
  char* out = static_cast<char*>(buffer);
  for (int s = 0; s < num_slots; ++s) {
    int cidx = SlotIndexToControllerIndex(s, left_agents, right_agents);
    AIControlledKeyboard* c = controllers[cidx];
    SlotInput slot;
    blunted::Vector3 dir = c->GetOriginalDirection();
    slot.dir_x = dir.coords[0];
    slot.dir_y = dir.coords[1];
    slot.buttons = 0;
    for (int b = 0; b < BUTTON_COUNT && b < static_cast<int>(e_ButtonFunction_Size); ++b) {
      if (c->GetButton(static_cast<e_ButtonFunction>(b))) {
        slot.buttons |= (1u << b);
      }
    }
    memcpy(out, &slot, SLOT_INPUT_BYTES);
    out += SLOT_INPUT_BYTES;
  }
  return required;
}

void DecodeAndApplyFrameInput(const void* buffer,
                              size_t buffer_size,
                              std::vector<AIControlledKeyboard*>& controllers,
                              int left_agents,
                              int right_agents) {
  // 2026-09-09: validate the entire frame before changing any controller or advancing logic.
  // const int num_slots = left_agents + right_agents;
  // const size_t required = num_slots * SLOT_INPUT_BYTES;
  // if (buffer_size < required || static_cast<int>(controllers.size()) < MAX_PLAYERS * 2) {
  //   return;
  // }
  if (left_agents < 0 || right_agents < 0 || left_agents > MAX_PLAYERS || right_agents > MAX_PLAYERS)
    throw std::invalid_argument("Invalid frame input team sizes");
  const int num_slots = left_agents + right_agents;
  const size_t required = num_slots * SLOT_INPUT_BYTES;
  if (buffer_size != required || (required && !buffer) || controllers.size() < MAX_PLAYERS * 2)
    throw std::invalid_argument("Frame input does not match the configured controller layout");
  std::array<SlotInput, 2 * MAX_PLAYERS> decoded{};
  for (int slot = 0; slot < num_slots; ++slot) {
    memcpy(&decoded[slot], static_cast<const char*>(buffer) + slot * SLOT_INPUT_BYTES, SLOT_INPUT_BYTES);
    if (!IsValidSlotInput(decoded[slot]) || !controllers[SlotIndexToControllerIndex(slot, left_agents, right_agents)])
      throw std::invalid_argument("Invalid frame input slot");
  }
  // 2026-09-09: application reads only the staged, validated slots.
  // const char* in = static_cast<const char*>(buffer);
  for (int s = 0; s < num_slots; ++s) {
    // 2026-09-09: apply the already validated frame without rereading caller memory.
    // SlotInput slot;
    // memcpy(&slot, in, SLOT_INPUT_BYTES);
    // in += SLOT_INPUT_BYTES;
    const SlotInput& slot = decoded[s];
    int cidx = SlotIndexToControllerIndex(s, left_agents, right_agents);
    AIControlledKeyboard* c = controllers[cidx];
    // 2026-09-09: applying an authoritative slot must enable its human controller,
    // matching GameEnv::action; reset starts every controller in builtin-AI mode.
    c->SetDisabled(false);
    c->SetDirection(blunted::Vector3(slot.dir_x, slot.dir_y, 0.f));
    for (int b = 0; b < BUTTON_COUNT && b < static_cast<int>(e_ButtonFunction_Size); ++b) {
      bool pressed = (slot.buttons & (1u << b)) != 0;
      c->SetButton(static_cast<e_ButtonFunction>(b), pressed);
    }
  }
  // Caller (e.g. game step) should call ResetNotSticky() on all controllers after the step.
}

}  // namespace frame_sync
