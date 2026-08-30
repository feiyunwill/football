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

#include "../../base/geometry/line.hpp"
#include "../../base/geometry/aabb.hpp"

namespace blunted {

// 2025-03-17 Line() 与 ~Line() 已改为头文件中 = default

Line::Line(const Vector3 vec1, const Vector3 vec2) {
  DO_VALIDATION;
  SetVertex(0, vec1);
  SetVertex(1, vec2);
}

void Line::SetVertex(unsigned char pos, const Vector3 &vec) {
  DO_VALIDATION;
  assert(pos < 2);
  vertices_[pos] = vec;
}

  const Vector3 &Line::GetVertex(unsigned char pos) const {
    assert(pos < 2);
    return vertices_[pos];
  }

  // returns offset from p1 towards p2 (0 == p1, 1 == p2)
  float Line::GetClosestToPoint(const Vector3 &point) const {
    if (vertices_[0] == vertices_[1]) return 0.0f;
    float lineDistance = (vertices_[1] - vertices_[0]).GetLength();
    if (lineDistance < 0.000001f) return 0.0f;

    // u == where on the line is the intersection point, 0 == v1 and 1 == v2
    float u = ((point.coords[0] - vertices_[0].coords[0]) * (vertices_[1].coords[0] - vertices_[0].coords[0]) +
               (point.coords[1] - vertices_[0].coords[1]) * (vertices_[1].coords[1] - vertices_[0].coords[1])) /
              (lineDistance * lineDistance);

    return u;
  }

  float Line::GetDistanceToPoint(const Vector3 &point, float &u) const {
    u = GetClosestToPoint(point);

    Vector3 intersect;
    intersect.coords[0] = vertices_[0].coords[0] + u * (vertices_[1].coords[0] - vertices_[0].coords[0]);
    intersect.coords[1] = vertices_[0].coords[1] + u * (vertices_[1].coords[1] - vertices_[0].coords[1]);

    return (intersect - point).GetLength();
  }

  Vector3 Line::GetIntersectionPoint(const Line &line) const {
    float u = 0.0f; //dud
    return GetIntersectionPoint(line, u);
  }

  Vector3 Line::GetIntersectionPoint(const Line &line, float &u) const {
    float divisor = (line.GetVertex(1).coords[1] - line.GetVertex(0).coords[1]) * (vertices_[1].coords[0] - vertices_[0].coords[0]) - (line.GetVertex(1).coords[0] - line.GetVertex(0).coords[0]) * (vertices_[1].coords[1] - vertices_[0].coords[1]);
    if (divisor == 0.0f) return vertices_[0];
    u = ( (line.GetVertex(1).coords[0] - line.GetVertex(0).coords[0]) * (vertices_[0].coords[1] - line.GetVertex(0).coords[1]) - (line.GetVertex(1).coords[1] - line.GetVertex(0).coords[1]) * (vertices_[0].coords[0] - line.GetVertex(0).coords[0]) ) /
        ( divisor );

    return vertices_[0] + (vertices_[1] - vertices_[0]) * u;
  }

  bool Line::WhatSide(const Vector3 &point) {
    DO_VALIDATION;
    return ((vertices_[1].coords[0] - vertices_[0].coords[0]) * (point.coords[1] - vertices_[0].coords[1]) - (vertices_[1].coords[1] - vertices_[0].coords[1]) * (point.coords[0] - vertices_[0].coords[0])) > 0;
  }
}
