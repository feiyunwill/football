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

// 2026-09-03 Phase 15: Bloom 高斯模糊片段着色器
// 双向高斯模糊用于 Bloom 效果

#version 150

#pragma optimize(on)

uniform sampler2D map_texture;
uniform vec2 direction;             // 模糊方向 (1,0) 水平, (0,1) 垂直
uniform vec2 textureSize;           // 纹理尺寸

out vec4 stdout;

// Adjacent Gaussian taps share a bilinear fetch on the linear-filtered Bloom
// texture: five reads reproduce the nine-tap kernel up to texture precision.
const float centerWeight = 0.227027;
const float pairWeight[2] = float[](0.3162162, 0.07027);
const float pairOffset[2] = float[](1.384615336, 3.230767041);

void main() {
    vec2 texCoord = gl_FragCoord.xy / textureSize;
    
    vec3 result = texture(map_texture, texCoord).rgb * centerWeight;
    for (int i = 0; i < 2; ++i) {
        vec2 offset = direction * pairOffset[i] / textureSize;
        result += (texture(map_texture, texCoord + offset).rgb +
                   texture(map_texture, texCoord - offset).rgb) * pairWeight[i];
    }
    
    stdout = vec4(result, 1.0);
}
