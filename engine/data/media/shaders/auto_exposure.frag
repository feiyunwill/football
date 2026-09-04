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

// 2026-09-03 Phase 13: 自动曝光亮度计算着色器
// 计算场景平均亮度用于自动曝光

#version 150

#pragma optimize(on)

uniform sampler2D map_hdr;          // HDR 颜色缓冲

uniform float contextWidth;
uniform float contextHeight;
uniform float contextX;
uniform float contextY;

uniform float minExposure;          // 最小曝光值
uniform float maxExposure;          // 最大曝光值
uniform float adaptationSpeed;      // 适应速度

out vec4 stdout;

// 亮度计算
float Luminance(vec3 color) {
    return dot(color, vec3(0.2126, 0.7152, 0.0722));
}

void main() {
    vec2 texCoord = gl_FragCoord.xy;
    texCoord.x -= contextX;
    texCoord.y -= contextY;
    texCoord.x /= contextWidth;
    texCoord.y /= contextHeight;
    
    // 降采样采样（1/16 分辨率）
    vec2 sampleSize = vec2(16.0);
    vec2 sampleStep = sampleSize / vec2(contextWidth, contextHeight);
    
    float totalLuminance = 0.0;
    float sampleCount = 0.0;
    
    // 采样 4x4 区域
    for (float x = 0.0; x < 4.0; x += 1.0) {
        for (float y = 0.0; y < 4.0; y += 1.0) {
            vec2 sampleCoord = texCoord + vec2(x, y) * sampleStep;
            vec3 color = texture(map_hdr, sampleCoord).rgb;
            totalLuminance += Luminance(color);
            sampleCount += 1.0;
        }
    }
    
    // 计算平均亮度
    float avgLuminance = totalLuminance / sampleCount;
    
    // 对数平均亮度（避免极端值）
    float logAvgLuminance = exp(avgLuminance);
    
    // 计算曝光值（EV100）
    // EV100 = log2(L * S / C)
    // S = ISO 100, C = 12.5 (18% 灰卡)
    float exposureValue = log2(logAvgLuminance * 100.0 / 12.5);
    
    // 将 EV100 转换为线性曝光
    float exposure = 1.0 / pow(2.0, exposureValue);
    
    // 限制曝光范围
    exposure = clamp(exposure, minExposure, maxExposure);
    
    // 输出曝光值到 R 通道
    stdout = vec4(exposure, avgLuminance, logAvgLuminance, 1.0);
}
