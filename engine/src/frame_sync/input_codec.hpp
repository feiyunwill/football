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

#ifndef GFOOTBALL_FRAME_SYNC_INPUT_CODEC_HPP
#define GFOOTBALL_FRAME_SYNC_INPUT_CODEC_HPP

#include "protocol.hpp"
#include <vector>
#include <cstddef>

class AIControlledKeyboard;

namespace frame_sync {

// Full action: encodes direction + all e_ButtonFunction states (aligned with action()/sticky_action_state()).
// Slot order: first left_agents slots (controller indices 0 .. left_agents-1),
// then right_agents slots (controller indices MAX_PLAYERS .. MAX_PLAYERS+right_agents-1).
// Buffer must be at least (left_agents + right_agents) * SLOT_INPUT_BYTES.
// Returns number of bytes written. Caller calls ResetNotSticky() on controllers after step.
size_t EncodeFrameInput(const std::vector<AIControlledKeyboard*>& controllers,
                        int left_agents,
                        int right_agents,
                        void* buffer,
                        size_t buffer_size);

// Decodes one frame's input from the protocol buffer and applies to the engine controllers.
// Same slot order as EncodeFrameInput. Buffer must contain at least
// num_slots * SLOT_INPUT_BYTES. Caller should call ResetNotSticky() on controllers after step.
void DecodeAndApplyFrameInput(const void* buffer,
                              size_t buffer_size,
                              std::vector<AIControlledKeyboard*>& controllers,
                              int left_agents,
                              int right_agents);

// Reads a single SlotInput from a slot index (0 .. left_agents+right_agents-1).
// Returns the controller index in the controllers vector for that slot.
int SlotIndexToControllerIndex(int slot_index, int left_agents, int right_agents);

}  // namespace frame_sync

#endif
