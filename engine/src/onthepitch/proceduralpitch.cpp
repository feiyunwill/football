#include "game_load.hpp"
#include <memory>
#include <stdexcept>
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

// written by bastiaan konings schuiling 2008 - 2015
// this work is public domain. the code is undocumented, scruffy, untested, and should generally not be used for anything important.
// i do not offer support, so don't ask. to be used for inspiration :)

#include "proceduralpitch.hpp"

#include <cmath>
#include <vector>

#include "../misc/perlin.h"

#include "../gamedefines.hpp"

#include "../types/resource.hpp"
#include "../systems/graphics/resources/texture.hpp"

#include "../main.hpp" // for getconfig

constexpr int perlinTexW = 1600;
constexpr int perlinTexH = 1000;
constexpr int seamlessTexW = 1200;
constexpr int seamlessTexH = 1200;
constexpr int overlayTexW = 4096;
constexpr int overlayTexH = 2048;

template <typename T>
T BilinearSample(T *tex, float x, float y, int w, int h) {
  DO_VALIDATION;
  // nearest neighbor version
  //return tex[int(y) * w + int(x)];

  // actual bilinear version
  int intX1 = int(std::floor(x));
  int intY1 = int(std::floor(y));
  int intX2 = (int(std::floor(x)) + 1) % w;
  int intY2 = (int(std::floor(y)) + 1) % h;
  T x1y1 = tex[intY1 * w + intX1];
  T x2y1 = tex[intY1 * w + intX2];
  T x1y2 = tex[intY2 * w + intX1];
  T x2y2 = tex[intY2 * w + intX2];
  float xBias = x - intX1;
  float yBias = y - intY1;
  T result = (x1y1 * (1.0f - xBias) + x2y1 * xBias) * (1.0f - yBias) +
             (x1y2 * (1.0f - xBias) + x2y2 * xBias) * yBias;

  return result;
}

// 2026-09-14: identical bilinear arithmetic per component avoids temporary Vector3 chains.
template <>
Vector3 BilinearSample(Vector3* tex, float x, float y, int w, int h) {
  DO_VALIDATION;
  const int x1 = int(std::floor(x)), y1 = int(std::floor(y));
  const int x2 = (x1 + 1) % w, y2 = (y1 + 1) % h;
  const float xb = x - x1, yb = y - y1;
  Vector3 result;
  for (int component = 0; component < 3; ++component) {
    result.coords[component] =
        (tex[y1 * w + x1].coords[component] * (1.0f - xb) +
         tex[y1 * w + x2].coords[component] * xb) * (1.0f - yb) +
        (tex[y2 * w + x1].coords[component] * (1.0f - xb) +
         tex[y2 * w + x2].coords[component] * xb) * yb;
  }
  return result;
}

