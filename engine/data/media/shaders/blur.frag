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

// 高斯权重 (5x5)
const float weight[5] = float[](0.227027, 0.1945946, 0.1216216, 0.054054, 0.016216);

void main() {
    vec2 texCoord = gl_FragCoord.xy / textureSize;
    
    // 中心采样
    vec3 result = texture(map_texture, texCoord).rgb * weight[0];
    
    // 双向采样
    vec2 offset = direction / textureSize;
    
    // 正方向采样
    for (int i = 1; i < 5; i++) {
        vec2 sampleCoord = texCoord + offset * float(i);
        result += texture(map_texture, sampleCoord).rgb * weight[i];
    }
    
    // 负方向采样
    for (int i = 1; i < 5; i++) {
        vec2 sampleCoord = texCoord - offset * float(i);
        result += texture(map_texture, sampleCoord).rgb * weight[i];
    }
    
    stdout = vec4(result, 1.0);
}
