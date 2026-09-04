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

// 2026-09-03 Phase 15: 屏幕空间反射片段着色器
// 使用光线步进实现屏幕空间反射

#version 150

#pragma optimize(on)

uniform sampler2D map_color;        // 颜色缓冲
uniform sampler2D map_normal;       // 法线缓冲
uniform sampler2D map_depth;        // 深度缓冲
uniform sampler2D map_material;     // 材质缓冲（粗糙度/金属度）

uniform mat4 projectionMatrix;
uniform mat4 viewMatrix;
uniform mat4 inverseProjectionMatrix;
uniform mat4 inverseViewMatrix;

uniform vec2 textureSize;
uniform vec3 cameraPosition;

// SSR 参数
uniform int maxSteps;               // 最大步进次数
uniform float maxDistance;           // 最大射线距离
uniform float thickness;            // 厚度阈值
uniform float fadeDistance;          // 衰减距离

out vec4 stdout;

// 深度重建位置
vec3 ReconstructPosition(vec2 texCoord, float depth) {
    vec4 clipPos = vec4(texCoord * 2.0 - 1.0, depth * 2.0 - 1.0, 1.0);
    vec4 viewPos = inverseProjectionMatrix * clipPos;
    return viewPos.xyz / viewPos.w;
}

// 屏幕空间坐标转换
vec2 ViewToScreen(vec3 viewPos) {
    vec4 clipPos = projectionMatrix * vec4(viewPos, 1.0);
    vec2 ndcPos = clipPos.xy / clipPos.w;
    return ndcPos * 0.5 + 0.5;
}

// 采样深度
float SampleDepth(vec2 texCoord) {
    return texture(map_depth, texCoord).r;
}

// 采样法线
vec3 SampleNormal(vec2 texCoord) {
    return texture(map_normal, texCoord).rgb * 2.0 - 1.0;
}

// 边缘衰减
float EdgeFade(vec2 texCoord) {
    vec2 fade = vec2(0.0);
    fade = smoothstep(vec2(0.0), vec2(0.1), texCoord);
    fade *= smoothstep(vec2(1.0), vec2(0.9), texCoord);
    return fade.x * fade.y;
}

void main() {
    vec2 texCoord = gl_FragCoord.xy / textureSize;
    
    // 采样当前像素
    float depth = SampleDepth(texCoord);
    vec3 normal = SampleNormal(texCoord);
    vec3 color = texture(map_color, texCoord).rgb;
    
    // 深度测试
    if (depth > 0.999) {
        stdout = vec4(color, 0.0);
        return;
    }
    
    // 重建视图空间位置
    vec3 viewPos = ReconstructPosition(texCoord, depth);
    
    // 反射方向（视图空间）
    vec3 viewNormal = mat3(viewMatrix) * normal;
    vec3 viewDir = normalize(-viewPos);
    vec3 reflectDir = reflect(viewDir, viewNormal);
    
    // 起始位置
    vec3 rayOrigin = viewPos;
    vec3 rayDir = reflectDir;
    
    // 光线步进
    float alpha = 0.0;
    vec2 hitTexCoord = vec2(0.0);
    
    float stepSize = maxDistance / float(maxSteps);
    vec3 currentPos = rayOrigin;
    
    for (int i = 0; i < maxSteps; i++) {
        // 步进
        currentPos += rayDir * stepSize;
        
        // 转换到屏幕空间
        vec2 currentTexCoord = ViewToScreen(currentPos);
        
        // 边界检查
        if (currentTexCoord.x < 0.0 || currentTexCoord.x > 1.0 ||
            currentTexCoord.y < 0.0 || currentTexCoord.y > 1.0) {
            break;
        }
        
        // 采样深度
        float currentDepth = SampleDepth(currentPos);
        float sampleDepth = SampleDepth(currentTexCoord);
        
        // 深度比较
        float depthDiff = currentDepth - sampleDepth;
        
        if (depthDiff > 0.0 && depthDiff < thickness) {
            // 命中
            alpha = 1.0;
            hitTexCoord = currentTexCoord;
            break;
        }
    }
    
    // 边缘衰减
    if (alpha > 0.0) {
        alpha *= EdgeFade(hitTexCoord);
        
        // 距离衰减
        float distance = length(currentPos - rayOrigin);
        alpha *= 1.0 - smoothstep(maxDistance * 0.5, maxDistance, distance);
    }
    
    // 采样反射颜色
    vec3 reflectionColor = texture(map_color, hitTexCoord).rgb;
    
    // 输出（RGB = 反射颜色, A = 反射强度）
    stdout = vec4(reflectionColor, alpha);
}
