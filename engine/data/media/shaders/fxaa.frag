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

// 2026-09-03 Phase 15: FXAA 抗锯齿片段着色器
// Fast Approximate Anti-Aliasing

#version 150

#pragma optimize(on)

uniform sampler2D map_texture;
uniform vec2 textureSize;

// FXAA 参数
uniform float fxaaReduceMin;        // 最小减少量
uniform float fxaaReduceMul;        // 减少乘数
uniform float fxaaSpanMax;          // 最大跨度

out vec4 stdout;

// 亮度计算
float Luminance(vec3 color) {
    return dot(color, vec3(0.299, 0.587, 0.114));
}

void main() {
    vec2 texCoord = gl_FragCoord.xy / textureSize;
    vec2 texelSize = 1.0 / textureSize;
    
    // 采样 3x3 邻域
    vec3 rgbNW = texture(map_texture, texCoord + vec2(-1.0, -1.0) * texelSize).rgb;
    vec3 rgbNE = texture(map_texture, texCoord + vec2( 1.0, -1.0) * texelSize).rgb;
    vec3 rgbSW = texture(map_texture, texCoord + vec2(-1.0,  1.0) * texelSize).rgb;
    vec3 rgbSE = texture(map_texture, texCoord + vec2( 1.0,  1.0) * texelSize).rgb;
    vec3 rgbM  = texture(map_texture, texCoord).rgb;
    
    // 计算亮度
    float lumaNW = Luminance(rgbNW);
    float lumaNE = Luminance(rgbNE);
    float lumaSW = Luminance(rgbSW);
    float lumaSE = Luminance(rgbSE);
    float lumaM  = Luminance(rgbM);
    
    // 计算亮度范围
    float lumaMin = min(lumaM, min(min(lumaNW, lumaNE), min(lumaSW, lumaSE)));
    float lumaMax = max(lumaM, max(max(lumaNW, lumaNE), max(lumaSW, lumaSE)));
    
    // 计算边缘方向
    vec2 dir;
    dir.x = -((lumaNW + lumaNE) - (lumaSW + lumaSE));
    dir.y =  ((lumaNW + lumaSW) - (lumaNE + lumaSE));
    
    // 归一化方向
    float dirReduce = max((lumaNW + lumaNE + lumaSW + lumaSE) * (0.25 * fxaaReduceMul), fxaaReduceMin);
    float rcpDirMin = 1.0 / (min(abs(dir.x), abs(dir.y)) + dirReduce);
    dir = min(vec2(fxaaSpanMax), max(vec2(-fxaaSpanMax), dir * rcpDirMin)) * texelSize;
    
    // 采样两个方向
    vec3 rgbA = 0.5 * (
        texture(map_texture, texCoord + dir * (1.0/3.0 - 0.5)).rgb +
        texture(map_texture, texCoord + dir * (2.0/3.0 - 0.5)).rgb
    );
    
    vec3 rgbB = rgbA * 0.5 + 0.25 * (
        texture(map_texture, texCoord + dir * -0.5).rgb +
        texture(map_texture, texCoord + dir *  0.5).rgb
    );
    
    // 计算新亮度
    float lumaB = Luminance(rgbB);
    
    // 边缘检测
    if (lumaB < lumaMin || lumaB > lumaMax) {
        // 使用第一个采样
        stdout = vec4(rgbA, 1.0);
    } else {
        // 使用第二个采样
        stdout = vec4(rgbB, 1.0);
    }
}