Uint32 GetPitchDiffuseColor(SDL_Surface *pitchSurf, Vector3 *seamlessTex,
                            float *perlinTex, Vector3 *overlayTex,
                            float *overlay_alphaTex, float xCoord,
                            // 2026-09-14: freeze display configuration once per texture chunk.
                            // float yCoord) {
                            float yCoord, float rToB) {
  DO_VALIDATION;

  float texMultiplier = 0.3f;
  float texScale = 0.32f;
  float randomNoiseMultiplier = 0.0f;
  float perlinNoiseMultiplier = 0.4f;
  float brightness = 2.0f;

  float r, g, b;

  float contrast = 0.4f; // g <=> rb contrast. lower = less saturation, higher = greener
  // 2026-09-14: moved the invariant lookup out of the per-pixel loop.
  //  float rToB = GetConfiguration()->GetReal("graphics_pitchredtoblueratio", 0.5f) * 2.0f; // 0 .. 2, higher is more red, lower is more blue
  r = ((35 - contrast * 10) * rToB ) * brightness;
  g = 46 * brightness;
  b = ((25 - contrast * 10) * (2.0f - rToB) ) * brightness;

  float seamlessX = ((xCoord / pitchFullHalfW) * 0.5 + 0.5) * seamlessTexW * 18.0 * texScale;
  float seamlessY = ((yCoord / pitchFullHalfH) * 0.5 + 0.5) * seamlessTexH * 12.0 * texScale;
  seamlessX = std::fmod(seamlessX, seamlessTexW);
  seamlessY = std::fmod(seamlessY, seamlessTexH);
  //printf("%f, %f - ", seamlessX, seamlessY);
  Vector3 tex = BilinearSample(seamlessTex, seamlessX, seamlessY, seamlessTexW, seamlessTexH);
  r = r * (1.0f - texMultiplier) + tex.coords[0] * texMultiplier;
  g = g * (1.0f - texMultiplier) + tex.coords[1] * texMultiplier;
  b = b * (1.0f - texMultiplier) + tex.coords[2] * texMultiplier;

  float perlX = ((xCoord / pitchFullHalfW) * 0.5 + 0.5) * perlinTexW;
  float perlY = ((yCoord / pitchFullHalfH) * 0.5 + 0.5) * perlinTexH;
  float randomSpread = 2.5f;
  float randomX = random_non_determ(-1, 1);
  perlX = clamp(perlX + randomX * randomSpread, 0, perlinTexW - 1);
  float randomY = random_non_determ(-1, 1);
  perlY = clamp(perlY + randomY * randomSpread, 0, perlinTexH - 1);
  float perlinNoise = BilinearSample(perlinTex, perlX, perlY, perlinTexW, perlinTexH) - 0.5f;
  float perlinNoiseR = perlinNoise;
  float perlinNoiseG = perlinNoise;
  float perlinNoiseB = perlinNoise;

  /* mud
    if (noise < 0.1) { DO_VALIDATION;
      float bias = noise / 1.0;
      r = (r * bias) + r * 1.0  * (1 - bias);
      g = (g * bias) + g * 0.9  * (1 - bias);
      b = (b * bias) + b * 0.9  * (1 - bias);
    }
  */

  float randomNoise = 0.0f;
  if (randomNoiseMultiplier > 0.0f) randomNoise = random_non_determ(-1, 1);
  r += ((perlinNoiseR * perlinNoiseMultiplier) + (randomNoise * randomNoiseMultiplier)) * 40.0f;
  g += ((perlinNoiseG * perlinNoiseMultiplier) + (randomNoise * randomNoiseMultiplier)) * 40.0f;
  b += ((perlinNoiseB * perlinNoiseMultiplier) + (randomNoise * randomNoiseMultiplier)) * 40.0f;

  // fake ambient occlusion
  Vector3 lightPos = Vector3(0, 0, 0);
  float darkness =
      1.0f - std::pow(clamp((lightPos - Vector3(xCoord / pitchHalfW,
                                                yCoord / pitchHalfH, 0))
                                    .GetLength() *
                                0.7f,
                            0.0, 1.0),
                      1.5f) *
                 0.18f;
  r *= darkness;
  g *= darkness;
  b *= darkness;

  float overlayX = ((xCoord / pitchFullHalfW) * 0.5 + 0.5) * overlayTexW;
  float overlayY = ((yCoord / pitchFullHalfH) * 0.5 + 0.5) * overlayTexH;
  Vector3 overlay = BilinearSample(overlayTex, overlayX, overlayY, overlayTexW, overlayTexH);
  float overlay_alpha = BilinearSample(overlay_alphaTex, overlayX, overlayY, overlayTexW, overlayTexH);
  r = clamp(r * (1.0 - overlay_alpha) + overlay.coords[0] * overlay_alpha, 0, 255);
  g = clamp(g * (1.0 - overlay_alpha) + overlay.coords[1] * overlay_alpha, 0, 255);
  b = clamp(b * (1.0 - overlay_alpha) + overlay.coords[2] * overlay_alpha, 0, 255);

  Uint32 color = SDL_MapRGB(pitchSurf->format, r, g, b);
  return color;
}

inline Uint32 GetPitchSpecularColor(SDL_Surface *pitchSurf, float *perlinTex,
                                    float xCoord, float yCoord) {
  DO_VALIDATION;

  float base = 2.0f;
  float noisefac = 18.0f;

  float perlX = ((xCoord / pitchFullHalfW) * 0.5 + 0.5) * perlinTexW;
  float perlY = ((yCoord / pitchFullHalfH) * 0.5 + 0.5) * perlinTexH;
  float randomSpread = 2.5f;
  float randomX = random_non_determ(-1, 1);
  perlX = clamp(perlX + randomX * randomSpread, 0, perlinTexW - 1);
  float randomY = random_non_determ(-1, 1);
  perlY = clamp(perlY + randomY * randomSpread, 0, perlinTexH - 1);
  float noise = base + BilinearSample(perlinTex, perlX, perlY, perlinTexW, perlinTexH) * noisefac;

  Uint32 color = SDL_MapRGB(pitchSurf->format, noise, noise, noise);
  return color;
}

