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

// 2026-09-03 Phase 14: 级联阴影贴图采样着色器
// 从多个级联阴影贴图中采样并混合

#version 150

#pragma optimize(on)

const int MAX_CASCADES = 4;

// 纹理
uniform sampler2DArray shadowMapArray;    // 级联阴影贴图数组
uniform sampler2D map_normal;            // 法线贴图

// 级联参数
uniform vec4 cascadeSplits;              // 级联分割点
uniform mat4 cascadeViewProj[MAX_CASCADES]; // 级联视图投影矩阵
uniform float shadowMapSize;             // 阴影贴图尺寸
uniform float shadowBias;                // 阴影偏移
uniform float normalBias;                // 法线偏移

// 相机参数
uniform vec3 cameraPosition;
uniform vec3 lightDirection;

// 输入
in vec3 WorldPos;
in vec3 Normal;
in vec2 TexCoords;

// 输出
out float ShadowFactor;

// 软阴影参数
const int PCF_SAMPLES = 4;
const float PCF_RADIUS = 1.5;

// 计算级联索引
int CalculateCascadeIndex(vec4 viewPos) {
    for (int i = 0; i < MAX_CASCADES; i++) {
        if (viewPos.z < cascadeSplits[i]) {
            return i;
        }
    }
    return MAX_CASCADES - 1;
}

// 透视投影变换
vec3 ProjectOrtho(vec3 pos, mat4 proj) {
    vec4 clipPos = proj * vec4(pos, 1.0);
    return clipPos.xyz / clipPos.w;
}

// PCF 软阴影采样
float SampleShadowMapPCF(sampler2DArray shadowMap, vec3 projCoords, int cascadeIndex, float bias) {
    float shadow = 0.0;
    vec2 texelSize = 1.0 / vec2(shadowMapSize);
    
    // 3x3 PCF 采样
    for (int x = -1; x <= 1; x++) {
        for (int y = -1; y <= 1; y++) {
            vec2 offset = vec2(x, y) * texelSize;
            vec3 sampleCoord = vec3(projCoords.xy + offset, float(cascadeIndex));
            float closestDepth = texture(shadowMap, sampleCoord).r;
            shadow += (projCoords.z - bias > closestDepth) ? 1.0 : 0.0;
        }
    }
    
    return shadow / 9.0;
}

// 软阴影边缘平滑
float SmoothShadow(float shadow) {
    return shadow * shadow * (3.0 - 2.0 * shadow); // smoothstep
}

void main() {
    // 计算法线偏移
    vec3 N = normalize(Normal);
    vec3 offsetWorldPos = WorldPos + N * normalBias;
    
    // 计算视图空间位置
    vec4 viewPos = cascadeViewProj[0] * vec4(offsetWorldPos, 1.0);
    viewPos.z = -viewPos.z; // 转换为正深度
    
    // 计算级联索引
    int cascadeIndex = CalculateCascadeIndex(viewPos);
    
    // 计算投影坐标
    vec4 clipPos = cascadeViewProj[cascadeIndex] * vec4(offsetWorldPos, 1.0);
    vec3 projCoords = clipPos.xyz / clipPos.w;
    
    // 转换到 [0, 1] 范围
    projCoords = projCoords * 0.5 + 0.5;
    
    // 深度偏移
    float bias = shadowBias * tan(acos(dot(N, lightDirection)));
    bias = clamp(bias, 0.001, 0.01);
    
    // PCF 软阴影
    float shadow = SampleShadowMapPCF(shadowMapArray, projCoords, cascadeIndex, bias);
    
    // 边缘平滑
    shadow = SmoothShadow(shadow);
    
    // 级联混合（在分割点附近）
    if (cascadeIndex < MAX_CASCADES - 1) {
        float splitDist = cascadeSplits[cascadeIndex];
        float nextSplitDist = cascadeSplits[cascadeIndex + 1];
        float blendFactor = (viewPos.z - splitDist) / (nextSplitDist - splitDist);
        
        if (blendFactor > 0.8) {
            // 采样下一个级联
            vec4 nextClipPos = cascadeViewProj[cascadeIndex + 1] * vec4(offsetWorldPos, 1.0);
            vec3 nextProjCoords = nextClipPos.xyz / nextClipPos.w;
            nextProjCoords = nextProjCoords * 0.5 + 0.5;
            
            float nextShadow = SampleShadowMapPCF(shadowMapArray, nextProjCoords, cascadeIndex + 1, bias);
            nextShadow = SmoothShadow(nextShadow);
            
            // 混合
            shadow = mix(shadow, nextShadow, (blendFactor - 0.8) / 0.2);
        }
    }
    
    // 输出阴影因子（1.0 = 完全光照，0.0 = 完全阴影）
    ShadowFactor = 1.0 - shadow;
}
