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

// GPU-only scene metering with deterministic per-render adaptation.
#version 150

uniform sampler2D map_hdr;
uniform sampler2D map_previousExposure;
uniform float minExposure;
uniform float maxExposure;
uniform float adaptationFactor;
out vec4 stdout;

void main() {
    // A stratified 16x16 sample avoids a CPU readback and handles HDR outliers
    // with geometric-mean luminance rather than arithmetic averaging.
    float logSum = 0.0;
    for (int y = 0; y < 16; ++y) {
        for (int x = 0; x < 16; ++x) {
            vec2 uv = (vec2(x, y) + vec2(0.5)) / 16.0;
            vec3 color = max(texture(map_hdr, uv).rgb, vec3(0.0));
            float luminance = max(dot(color,
                vec3(0.2126, 0.7152, 0.0722)), 0.0001);
            logSum += log(luminance);
        }
    }
    float averageLuminance = exp(logSum / 256.0);
    float target = clamp(0.18 / averageLuminance,
                         minExposure, maxExposure);
    float previous = clamp(
        texture(map_previousExposure, vec2(0.5)).r,
        minExposure, maxExposure);
    float adapted = mix(previous, target,
                        clamp(adaptationFactor, 0.0, 1.0));
    stdout = vec4(adapted, target, averageLuminance, 1.0);
}
