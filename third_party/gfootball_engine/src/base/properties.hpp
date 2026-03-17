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

#ifndef _HPP_BASE_PROPERTIES
#define _HPP_BASE_PROPERTIES

#include "../defines.hpp"

#include "../base/math/vector3.hpp"

namespace blunted {

  typedef std::map <std::string, std::string> map_Properties;

  class Vector3;

  class Properties {

    public:
      Properties();
      Properties(std::vector<std::pair<std::string, float>> values);
      virtual ~Properties() = default;
      // 2025-03-17 六大函数：显式 =default（规则 cpp-special-member-functions）
      Properties(const Properties&) = default;
      Properties(Properties&&) = default;
      Properties& operator=(const Properties&) = default;
      Properties& operator=(Properties&&) = default;
      bool Exists(const std::string &name) const;

      void Set(const std::string &name, const std::string &value);
      void SetInt(const std::string &name, int value);
      void Set(const std::string &name, real value);
      void SetBool(const std::string &name, bool value);
      const std::string &Get(
          const std::string &name,
          const std::string &defaultValue = "") const;
      bool GetBool(const std::string &name, bool defaultValue = false) const;
      real GetReal(const std::string &name, real defaultValue = 0) const;
      int GetInt(const std::string &name, int defaultValue = 0) const;
      void AddProperties(const Properties *userprops);
      void AddProperties(const Properties &userprops);
      // 2025-03-17 移动语义：支持 Object::SetProperties(Properties&&)
      void AddProperties(Properties &&other);
      const map_Properties *GetProperties() const;
      void ProcessState(EnvState* state);

     protected:
      // 2025-03-17 Google 规范：Class data members 末尾下划线（cpp-google-style）
      map_Properties properties_;
  };

}

#endif
