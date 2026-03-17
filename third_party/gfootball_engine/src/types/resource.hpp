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

#ifndef _HPP_RESOURCE
#define _HPP_RESOURCE

#include <compare>

#include "../defines.hpp"

#include "../managers/resourcemanager.hpp"

#include "../types/refcounted.hpp"

namespace blunted {

  enum e_ResourceType {
    e_ResourceType_GeometryData = 1,
    e_ResourceType_Surface = 2,
    e_ResourceType_Texture = 3,
    e_ResourceType_VertexBuffer = 4,
  };
  constexpr std::strong_ordering operator<=>(e_ResourceType a, e_ResourceType b) {
    return static_cast<int>(a) <=> static_cast<int>(b);
  }

  template <typename T>
  class Resource : public RefCounted {

    public:
      Resource(std::string identString) : resource_(nullptr), identString_(identString) { DO_VALIDATION;
        resource_ = new T();
      }

      virtual ~Resource() { DO_VALIDATION;
        delete resource_;
        resource_ = nullptr;
      }

      Resource(const Resource &src, const std::string &identString) : identString_(identString) { DO_VALIDATION;
        resource_ = new T(*src.resource_);
      }

      // 2025-03-17 禁止默认拷贝/移动赋值，避免重复释放（cpp-special-member-functions）
      Resource &operator=(const Resource &) = delete;
      Resource(Resource &&) = delete;
      Resource &operator=(Resource &&) = delete;

      T *GetResource() { DO_VALIDATION;
        return resource_;
      }

      std::string GetIdentString() { DO_VALIDATION;
        return identString_;
      }

    protected:
      // 2025-03-17 Google 规范：Class data members 末尾下划线（cpp-google-style）
      T *resource_;
      const std::string identString_;

  };

}

#endif
