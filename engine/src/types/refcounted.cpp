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

#include "refcounted.hpp"

#include "../defines.hpp"

namespace blunted {

RefCounted::RefCounted() : refCount_(0) { DO_VALIDATION; }

RefCounted::~RefCounted() { DO_VALIDATION; }

RefCounted::RefCounted(const RefCounted &src) : refCount_(0) { DO_VALIDATION; }

RefCounted &RefCounted::operator=(const RefCounted &src) {
  DO_VALIDATION;
  return *this;
}

unsigned long RefCounted::GetRefCount() {
  DO_VALIDATION;
  // 2026-04-02 refCount_ 为 std::atomic：原 volatile 直接读在并发下无保证。
  // int i = refCount_;
  // return i;
  return static_cast<unsigned long>(
      refCount_.load(std::memory_order_relaxed));
}

void intrusive_ptr_add_ref(RefCounted *p) {
  DO_VALIDATION;
  assert(p);
  // 2026-04-02 原子递增；与 boost::intrusive_ptr 钩子契约一致。
  // ++(p->refCount_);
  p->refCount_.fetch_add(1, std::memory_order_relaxed);
}

void intrusive_ptr_release(RefCounted *p) {
  DO_VALIDATION;
  assert(p);
  // 2026-04-02 fetch_sub 返回减之前的值；为 1 表示本次释放后 refcount 归零。
  // if (--(p->refCount_) == 0) {
  if (p->refCount_.fetch_sub(1, std::memory_order_acq_rel) == 1) {
    DO_VALIDATION;
    delete p;
  }
}
}