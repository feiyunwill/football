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

// 2026-09-03 Phase 14: 方差阴影贴图着色器
// 使用 VSM 实现软阴影

#version 150

#pragma optimize(on)

uniform sampler2D shadowMap;           // 阴影贴图
uniform sampler2D map_normal;         // 法线贴图

uniform mat4 lightViewProjMatrix;     // 灯光视图投影矩阵
uniform vec3 lightDirection;          // 灯光方向
uniform float shadowBias;             // 阴影偏移
uniform float varianceBias;           // 方差偏移

uniform vec3 cameraPosition;

in vec3 WorldPos;
in vec3 Normal;
in vec2 TexCoords;

out float ShadowFactor;

// 亮度计算
float Luminance(vec3 color) {
    return dot(color, vec3(0.2126, 0.7152, 0.0722));
}

// 方差阴影映射
float VarianceShadowMap(vec2 moments, float depth) {
    // 单侧切比雪夫不等式
    float p = step(depth, moments.x);
    float variance = max(moments.y - moments.x * moments.x, 0.00002);
    
    // 软阴影
    float d = depth - moments.x;
    float pMax = variance / (variance + d * d);
    
    // 偏移调整
    pMax = smoothstep(0.2, 1.0, pMax);
    
    return min(max(p, pMax), 1.0);
}

// 指数方差阴影映射
float ExponentialVarianceShadowMap(vec2 moments, float depth) {
    float p = exp(-shadowBias * depth);
    float variance = max(moments.y - moments.x * moments.x, 0.00002);
    
    // 软阴影
    float d = depth - moments.x;
    float pMax = variance / (variance + d * d);
    
    return min(max(p, pMax), 1.0);
}

void main() {
    // 计算法线
    vec3 N = normalize(Normal);
    
    // 法线偏移
    vec3 offsetWorldPos = WorldPos + N * 0.01;
    
    // 投影到灯光空间
    vec4 lightClipPos = lightViewProjMatrix * vec4(offsetWorldPos, 1.0);
    vec3 projCoords = lightClipPos.xyz / lightClipPos.w;
    projCoords = projCoords * 0.5 + 0.5;
    
    // 采样阴影贴图（存储深度和深度平方）
    vec2 moments = texture(shadowMap, projCoords.xy).rg;
    
    // 当前深度
    float currentDepth = projCoords.z;
    
    // 方差阴影映射
    float shadow = VarianceShadowMap(moments, currentDepth);
    
    // 输出阴影因子
    ShadowFactor = shadow;
}
