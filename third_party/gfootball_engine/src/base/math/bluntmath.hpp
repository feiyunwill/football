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

#ifndef _hpp_bluntmath
#define _hpp_bluntmath

#include <cmath>
#include <limits>
#include <assert.h>
#include <iostream>
#include "../log.hpp"



namespace blunted {
  typedef float real;

  real clamp(const real value, const real min, const real max);
  real NormalizedClamp(const real value, const real min, const real max);

  // you can never be too specific ;)
  constexpr real pi = 3.1415926535897932384626433832795028841972f; // last decimal rounded ;)
  // 2025-03-17 Class data members 改为 Google 规范：小写+下划线+末尾下划线（cpp-google-style）
  class radian {
   public:
    radian() { DO_VALIDATION;}
    radian(float r) : angle_(r) { DO_VALIDATION;}
    // 2025-03-17 六大函数：显式 =default 以符合 cpp-special-member-functions 规则
    radian(const radian&) = default;
    radian(radian&&) = default;
    ~radian() = default;
    radian& operator=(const radian&) = default;
    radian& operator=(radian&&) = default;
    std::ostream& operator<<(std::ostream& os) {
      os << angle_ << " " << rotated_;
      return os;
    }
    radian &operator+=(radian r) { DO_VALIDATION;
      angle_ += r.angle_;
      rotated_ ^= r.rotated_;
      return *this;
    }
    radian &operator-=(radian r){
      angle_ -= r.angle_;
      rotated_ ^= r.rotated_;
      return *this;
    }
    radian &operator/=(radian r) { DO_VALIDATION;
      *this = radian(real(*this) / real(r));
      return *this;
    }
    radian &operator*=(radian r) { DO_VALIDATION;
      *this = radian(real(*this) * real(r));
      return *this;
    }
    operator real() const {
      if (rotated_) { DO_VALIDATION;
        return angle_ - pi;
      }
      return angle_;
    }
    void Mirror() { DO_VALIDATION;
      rotated_ = !rotated_;
    }
   private:
    float angle_ = 0.0f;
    // Was angle rotated by PI.
    bool rotated_ = false;
  };

  void normalize(real v[3]);
  signed int signSide(real n);  // returns -1 or 1
  bool is_odd(int n);
  void randomseed(unsigned int seed);
  real boostrandom(real min, real max);
  real random_non_determ(real min, real max);

  inline float curve(float source, float bias = 1.0f) { DO_VALIDATION; // make linear / into sined _/-
    return (std::sin((source - 0.5f) * pi) * 0.5f + 0.5f) * bias +
           source * (1.0f - bias);
  }

  radian ModulateIntoRange(real min, real max, radian value);
}

#endif
