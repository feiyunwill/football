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

#ifndef _HPP_OBJECT
#define _HPP_OBJECT

#include "../defines.hpp"

#include "../types/subject.hpp"
#include "../types/spatial.hpp"
#include "../base/properties.hpp"

#include <compare>

namespace blunted {

  class ISystemObject;

  enum e_ObjectType {
    e_ObjectType_Camera = 1,
    e_ObjectType_Image2D = 2,
    e_ObjectType_Geometry = 3,
    e_ObjectType_Skybox = 4,
    e_ObjectType_Light = 5,
    e_ObjectType_UserStart = 7
  };

  constexpr std::strong_ordering operator<=>(e_ObjectType a, e_ObjectType b) {
    return static_cast<int>(a) <=> static_cast<int>(b);
  }

  struct MustUpdateSpatialData {
    bool have_to_ = false;
    e_SystemType exclude_system_;
    friend constexpr std::strong_ordering operator<=>(const MustUpdateSpatialData &a, const MustUpdateSpatialData &b) {
      if (auto c = a.have_to_ <=> b.have_to_; c != 0) return c;
      return static_cast<int>(a.exclude_system_) <=> static_cast<int>(b.exclude_system_);
    }
    friend constexpr bool operator==(const MustUpdateSpatialData &a, const MustUpdateSpatialData &b) = default;
  };

  class Object : public Subject<Interpreter>, public Spatial {

    public:
      Object(std::string name, e_ObjectType objectType);
      virtual ~Object();

      Object(const Object &src);
      Object(Object &&src) noexcept;

      virtual void Exit();

      virtual e_ObjectType GetObjectType();

      virtual bool IsEnabled() { DO_VALIDATION; return enabled_; }
      virtual void Enable() { DO_VALIDATION; enabled_ = true; }
      virtual void Disable() { DO_VALIDATION; enabled_ = false; }

      virtual const Properties &GetProperties() const;
      virtual bool PropertyExists(const char *property) const;
      virtual const std::string &GetProperty(const char *property) const;

      virtual void SetProperties(const Properties &props);
      virtual void SetProperties(Properties &&props);
      virtual void SetProperty(const char *name, const char *value);

      virtual bool RequestPropertyExists(const char *property) const;
      virtual std::string GetRequestProperty(const char *property) const;
      virtual void AddRequestProperty(const char *property);
      virtual void SetRequestProperty(const char *property, const char *value);

      virtual void Synchronize();
      virtual void Poke(e_SystemType targetSystemType);

      virtual void RecursiveUpdateSpatialData(e_SpatialDataType spatialDataType, e_SystemType excludeSystem = e_SystemType_None);

      MustUpdateSpatialData update_spatial_data_after_poke_;

      virtual boost::intrusive_ptr<Interpreter> GetInterpreter(e_SystemType targetSystemType);

      virtual void SetPokePriority(int prio) { DO_VALIDATION; poke_priority_ = prio; }
      virtual int GetPokePriority() const { return poke_priority_; }

    protected:
      Properties properties_;
      e_ObjectType object_type_;
      mutable int poke_priority_;
      mutable Properties request_properties_;
      bool enabled_ = false;

  };

}

#endif
