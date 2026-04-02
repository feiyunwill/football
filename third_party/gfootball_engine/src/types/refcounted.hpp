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

#ifndef _HPP_REFCOUNTED
#define _HPP_REFCOUNTED

// 2026-04-02 头文件仅声明 RefCounted，不拉 defines.hpp，避免扩大包含面；DO_VALIDATION 仅在 .cpp 使用。
// #include "../defines.hpp"

// 2026-04-02 移除 Boost：头文件未实际使用 atomic_count；实现侧曾用 volatile++/--，非线程安全。
// #include <boost/detail/atomic_count.hpp>
// #ifdef WIN32
// #include <boost/detail/interlocked.hpp>
// #endif
#include <atomic>

namespace blunted {

  class RefCounted {

    public:
      RefCounted();
      virtual ~RefCounted();

      RefCounted(const RefCounted &src);
      RefCounted& operator=(const RefCounted &src);

      unsigned long GetRefCount();

    protected:

    private:
      // 2025-03-17 Google 规范：Class data members 末尾下划线（cpp-google-style）
      // 2026-04-02 标准库 std::atomic 替代 volatile long，保证引用计数原子性与去 Boost。
      // volatile long refCount_ = 0;
      std::atomic<long> refCount_{0};
      friend void intrusive_ptr_add_ref(RefCounted *p);
      friend void intrusive_ptr_release(RefCounted *p);

  };

  void intrusive_ptr_add_ref(RefCounted *p);
  void intrusive_ptr_release(RefCounted *p);

}

#endif
