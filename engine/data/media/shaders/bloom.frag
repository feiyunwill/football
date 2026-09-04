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

// 2026-09-03 Phase 15: Bloom 合成片段着色器
// 将 Bloom 效果与原始图像合成

#version 150

#pragma optimize(on)

uniform sampler2D map_hdr;          // HDR 原始图像
uniform sampler2D map_bloom;        // Bloom 模糊图像

uniform float bloomStrength;        // Bloom 强度
uniform float bloomThreshold;       // Bloom 阈值
uniform float bloomClamp;           // Bloom 钳制值

out vec4 stdout;

// 亮度计算
float Luminance(vec3 color) {
    return dot(color, vec3(0.2126, 0.7152, 0.0722));
}

// 提取高亮区域
vec3 ExtractBright(vec3 color, float threshold) {
    float brightness = Luminance(color);
    float contribution = max(brightness - threshold, 0.0);
    return color * (contribution / max(brightness, 0.0001));
}

// 色调映射（ACES）
vec3 ACESToneMapping(vec3 color) {
    const float a = 2.51;
    const float b = 0.03;
    const float c = 2.43;
    const float d = 0.59;
    const float e = 0.14;
    return clamp((color * (a * color + b)) / (color * (c * color + d) + e), 0.0, 1.0);
}

// Gamma 校正
vec3 GammaCorrection(vec3 color, float gamma) {
    return pow(color, vec3(1.0 / gamma));
}

void main() {
    vec2 texCoord = gl_FragCoord.xy / vec2(textureSize(map_hdr, 0));
    
    // 采样原始图像
    vec3 hdrColor = texture(map_hdr, texCoord).rgb;
    
    // 采样 Bloom 图像
    vec3 bloomColor = texture(map_bloom, texCoord).rgb;
    
    // 提取高亮区域（用于 Bloom）
    vec3 brightColor = ExtractBright(hdrColor, bloomThreshold);
    
    // 合成 Bloom
    vec3 result = hdrColor + bloomColor * bloomStrength;
    
    // 钳制 Bloom 强度
    float bloomAmount = Luminance(bloomColor);
    if (bloomAmount > bloomClamp) {
        result = hdrColor + bloomColor * (bloomClamp / bloomAmount);
    }
    
    // 色调映射
    result = ACESToneMapping(result);
    
    // Gamma 校正
    result = GammaCorrection(result, 2.2);
    
    stdout = vec4(result, 1.0);
}