float GetSmoothGrassDirection(float coord, float repeat,
                              int transitionSharpness = 5) {
  DO_VALIDATION;
  float iteration = std::floor(coord / repeat);
  float bias = coord - repeat * iteration; // goes from 0 to 1 over two bands (since bands are split by being < 0.5 and > 0.5)
  bias = std::sin(bias * 2 * pi) * 0.5f + 0.5f;
  for (int i = 0; i < transitionSharpness; i++) {
    DO_VALIDATION;
    bias = curve(bias, 1.0f);
  }

  // back to -1 .. 1 range
  bias *= 2.0f;
  bias -= 1.0f;
  return bias;
}

// 2026-09-14: keep the previous pixel implementation for review.
// 
// Uint32 GetPitchNormalColor(SDL_Surface *pitchSurf, float xCoord, float yCoord,
//                            float repeatMultiplier) {
//   DO_VALIDATION;
//   float noisefac = 0.06f;
// 
//   Vector3 normal = Vector3(0, 0, 1);
// 
//   if (fabs(xCoord) < pitchHalfW && fabs(yCoord) < pitchHalfH) {
//     DO_VALIDATION;
// 
//     float xRepeat = 11.0f * repeatMultiplier;
//     float yRepeat = 11.0f * repeatMultiplier;
//     float xStrength = 0.12;
//     float yStrength = 0.1; // i *think* the mowing of the 'lateral' lines may undo the strength of these medial lines. so make this less apparent
// 
//     int transitionSharpness = 5;
//     if (repeatMultiplier > 0.75f) transitionSharpness = 7; // wider mow lines == more sharpening to correct for upscale
//     normal += Vector3(GetSmoothGrassDirection(yCoord / yRepeat, 1.0f, transitionSharpness) * yStrength, GetSmoothGrassDirection(xCoord / xRepeat, 1.0f, transitionSharpness) * xStrength, 0);
//   }
// 
//   normal.coords[0] += random_non_determ(-1, 1) * noisefac;
//   normal.coords[1] += random_non_determ(-1, 1) * noisefac;
// 
//   normal.Normalize();
// 
//   normal.coords[0] = normal.coords[0] * 0.5f + 0.5f;
//   normal.coords[1] = normal.coords[1] * 0.5f + 0.5f;
//   normal.coords[2] = normal.coords[2] * 0.5f + 0.5f;
// 
//   Uint32 color = SDL_MapRGB(pitchSurf->format, normal.coords[0] * 255, normal.coords[1] * 255, normal.coords[2] * 255);
//   return color;
// }

struct PitchNormalAxisSample {
  float direction = 0;
  bool inside = false;
  PitchNormalAxisSample() = default;
  ~PitchNormalAxisSample() = default;
  PitchNormalAxisSample(const PitchNormalAxisSample&) = default;
  PitchNormalAxisSample& operator=(const PitchNormalAxisSample&) = default;
  PitchNormalAxisSample(PitchNormalAxisSample&&) = default;
  PitchNormalAxisSample& operator=(PitchNormalAxisSample&&) = default;
};
// Mowing depends on one coordinate, so compute each row/column only once.
// The original double-coordinate expression and float strengths are preserved.
std::vector<PitchNormalAxisSample> PitchNormalAxis(
    int pixels, float fullHalf, float fieldHalf, int offset,
    float repeatMultiplier, float strength) {
  std::vector<PitchNormalAxisSample> samples(pixels);
  const float repeat = 11.0f * repeatMultiplier;
  const int sharpness = repeatMultiplier > 0.75f ? 7 : 5;
  for (int pixel = 0; pixel < pixels; ++pixel) {
    const float coordinate = pixel / (pixels * 1.0) * fullHalf + fullHalf * offset;
    samples[pixel].inside = fabs(coordinate) < fieldHalf;
    if (samples[pixel].inside)
      samples[pixel].direction =
          GetSmoothGrassDirection(coordinate / repeat, 1.0f, sharpness) * strength;
  }
  return samples;
}
Vector3 PitchNormalBase(const PitchNormalAxisSample& x, const PitchNormalAxisSample& y) {
  Vector3 normal(0, 0, 1);
  if (x.inside && y.inside) normal += Vector3(y.direction, x.direction, 0);
  return normal;
}
Uint32 GetPitchNormalColorPrepared(SDL_Surface* surface, Vector3 normal) {
  DO_VALIDATION;
  const float noisefac = 0.06f;
  normal.coords[0] += random_non_determ(-1, 1) * noisefac;
  normal.coords[1] += random_non_determ(-1, 1) * noisefac;
  normal.Normalize();
  normal.coords[0] = normal.coords[0] * 0.5f + 0.5f;
  normal.coords[1] = normal.coords[1] * 0.5f + 0.5f;
  normal.coords[2] = normal.coords[2] * 0.5f + 0.5f;
  return SDL_MapRGB(surface->format, normal.coords[0] * 255,
                   normal.coords[1] * 255, normal.coords[2] * 255);
}

