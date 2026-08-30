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

#ifndef _HPP_SCENE
#define _HPP_SCENE

#include "../defines.hpp"

#include "iscene.hpp"

#include <bitset>

namespace blunted {

  typedef std::vector < boost::intrusive_ptr<Object> > vector_Objects;

  class Scene : public IScene {

    public:
      Scene();
      // 2026-04-02 现代 C++：抽象场景基类禁用切片拷贝/移动
      // Scene(const Scene &) = default; — removed: polymorphic base
      Scene(const Scene &) = delete;
      Scene &operator=(const Scene &) = delete;
      Scene(Scene &&) = delete;
      Scene &operator=(Scene &&) = delete;
      // 2026-04-02 现代 C++：覆盖 IScene 虚函数使用 override
      // virtual ~Scene();
      ~Scene() override;

      // virtual void Init() = 0; // ATOMIC
      void Init() override = 0; // ATOMIC
      // virtual void Exit(); // ATOMIC
      void Exit() override; // ATOMIC

      // virtual void CreateSystemObjects(boost::intrusive_ptr<Object> object);
      void CreateSystemObjects(boost::intrusive_ptr<Object> object) override;
      // virtual bool SupportedObjectType(e_ObjectType objectType) const;
      bool SupportedObjectType(e_ObjectType objectType) const override;

    protected:
      // 2026-04-02 原 std::vector<e_ObjectType> 线性查找；改为 bitset 按枚举整数值置位，O(1) 查询
      // std::vector<e_ObjectType> supported_object_types_;
      std::bitset<kObjectTypeSupportBitsetSize> supported_object_types_{};
  };

}

#endif
