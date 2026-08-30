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

#include "texture.hpp"

#include "../rendering/r3d_messages.hpp"

namespace blunted {

Texture::Texture() : texture_id_(-1) {
  DO_VALIDATION;
  renderer_3d_ = nullptr;
  width_ = 0;
  height_ = 0;
}

Texture::~Texture() {
  DO_VALIDATION;
  DeleteTexture();
}

void Texture::SetRenderer3D(Renderer3D *renderer3D) {
  DO_VALIDATION;
  renderer_3d_ = renderer3D;
}

void Texture::DeleteTexture() {
  DO_VALIDATION;
  if (texture_id_ != -1) {
    DO_VALIDATION;
    assert(renderer_3d_);
    renderer_3d_->DeleteTexture(texture_id_);
    texture_id_ = -1;
  }
}

int Texture::CreateTexture(e_InternalPixelFormat internalPixelFormat,
                           e_PixelFormat pixelFormat, int width, int height,
                           bool alpha, bool repeat, bool mipmaps, bool filter,
                           bool compareDepth) {
  DO_VALIDATION;
  assert(renderer_3d_);

  texture_id_ = renderer_3d_->CreateTexture(internalPixelFormat, pixelFormat, width,
                                        height, alpha, repeat, mipmaps, filter,
                                        false, compareDepth);

  width_ = width;
  height_ = height;

  return texture_id_;
}

void Texture::ResizeTexture(SDL_Surface *image,
                            e_InternalPixelFormat internalPixelFormat,
                            e_PixelFormat pixelFormat, bool alpha,
                            bool mipmaps) {
  DO_VALIDATION;
  assert(renderer_3d_);
  assert(texture_id_ != -1);

  bool _alpha = SDL_ISPIXELFORMAT_ALPHA(image->format->format);
  renderer_3d_->ResizeTexture(texture_id_, image, internalPixelFormat, pixelFormat,
                            _alpha, mipmaps);
}

void Texture::UpdateTexture(SDL_Surface *image, bool alpha, bool mipmaps) {
  DO_VALIDATION;
  assert(renderer_3d_);
  assert(texture_id_ != -1);

  bool _alpha = SDL_ISPIXELFORMAT_ALPHA(image->format->format);
  renderer_3d_->UpdateTexture(texture_id_, image, _alpha, mipmaps);
}

int Texture::GetID() {
  DO_VALIDATION;
  return texture_id_;
}
}