/* todo
void DrawMud(SDL_PixelFormat *pixelFormat, Uint32 *diffuseBitmap, int resX, int
resY, signed int offsetW, signed int offsetH) { DO_VALIDATION;
}
*/

void CreateChunk(int i, int resX, int resY, int resSpecularX, int resSpecularY,
                 int resNormalX, int resNormalY,
                 float grassNormalRepeatMultiplier, Vector3 *seamlessTex,
                 float *perlinTex, Vector3 *overlayTex,
                 float *overlay_alphaTex) {
  DO_VALIDATION;

  signed int offsetW, offsetH;
  if (i == 1 || i == 3) offsetW = -1; else
                        offsetW = 0;
  if (i == 1 || i == 2) offsetH = -1; else
                        offsetH = 0;

// 2026-09-14: own the SDL surface before any cancellation or subsequent allocation.
//   SDL_Surface *pitchDiffuseSurf = CreateSDLSurface(resX, resY);
  auto pitchDiffuseSurf_owner = std::unique_ptr<SDL_Surface, decltype(&SDL_FreeSurface)>(CreateSDLSurface(resX, resY), SDL_FreeSurface);
  SDL_Surface* pitchDiffuseSurf = pitchDiffuseSurf_owner.get();
  if (!pitchDiffuseSurf) throw std::runtime_error("Pitch surface allocation or loading failed");
// 2026-09-14: own the SDL surface before any cancellation or subsequent allocation.
//   SDL_Surface *pitchSpecularSurf = CreateSDLSurface(resSpecularX, resSpecularY);
  auto pitchSpecularSurf_owner = std::unique_ptr<SDL_Surface, decltype(&SDL_FreeSurface)>(CreateSDLSurface(resSpecularX, resSpecularY), SDL_FreeSurface);
  SDL_Surface* pitchSpecularSurf = pitchSpecularSurf_owner.get();
  if (!pitchSpecularSurf) throw std::runtime_error("Pitch surface allocation or loading failed");
// 2026-09-14: own the SDL surface before any cancellation or subsequent allocation.
//   SDL_Surface *pitchNormalSurf = CreateSDLSurface(resNormalX, resNormalY);
  auto pitchNormalSurf_owner = std::unique_ptr<SDL_Surface, decltype(&SDL_FreeSurface)>(CreateSDLSurface(resNormalX, resNormalY), SDL_FreeSurface);
  SDL_Surface* pitchNormalSurf = pitchNormalSurf_owner.get();
  if (!pitchNormalSurf) throw std::runtime_error("Pitch surface allocation or loading failed");

// 2026-09-14: keep exact element initialization and arithmetic while owning temporary pixel storage.
//   Uint32 *diffuseBitmap;
//   diffuseBitmap = new Uint32[resX * resY];
  auto diffuseBitmap_owner = std::unique_ptr<Uint32[]>(new Uint32[resX * resY]);
  Uint32* diffuseBitmap = diffuseBitmap_owner.get();
// 2026-09-14: keep exact element initialization and arithmetic while owning temporary pixel storage.
//   Uint32 *specularBitmap;
//   specularBitmap = new Uint32[resSpecularX * resSpecularY];
  auto specularBitmap_owner = std::unique_ptr<Uint32[]>(new Uint32[resSpecularX * resSpecularY]);
  Uint32* specularBitmap = specularBitmap_owner.get();
// 2026-09-14: keep exact element initialization and arithmetic while owning temporary pixel storage.
//   Uint32 *normalBitmap;
//   normalBitmap = new Uint32[resNormalX * resNormalY];
  auto normalBitmap_owner = std::unique_ptr<Uint32[]>(new Uint32[resNormalX * resNormalY]);
  Uint32* normalBitmap = normalBitmap_owner.get();

  // 2026-09-14: resource generation holds the environment owner throughout.
  const float rToB = GetConfiguration()->GetReal("graphics_pitchredtoblueratio", 0.5f) * 2.0f;

  for (int x = 0; x < resX; x++) {
    GameLoadCheckpoint("pitch.diffuse");
    DO_VALIDATION;
    for (int y = 0; y < resY; y++) {
      DO_VALIDATION;
      float xCoord = x / (resX * 1.0) * pitchFullHalfW + pitchFullHalfW * offsetW;
      float yCoord = y / (resY * 1.0) * pitchFullHalfH + pitchFullHalfH * offsetH;
      // 2026-09-14: pass the immutable display setting.
      //      diffuseBitmap[y * resX + x] = GetPitchDiffuseColor(pitchDiffuseSurf, seamlessTex, perlinTex, overlayTex, overlay_alphaTex, xCoord, yCoord);
      diffuseBitmap[y * resX + x] = GetPitchDiffuseColor(pitchDiffuseSurf, seamlessTex, perlinTex, overlayTex, overlay_alphaTex, xCoord, yCoord, rToB);
    }
  }
  for (int x = 0; x < resSpecularX; x++) {
    GameLoadCheckpoint("pitch.specular");
    DO_VALIDATION;
    for (int y = 0; y < resSpecularY; y++) {
      DO_VALIDATION;
      float xSpecularCoord = x / (resSpecularX * 1.0) * pitchFullHalfW + pitchFullHalfW * offsetW;
      float ySpecularCoord = y / (resSpecularY * 1.0) * pitchFullHalfH + pitchFullHalfH * offsetH;
      specularBitmap[y * resSpecularX + x] = GetPitchSpecularColor(pitchSpecularSurf, perlinTex, xSpecularCoord, ySpecularCoord);
    }
  }
  // 2026-09-14: <= resNormalX + resNormalY cached samples; no authoritative RNG use.
  const auto normalX = PitchNormalAxis(resNormalX, pitchFullHalfW, pitchHalfW,
                                       offsetW, grassNormalRepeatMultiplier, 0.12f);
  const auto normalY = PitchNormalAxis(resNormalY, pitchFullHalfH, pitchHalfH,
                                       offsetH, grassNormalRepeatMultiplier, 0.1f);
  for (int x = 0; x < resNormalX; x++) {
    GameLoadCheckpoint("pitch.normal");
    DO_VALIDATION;
    for (int y = 0; y < resNormalY; y++) {
      DO_VALIDATION;
      // 2026-09-14: preserve pixel traversal and visual random draws exactly.
      //       float xNormalCoord = x / (resNormalX * 1.0) * pitchFullHalfW + pitchFullHalfW * offsetW;
      //       float yNormalCoord = y / (resNormalY * 1.0) * pitchFullHalfH + pitchFullHalfH * offsetH;
      //       normalBitmap[y * resNormalX + x] = GetPitchNormalColor(pitchNormalSurf, xNormalCoord, yNormalCoord, grassNormalRepeatMultiplier);
      normalBitmap[y * resNormalX + x] = GetPitchNormalColorPrepared(
          pitchNormalSurf, PitchNormalBase(normalX[x], normalY[y]));
    }
  }

  memcpy(pitchDiffuseSurf->pixels, diffuseBitmap, resX * resY * sizeof(Uint32));
  memcpy(pitchSpecularSurf->pixels, specularBitmap, resSpecularX * resSpecularY * sizeof(Uint32));
  memcpy(pitchNormalSurf->pixels, normalBitmap, resNormalX * resNormalY * sizeof(Uint32));
// 2026-09-14: preserve the successful release boundary with exception-safe ownership.
//   delete [] diffuseBitmap;
  diffuseBitmap_owner.reset();
// 2026-09-14: preserve the successful release boundary with exception-safe ownership.
//   delete [] specularBitmap;
  specularBitmap_owner.reset();
// 2026-09-14: preserve the successful release boundary with exception-safe ownership.
//   delete [] normalBitmap;
  normalBitmap_owner.reset();

  // find pitch texture

  bool alreadyThere = false;
  boost::intrusive_ptr<Resource<Texture> > pitchDiffuseTex =
      GetContext().texture_manager.Fetch("pitch_0" + int_to_str(i) + ".png",
                                         false, alreadyThere, true);
  assert(alreadyThere);
  boost::intrusive_ptr<Resource<Texture> > pitchSpecularTex =
      GetContext().texture_manager.Fetch(
          "pitch_specular_0" + int_to_str(i) + ".png", false, alreadyThere,
          true);
  assert(alreadyThere);
  boost::intrusive_ptr<Resource<Texture> > pitchNormalTex =
      GetContext().texture_manager.Fetch(
          "pitch_normal_0" + int_to_str(i) + ".png", false, alreadyThere, true);
  assert(alreadyThere);



  // overwrite pitch texture

  pitchDiffuseTex->GetResource()->DeleteTexture();
  pitchDiffuseTex->GetResource()->CreateTexture(e_InternalPixelFormat_SRGB8, e_PixelFormat_RGB, resX, resY, false, true, true, true);
  pitchDiffuseTex->GetResource()->UpdateTexture(pitchDiffuseSurf, false, true);
// 2026-09-14: release at the original successful lifetime boundary; exceptions use RAII.
//   SDL_FreeSurface(pitchDiffuseSurf);
  pitchDiffuseSurf_owner.reset();

  pitchSpecularTex->GetResource()->DeleteTexture();
  pitchSpecularTex->GetResource()->CreateTexture(e_InternalPixelFormat_RGB8, e_PixelFormat_RGB, resSpecularX, resSpecularY, false, true, true, true);
  pitchSpecularTex->GetResource()->UpdateTexture(pitchSpecularSurf, false, true);
// 2026-09-14: release at the original successful lifetime boundary; exceptions use RAII.
//   SDL_FreeSurface(pitchSpecularSurf);
  pitchSpecularSurf_owner.reset();

  pitchNormalTex->GetResource()->DeleteTexture();
  pitchNormalTex->GetResource()->CreateTexture(e_InternalPixelFormat_RGB8, e_PixelFormat_RGB, resNormalX, resNormalY, false, true, true, true);
  pitchNormalTex->GetResource()->UpdateTexture(pitchNormalSurf, false, true);
// 2026-09-14: release at the original successful lifetime boundary; exceptions use RAII.
//   SDL_FreeSurface(pitchNormalSurf);
  pitchNormalSurf_owner.reset();
}

