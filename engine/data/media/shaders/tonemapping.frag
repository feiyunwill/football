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

// 2026-09-03 Phase 13: 色调映射着色器
// 支持多种色调映射算子

#version 150

#pragma optimize(on)

uniform sampler2D map_hdr;          // HDR 颜色缓冲
uniform sampler2D map_bloom;        // 泛光纹理（可选）
uniform sampler2D map_depth;        // 深度纹理

uniform float contextWidth;
uniform float contextHeight;
uniform float contextX;
uniform float contextY;

uniform float exposure;             // 曝光值
uniform float bloomStrength;        // 泛光强度
uniform int toneMappingOperator;    // 色调映射算子 (0=Reinhard, 1=ACES, 2=Uncharted2, 3=Filmic)

out vec4 stdout;

// ============================================
// Reinhard 色调映射
// ============================================
vec3 ReinhardToneMapping(vec3 color) {
    return color / (color + vec3(1.0));
}

// ============================================
// ACES 色调映射 (Academy Color Encoding System)
// ============================================
vec3 ACESToneMapping(vec3 color) {
    // ACES 拟合曲线
    const float a = 2.51;
    const float b = 0.03;
    const float c = 2.43;
    const float d = 0.59;
    const float e = 0.14;
    
    return clamp((color * (a * color + b)) / (color * (c * color + d) + e), 0.0, 1.0);
}

// ============================================
// Uncharted 2 色调映射 (Hable)
// ============================================
vec3 Uncharted2Partial(vec3 x) {
    float A = 0.15;
    float B = 0.50;
    float C = 0.10;
    float D = 0.20;
    float E = 0.02;
    float F = 0.30;
    return ((x * (A * x + C * B) + D * E) / (x * (A * x + B) + D * F)) - E / F;
}

vec3 Uncharted2ToneMapping(vec3 color) {
    float W = 11.2;
    vec3 curr = Uncharted2Partial(color * exposure);
    vec3 whiteScale = vec3(1.0) / Uncharted2Partial(vec3(W));
    return curr * whiteScale;
}

// ============================================
// Filmic 色调映射 (Jim Hejl)
// ============================================
vec3 FilmicToneMapping(vec3 color) {
    vec3 x = max(vec3(0.0), color - 0.004);
    return (x * (6.2 * x + 0.5)) / (x * (6.2 * x + 1.7) + 0.06);
}

// ============================================
// Gamma 校正
// ============================================
vec3 GammaCorrection(vec3 color, float gamma) {
    return pow(color, vec3(1.0 / gamma));
}

// ============================================
// 亮度计算
// ============================================
float Luminance(vec3 color) {
    return dot(color, vec3(0.2126, 0.7152, 0.0722));
}

void main() {
    vec2 texCoord = gl_FragCoord.xy;
    texCoord.x -= contextX;
    texCoord.y -= contextY;
    texCoord.x /= contextWidth;
    texCoord.y /= contextHeight;
    
    // 采样 HDR 颜色
    vec3 hdrColor = texture(map_hdr, texCoord).rgb;
    
    // 应用曝光
    vec3 color = hdrColor * exposure;
    
    // 添加泛光（如果有）
    if (bloomStrength > 0.0) {
        vec3 bloom = texture(map_bloom, texCoord).rgb;
        color += bloom * bloomStrength;
    }
    
    // 色调映射
    switch (toneMappingOperator) {
        case 0: // Reinhard
            color = ReinhardToneMapping(color);
            break;
        case 1: // ACES
            color = ACESToneMapping(color);
            break;
        case 2: // Uncharted 2
            color = Uncharted2ToneMapping(color);
            break;
        case 3: // Filmic
            color = FilmicToneMapping(color);
            break;
        default:
            color = ReinhardToneMapping(color);
            break;
    }
    
    // Gamma 校正
    color = GammaCorrection(color, 2.2);
    
    // 深度测试（背景填充）
    float depth = texture(map_depth, texCoord).x;
    if (depth > 0.999) {
        color = vec3(0.85, 0.85, 0.9); // 天空颜色
    }
    
    stdout = vec4(color, 1.0);
}
