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

#include "geometrydata.hpp"

#include "../../systems/isystemobject.hpp"

#include "../../base/geometry/trianglemeshutils.hpp"

namespace blunted {

GeometryData::GeometryData() {
  DO_VALIDATION;
  aabb_.aabb.Reset();
  aabb_.dirty = false;
}

GeometryData::~GeometryData() {
  DO_VALIDATION;
  // printf("ANNIHILATING TMESH\n");
  for (unsigned int i = 0; i < triangle_meshes_.size(); i++) {
    DO_VALIDATION;
    delete[] triangle_meshes_[i].vertices;
  }
}

GeometryData::GeometryData(const GeometryData &src) {
  DO_VALIDATION;
  for (unsigned int i = 0; i < src.triangle_meshes_.size(); i++) {
    DO_VALIDATION;
    // shallow copy
    MaterializedTriangleMesh mesh = src.triangle_meshes_[i];

    // 'deepen' vertices
    mesh.vertices = new float[src.triangle_meshes_[i].verticesDataSize];
    memcpy(mesh.vertices, src.triangle_meshes_[i].vertices,
           src.triangle_meshes_[i].verticesDataSize * sizeof(float));

    triangle_meshes_.push_back(mesh);
  }
  aabb_.aabb = src.GetAABB();
  aabb_.dirty = false;
}

GeometryData::GeometryData(GeometryData &&src) noexcept
    : is_dynamic_(src.is_dynamic_),
      triangle_meshes_(std::move(src.triangle_meshes_)),
      aabb_(src.aabb_) {
  src.aabb_.dirty = true;
}

GeometryData &GeometryData::operator=(GeometryData &&src) noexcept {
  is_dynamic_ = src.is_dynamic_;
  triangle_meshes_ = std::move(src.triangle_meshes_);
  aabb_ = src.aabb_;
  src.aabb_.dirty = true;
  return *this;
}

void GeometryData::AddTriangleMesh(Material material, float *vertices,
                                   int verticesDataSize,
                                   std::vector<unsigned int> indices) {
  DO_VALIDATION;
  assert(indices.size() % 3 == 0);
  MaterializedTriangleMesh mesh;
  mesh.material = material;
  mesh.vertices = vertices;
  mesh.verticesDataSize = verticesDataSize;
  mesh.indices = indices;

  triangle_meshes_.push_back(mesh);
  aabb_.aabb.Reset();
  aabb_.dirty = true;
}

std::vector<MaterializedTriangleMesh> GeometryData::GetTriangleMeshes() {
  DO_VALIDATION;
  return triangle_meshes_;
}

std::vector<MaterializedTriangleMesh> &GeometryData::GetTriangleMeshesRef() {
  DO_VALIDATION;
  return triangle_meshes_;
}

  AABB GeometryData::GetAABB() const {
    if (aabb_.dirty) {
      DO_VALIDATION;
      aabb_.aabb.Reset();
      for (int i = 0; i < (signed int)triangle_meshes_.size(); i++) {
        DO_VALIDATION;
        aabb_.aabb += GetTriangleMeshAABB(triangle_meshes_[i].vertices, triangle_meshes_[i].verticesDataSize, triangle_meshes_[i].indices);
      }
      aabb_.dirty = false;
    }
    return aabb_.aabb;
  }

}