void GeneratePitch(int resX, int resY, int resSpecularX, int resSpecularY,
                   int resNormalX, int resNormalY) {
  DO_VALIDATION;
  if (GetContext().already_loaded) {
    DO_VALIDATION;
    return;
  }
// 2026-09-14: do not publish a completed pitch until every chunk has been generated and uploaded.
//   GetContext().already_loaded = true;
  GameLoadCheckpoint("pitch.begin");

// 2026-09-14: own the SDL surface before any cancellation or subsequent allocation.
//   SDL_Surface *seamless = IMG_LoadBmp("media/textures/pitch/seamlessgrass08.png");
  auto seamless_owner = std::unique_ptr<SDL_Surface, decltype(&SDL_FreeSurface)>(IMG_LoadBmp("media/textures/pitch/seamlessgrass08.png"), SDL_FreeSurface);
  SDL_Surface* seamless = seamless_owner.get();
  if (!seamless) throw std::runtime_error("Pitch surface allocation or loading failed");
  SDL_PixelFormat seamlessFormat = *seamless->format;
  assert(seamlessTexW == seamless->w);
  assert(seamlessTexH == seamless->h);
// 2026-09-14: keep exact element initialization and arithmetic while owning temporary pixel storage.
//   Vector3 *seamlessTex = new Vector3[seamlessTexW * seamlessTexH];
  auto seamlessTex_owner = std::unique_ptr<Vector3[]>(new Vector3[seamlessTexW * seamlessTexH]);
  Vector3* seamlessTex = seamlessTex_owner.get();
  for (int x = 0; x < seamlessTexW; x++) {
    GameLoadCheckpoint("pitch.source");
    DO_VALIDATION;
    for (int y = 0; y < seamlessTexH; y++) {
      DO_VALIDATION;
      Uint32 pixel = sdl_getpixel(seamless, x, y);
      Uint8 r, g, b;
      SDL_GetRGB(pixel, &seamlessFormat, &r, &g, &b);
      seamlessTex[y * seamless->w + x] = Vector3(r, g, b);
    }
  }
// 2026-09-14: release at the original successful lifetime boundary; exceptions use RAII.
//   SDL_FreeSurface(seamless);
  seamless_owner.reset();

// 2026-09-14: own the SDL surface before any cancellation or subsequent allocation.
//   SDL_Surface *overlay = IMG_LoadBmp("media/textures/pitch/overlay.png");
  auto overlay_owner = std::unique_ptr<SDL_Surface, decltype(&SDL_FreeSurface)>(IMG_LoadBmp("media/textures/pitch/overlay.png"), SDL_FreeSurface);
  SDL_Surface* overlay = overlay_owner.get();
  if (!overlay) throw std::runtime_error("Pitch surface allocation or loading failed");
  SDL_PixelFormat overlayFormat = *overlay->format;
  assert(overlayTexW == overlay->w);
  assert(overlayTexH == overlay->h);
// 2026-09-14: keep exact element initialization and arithmetic while owning temporary pixel storage.
//   Vector3 *overlayTex = new Vector3[overlayTexW * overlayTexH];
  auto overlayTex_owner = std::unique_ptr<Vector3[]>(new Vector3[overlayTexW * overlayTexH]);
  Vector3* overlayTex = overlayTex_owner.get();
// 2026-09-14: keep exact element initialization and arithmetic while owning temporary pixel storage.
//   float* overlay_alphaTex = new float[overlayTexW * overlayTexH];
  auto overlay_alphaTex_owner = std::unique_ptr<float[]>(new float[overlayTexW * overlayTexH]);
  float* overlay_alphaTex = overlay_alphaTex_owner.get();
  for (int x = 0; x < overlayTexW; x++) {
    GameLoadCheckpoint("pitch.overlay");
    DO_VALIDATION;
    for (int y = 0; y < overlayTexH; y++) {
      DO_VALIDATION;
      Uint32 pixel = sdl_getpixel(overlay, x, y);
      Uint8 r, g, b, a;
      SDL_GetRGBA(pixel, &overlayFormat, &r, &g, &b, &a);
      overlayTex[y * overlay->w + x] = Vector3(r, g, b);
      overlay_alphaTex[y * overlay->w + x] = a / 256.0f;
      //printf("alpha: %f\n", overlay_alphaTex[y * overlay->w + x]);
    }
  }
// 2026-09-14: release at the original successful lifetime boundary; exceptions use RAII.
//   SDL_FreeSurface(overlay);
  overlay_owner.reset();

  float scale = 0.06f;

// 2026-09-14: noise generators remain owned throughout pitch generation.
//   Perlin *perlin1 = new Perlin(4, 0.06 * scale, 0.5); // low freq
  auto perlin1_owner = std::make_unique<Perlin>(4, 0.06 * scale, 0.5);
  Perlin* perlin1 = perlin1_owner.get();
// 2026-09-14: noise generators remain owned throughout pitch generation.
//   Perlin *perlin2 = new Perlin(4, 0.14 * scale, 0.5); // mid freq
  auto perlin2_owner = std::make_unique<Perlin>(4, 0.14 * scale, 0.5);
  Perlin* perlin2 = perlin2_owner.get();
//  Perlin *perlin3 = new Perlin(4, 25.4 / 20.0,   3, 423423); // high freq
// 2026-09-14: keep exact element initialization and arithmetic while owning temporary pixel storage.
//   float* perlinTex = new float[perlinTexW * perlinTexH];
  auto perlinTex_owner = std::unique_ptr<float[]>(new float[perlinTexW * perlinTexH]);
  float* perlinTex = perlinTex_owner.get();

  // make sure sines are in range -1 to 1
  // generate sine
  float noiseFactor = 0.15; // 'random grid of canals'
  float sinScale = 4.0f; // smaller is larger (heh)
  float ynoise[perlinTexH];
  for (int y = 0; y < perlinTexH; y++) {
    DO_VALIDATION;
    ynoise[y] = (std::sin(y / (float)perlinTexH * 13 * sinScale) +
                 std::sin(y / (float)perlinTexH * 43 * sinScale) +
                 std::sin(y / (float)perlinTexH * 107 * sinScale) +
                 std::sin(y / (float)perlinTexH * 245 * sinScale)) *
                0.25f;
  }

  for (int x = 0; x < perlinTexW; x++) {
    GameLoadCheckpoint("pitch.noise");
    DO_VALIDATION;
    float xnoise = (std::sin(x / (float)perlinTexW * 15 * sinScale) +
                    std::sin(x / (float)perlinTexW * 41 * sinScale) +
                    std::sin(x / (float)perlinTexW * 109 * sinScale) +
                    std::sin(x / (float)perlinTexW * 241 * sinScale)) *
                   0.25f;
    for (int y = 0; y < perlinTexH; y++) {
      DO_VALIDATION;
      float noise = xnoise * 0.65f + ynoise[y] * 0.35f;
      noise = curve(noise * 0.5f + 0.5f, 0.4f) * 2.0f - 1.0f; // compress
      //printf("%f ", perlin1->Get(x, y));
      perlinTex[y * perlinTexW + x] = perlin1->Get(x, y) * 0.4f +
                                      perlin2->Get(x, y) * 0.6f; // + 0.5f to get it from [0..1]; the multiplier is bias between the noises
      perlinTex[y * perlinTexW + x] = perlinTex[y * perlinTexW + x] * 1.7f + 0.5f; // most of perlin noise is well between -0.5 and 0.5, so expand a bit
      perlinTex[y * perlinTexW + x] += (NormalizedClamp(noise, -0.9f, 0.9f) * 2.0f - 1.0f) * noiseFactor; // cut off on both sides, for graphics effect
      perlinTex[y * perlinTexW + x] = clamp(perlinTex[y * perlinTexW + x], 0.2f, 0.8f); // clamp in range; there'll be some clipping otherwise
      perlinTex[y * perlinTexW + x] = curve(perlinTex[y * perlinTexW + x], 0.4f);
    }
  }

//  boost::thread pitchThread[4];
  // 2026-09-14: grass texture selection must not advance the authoritative simulation RNG.
  // float grassNormalRepeatMultiplier = (boostrandom(0, 1) > 0.5f) ? 1.0f : 0.5f;
  float grassNormalRepeatMultiplier = (random_non_determ(0, 1) > 0.5f) ? 1.0f : 0.5f;
  for (int i = 0; i < 4; i++) {
    DO_VALIDATION;
    CreateChunk(i + 1, resX, resY, resSpecularX, resSpecularY, resNormalX,
                resNormalY, grassNormalRepeatMultiplier, seamlessTex, perlinTex,
                overlayTex, overlay_alphaTex);
  }

  //  for (int i = 0; i < 4; i++) { DO_VALIDATION;
  // pitchThread[i].join();
  //}

// 2026-09-14: release noise generator at its original boundary.
//   delete perlin1;
  perlin1_owner.reset();
// 2026-09-14: release noise generator at its original boundary.
//   delete perlin2;
  perlin2_owner.reset();
// 2026-09-14: preserve the successful release boundary with exception-safe ownership.
//   delete [] perlinTex;
  perlinTex_owner.reset();
// 2026-09-14: preserve the successful release boundary with exception-safe ownership.
//   delete [] overlayTex;
  overlayTex_owner.reset();
// 2026-09-14: preserve the successful release boundary with exception-safe ownership.
//   delete [] overlay_alphaTex;
  overlay_alphaTex_owner.reset();
// 2026-09-14: preserve the successful release boundary with exception-safe ownership.
//   delete [] seamlessTex;
  seamlessTex_owner.reset();
  GetContext().already_loaded = true;

}
