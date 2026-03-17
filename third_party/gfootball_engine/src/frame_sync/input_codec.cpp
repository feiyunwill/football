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

namespace frame_sync {

int SlotIndexToControllerIndex(int slot_index, int left_agents, int right_agents) {
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
  const int num_slots = left_agents + right_agents;
  const size_t required = num_slots * SLOT_INPUT_BYTES;
  if (buffer_size < required || static_cast<int>(controllers.size()) < MAX_PLAYERS * 2) {
    return 0;
  }
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
  const int num_slots = left_agents + right_agents;
  const size_t required = num_slots * SLOT_INPUT_BYTES;
  if (buffer_size < required || static_cast<int>(controllers.size()) < MAX_PLAYERS * 2) {
    return;
  }
  const char* in = static_cast<const char*>(buffer);
  for (int s = 0; s < num_slots; ++s) {
    SlotInput slot;
    memcpy(&slot, in, SLOT_INPUT_BYTES);
    in += SLOT_INPUT_BYTES;
    int cidx = SlotIndexToControllerIndex(s, left_agents, right_agents);
    AIControlledKeyboard* c = controllers[cidx];
    c->SetDirection(blunted::Vector3(slot.dir_x, slot.dir_y, 0.f));
    for (int b = 0; b < BUTTON_COUNT && b < static_cast<int>(e_ButtonFunction_Size); ++b) {
      bool pressed = (slot.buttons & (1u << b)) != 0;
      c->SetButton(static_cast<e_ButtonFunction>(b), pressed);
    }
  }
  // Caller (e.g. game step) should call ResetNotSticky() on all controllers after the step.
}

}  // namespace frame_sync
