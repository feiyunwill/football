// Copyright 2019 Google LLC & Bastiaan Konings
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

// written by bastiaan konings schuiling 2008 - 2014
// this work is public domain. the code is undocumented, scruffy, untested, and should generally not be used for anything important.
// i do not offer support, so don't ask. to be used for inspiration :)

#ifndef _HPP_MESSAGEQUEUE
#define _HPP_MESSAGEQUEUE

#include "../defines.hpp"

// 2026-08-26 Modern C++ 迁移（原因）：boost::condition → std::condition_variable；
// 本类仅调用 notify_one()，无 wait，语义完全一致。
#include <condition_variable>
#include <optional>

#include "../base/properties.hpp"

#include "../types/command.hpp"

namespace blunted {

  // 2026-09-09: replace allocating unbounded list with fixed storage; fail explicitly.
//   template <typename T = boost::intrusive_ptr<Command> >
//   class MessageQueue {
//
//     public:
//       MessageQueue() = default;
//       virtual ~MessageQueue() = default;
//
//       // 2026-09-09: release queued resource references before renderer teardown.
//       void Clear() { queue_.clear(); }
//
//       inline void PushMessage(T message, bool notify = true) { DO_VALIDATION;
//         queue_.push_back(message);
//         if (notify) NotifyWaiting();
//       }
//
//       inline void NotifyWaiting() { DO_VALIDATION;
//         message_notification_.notify_one();
//       }
//
//       inline T GetMessage(bool &MsgAvail) { DO_VALIDATION;
//         T message;
//         if (queue_.size() > 0) { DO_VALIDATION;
//           message = *queue_.begin();
//           queue_.pop_front();
//           MsgAvail = true;
//         } else {
//           MsgAvail = false;
//         }
//         return message;
//       }
//
//     protected:
//       // 2025-03-17 Google 规范：Class data members 末尾下划线（cpp-google-style）
//       std::list < T > queue_;
//       // 2026-08-26 移除 Boost：boost::condition → std::condition_variable（唯一调用点是 notify_one）。
//       // boost::condition message_notification_;
//       std::condition_variable message_notification_;
//
//   };
  // Single-owner queue: production graphics operations are serialized by
  // GameEnv's ContextHolder. Referenced textures have their own resource budget.
  template <typename T = boost::intrusive_ptr<Command>>
  class MessageQueue {
    using Slot = std::optional<T>;
    static size_t CheckedCapacity(size_t count, size_t bytes) {
      if (count == 0 || count > 65536 || bytes == 0 || bytes > 16 * 1024 * 1024 ||
          count > bytes / sizeof(Slot))
        throw std::invalid_argument("MessageQueue capacity exceeds storage budget");
      return count;
    }
   public:
    explicit MessageQueue(size_t capacity = 4096, size_t storage_bytes = 1024 * 1024)
        : slots_(CheckedCapacity(capacity, storage_bytes)) {
      static_assert(std::is_nothrow_move_constructible_v<T>,
                    "MessageQueue requires nonthrowing ownership transfer");
      if (StorageBytes() > storage_bytes)
        throw std::length_error("MessageQueue allocator exceeded storage budget");
    }
    virtual ~MessageQueue() = default;
    MessageQueue(const MessageQueue&) = delete;
    MessageQueue& operator=(const MessageQueue&) = delete;
    MessageQueue(MessageQueue&&) = delete;
    MessageQueue& operator=(MessageQueue&&) = delete;

    size_t Size() const noexcept { return count_; }
    size_t Capacity() const noexcept { return slots_.size(); }
    size_t StorageBytes() const noexcept { return slots_.capacity() * sizeof(Slot); }
    void Clear() noexcept {
      while (count_) {
        slots_[head_].reset();
        head_ = (head_ + 1) % slots_.size();
        --count_;
      }
      head_ = 0;
    }
    void PushMessage(T message, bool notify = true) {
      DO_VALIDATION;
      if (count_ == slots_.size())
        throw std::length_error("MessageQueue capacity exceeded");
      slots_[(head_ + count_) % slots_.size()].emplace(std::move(message));
      ++count_;
      if (notify) NotifyWaiting();
    }
    void NotifyWaiting() { message_notification_.notify_one(); }
    T GetMessage(bool& available) {
      DO_VALIDATION;
      available = count_ != 0;
      if (!available) return T{};
      T message(std::move(*slots_[head_]));
      slots_[head_].reset();
      head_ = (head_ + 1) % slots_.size();
      --count_;
      return message;
    }
   private:
    std::vector<Slot> slots_;
    size_t head_ = 0, count_ = 0;
    std::condition_variable message_notification_;
  };

}

#endif
