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

#include "image2d.hpp"

#include <cmath>

#include "../../base/log.hpp"

#include "../../systems/isystemobject.hpp"

//#include "SDL2/SDL_gfxBlitFunc.h"

namespace blunted {

Image2D::Image2D(std::string name) : Object(name, e_ObjectType_Image2D) {
  DO_VALIDATION;
  // printf("CREATING IMAGE\n");
}

Image2D::~Image2D() {
  DO_VALIDATION;
  // printf("DELETING IMAGE\n");
}

void Image2D::Exit() {
  DO_VALIDATION;  // ATOMIC
  // printf("EXITING IMAGE\n");

  int observersSize = observers_.size();
  for (int i = 0; i < observersSize; i++) {
    DO_VALIDATION;
    IImage2DInterpreter *image2DInterpreter =
        static_cast<IImage2DInterpreter *>(observers_[i].get());
    image2DInterpreter->OnUnload();
  }

  Object::Exit();

  if (image_) image_.reset();
}


void Image2D::SetImage(boost::intrusive_ptr<Resource<Surface> > image) {
  DO_VALIDATION;

  image_ = image;

  position_[0] = 0;
  position_[1] = 0;
  size_[0] = image->GetResource()->GetData()->w;
  size_[1] = image->GetResource()->GetData()->h;

  int observersSize = observers_.size();
  for (int i = 0; i < observersSize; i++) {
    DO_VALIDATION;
    IImage2DInterpreter *image2DInterpreter =
        static_cast<IImage2DInterpreter *>(observers_[i].get());
    image2DInterpreter->OnLoad(image);
  }
}

boost::intrusive_ptr<Resource<Surface> > Image2D::GetImage() {
  DO_VALIDATION;

  return image_;
}

void Image2D::SetPosition(int x, int y) {
  DO_VALIDATION;

  position_[0] = x;
  position_[1] = y;

  int observersSize = observers_.size();
  for (int i = 0; i < observersSize; i++) {
    DO_VALIDATION;
    IImage2DInterpreter *image2DInterpreter =
        static_cast<IImage2DInterpreter *>(observers_[i].get());
    image2DInterpreter->OnMove(x, y);
  }
}

void Image2D::SetPosition(const Vector3 &newPosition, bool updateSpatialData) {
  DO_VALIDATION;
  SetPosition(int(std::floor(newPosition.coords[0])),
              int(std::floor(newPosition.coords[1])));
}

  Vector3 Image2D::GetPosition() const {
    Vector3 tmp(position_[0], position_[1], 0);

    return tmp;
  }

  Vector3 Image2D::GetSize() const {
    Vector3 tmp(size_[0], size_[1], 0);

    return tmp;
  }

  void Image2D::DrawRectangle(int x, int y, int w, int h, const Vector3 &color,
                              int alpha) {
    DO_VALIDATION;
    SDL_Surface *surface = image_->GetResource()->GetData();
    //SDL_LockSurface(surface);

    Uint32 color32;
    if (SDL_ISPIXELFORMAT_ALPHA(surface->format->format))
      color32 = SDL_MapRGBA(surface->format, int(std::floor(color.coords[0])),
                            int(std::floor(color.coords[1])),
                            int(std::floor(color.coords[2])), alpha);
    else
      color32 = SDL_MapRGB(surface->format, int(std::floor(color.coords[0])),
                           int(std::floor(color.coords[1])),
                           int(std::floor(color.coords[2])));

    sdl_rectangle_filled(surface, x, y, w, h, color32);
  }

  void Image2D::Resize(int w, int h) {
    DO_VALIDATION;
    image_->GetResource()->Resize(w, h);
    size_[0] = w;
    size_[1] = h;
  }

  void Image2D::Poke(e_SystemType targetSystemType) {
    DO_VALIDATION;

    int observersSize = observers_.size();
    for (int i = 0; i < observersSize; i++) {
      DO_VALIDATION;
      IImage2DInterpreter *image2DInterpreter = static_cast<IImage2DInterpreter*>(observers_[i].get());
      if (image2DInterpreter->GetSystemType() == targetSystemType) image2DInterpreter->OnPoke();
    }
  }

  // events

  void Image2D::OnChange() {
    DO_VALIDATION;
    int observersSize = observers_.size();
    for (int i = 0; i < observersSize; i++) {
      DO_VALIDATION;
      IImage2DInterpreter *image2DInterpreter = static_cast<IImage2DInterpreter*>(observers_[i].get());
      image2DInterpreter->OnChange(image_);
    }
  }
}
