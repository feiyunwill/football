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

#include "plane.hpp"

#include <cassert>
#include <cmath>

namespace blunted {

Plane::Plane() : determinant_(0) {
  DO_VALIDATION;
  dirty_determinant_ = true;
}

Plane::Plane(const Vector3 vec1, const Vector3 vec2) {
  DO_VALIDATION;
  SetVertex(0, vec1);
  SetVertex(1, vec2);
  dirty_determinant_ = true;
}

// 2025-03-17 ~Plane() 已改为头文件中 = default

void Plane::Set(const Vector3 &pos, const Vector3 &dir) {
  DO_VALIDATION;
  SetVertex(0, pos);
  SetVertex(1, dir);
}

void Plane::SetVertex(unsigned char pos, const Vector3 &vec) {
  DO_VALIDATION;
  assert(pos < 2);
  vertices_[pos].coords[0] = vec.coords[0];
  vertices_[pos].coords[1] = vec.coords[1];
  vertices_[pos].coords[2] = vec.coords[2];
  dirty_determinant_ = true;
}

  const Vector3 &Plane::GetVertex(unsigned char pos) const {
    assert(pos < 2);
    return vertices_[pos];
  }

  void Plane::CalculateDeterminant() const {
    determinant_ = -GetVertex(0).GetDotProduct(GetVertex(1));
    dirty_determinant_ = false;
  }

  real Plane::GetDeterminant() const {
    if (dirty_determinant_) CalculateDeterminant();
    return determinant_;
  }

}
