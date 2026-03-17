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

#include "vertexbuffer.hpp"

#include "../rendering/interface_renderer3d.hpp"
#include "../rendering/r3d_messages.hpp"

namespace blunted {

VertexBuffer::VertexBuffer()
    : vertices_data_size_(0),
      vertex_count_(0),
      dynamic_buffer_(false),
      size_changed_(false) {
  DO_VALIDATION;
  assert(vertex_buffer_id_.bufferID == -1);
}

VertexBuffer::~VertexBuffer() {
  DO_VALIDATION;
  if (vertex_buffer_id_.bufferID != -1) {
    DO_VALIDATION;
    renderer_3d_->DeleteVertexBuffer(vertex_buffer_id_);
  }
}

void VertexBuffer::SetTriangleMesh(const std::vector<float>& vertices,
                                   unsigned int verticesDataSize,
                                   std::vector<unsigned int> indices) {
  DO_VALIDATION;
  vertices_ = vertices;
  TriangleMeshWasUpdatedExternally(verticesDataSize, indices);
}

void VertexBuffer::TriangleMeshWasUpdatedExternally(
    unsigned int verticesDataSize, std::vector<unsigned int> indices) {
  DO_VALIDATION;
  if (indices.size() > 0) {
    DO_VALIDATION;
    if (indices.size() != indices_.size()) size_changed_ = true;
    indices_ = indices;
  }
  vertices_data_size_ = verticesDataSize;
  int tmpVertexCount = verticesDataSize / GetTriangleMeshElementCount() / 3;
  if (tmpVertexCount != vertex_count_) size_changed_ = true;
  vertex_count_ = tmpVertexCount;
}

VertexBufferID VertexBuffer::CreateOrUpdateVertexBuffer(Renderer3D* renderer3D,
                                                        bool dynamicBuffer) {
  DO_VALIDATION;
  renderer_3d_ = renderer3D;

  if (vertex_buffer_id_.bufferID != -1 && size_changed_) {
    DO_VALIDATION;
    renderer3D->DeleteVertexBuffer(vertex_buffer_id_);
    vertex_buffer_id_.bufferID = -1;
  }

  if (vertex_buffer_id_.bufferID == -1) {
    DO_VALIDATION;
    dynamic_buffer_ = dynamicBuffer;
    e_VertexBufferUsage usage = e_VertexBufferUsage_StaticDraw;
    if (dynamicBuffer) usage = e_VertexBufferUsage_DynamicDraw;
    vertex_buffer_id_ = renderer3D->CreateVertexBuffer(
        vertices_.data(), vertices_data_size_, indices_, usage);
  } else {
    renderer3D->UpdateVertexBuffer(vertex_buffer_id_, vertices_.data(),
                                   vertices_data_size_);
  }

  size_changed_ = false;

  return vertex_buffer_id_;
}

float* VertexBuffer::GetTriangleMesh() {
  DO_VALIDATION;
  return vertices_.data();
}

int VertexBuffer::GetVaoID() {
  DO_VALIDATION;
  return vertex_buffer_id_.vertexArrayID;
}

int VertexBuffer::GetVerticesDataSize() {
  DO_VALIDATION;
  return vertices_data_size_;
}
}
