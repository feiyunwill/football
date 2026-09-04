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

// 2026-09-03 Phase 15: 运动模糊片段着色器
// 基于速度缓冲的运动模糊

#version 150

#pragma optimize(on)

uniform sampler2D map_color;        // 颜色缓冲
uniform sampler2D map_velocity;     // 速度缓冲

uniform vec2 textureSize;
uniform float blurStrength;         // 模糊强度
uniform int samples;                // 采样次数

out vec4 stdout;

void main() {
    vec2 texCoord = gl_FragCoord.xy / textureSize;
    
    // 采样速度
    vec2 velocity = texture(map_velocity, texCoord).rg;
    
    // 速度钳制
    float speed = length(velocity);
    velocity = velocity / max(speed, 0.0001) * min(speed, 0.1);
    
    // 应用模糊强度
    velocity *= blurStrength;
    
    // 采样颜色
    vec3 color = texture(map_color, texCoord).rgb;
    
    // 沿速度方向采样
    vec2 texelSize = 1.0 / textureSize;
    float totalWeight = 1.0;
    
    for (int i = 1; i < samples; i++) {
        vec2 offset = velocity * (float(i) / float(samples - 1));
        vec2 sampleCoord = texCoord + offset;
        
        // 边界检查
        sampleCoord = clamp(sampleCoord, vec2(0.0), vec2(1.0));
        
        // 采样并累加
        color += texture(map_color, sampleCoord).rgb;
        totalWeight += 1.0;
    }
    
    // 平均化
    color /= totalWeight;
    
    stdout = vec4(color, 1.0);
}
