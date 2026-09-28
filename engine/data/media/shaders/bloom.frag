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

// Extract linear HDR highlights before the separable half-resolution blur.
#version 150

uniform sampler2D map_hdr;
uniform vec2 outputSize;
uniform float bloomThreshold;
out vec4 stdout;

void main() {
    vec2 texCoord = gl_FragCoord.xy / outputSize;
    vec3 hdr = texture(map_hdr, texCoord).rgb;
    float luminance = dot(hdr, vec3(0.2126, 0.7152, 0.0722));
    float fraction = max(luminance - bloomThreshold, 0.0)
                   / max(luminance, 0.0001);
    stdout = vec4(hdr * fraction, 1.0);
}
