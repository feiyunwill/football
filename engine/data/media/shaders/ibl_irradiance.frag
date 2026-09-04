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

// 2026-09-03 Phase 12: 辐照度贴图片段着色器
// 用于将 HDR 环境贴图卷积为漫反射辐照度贴图
// 基于 Importon 的方法：https://learnopengl.com/IBL/Diffuse-irradiance

#version 150

#pragma optimize(on)

const float PI = 3.14159265359;

uniform samplerCube environmentMap;
uniform float sampleDelta;

in vec3 WorldPos;
out vec4 FragColor;

void main() {
    // 法线方向（从立方体贴图坐标获取）
    vec3 N = normalize(WorldPos);
    
    // 创建切线空间基向量
    vec3 up = vec3(0.0, 1.0, 0.0);
    vec3 right = normalize(cross(up, N));
    up = normalize(cross(N, right));
    
    float sampleCount = 0.0;
    vec3 irradiance = vec3(0.0);
    
    // 半球积分（漫反射辐照度）
    // 使用球面坐标采样
    for (float phi = 0.0; phi < 2.0 * PI; phi += sampleDelta) {
        for (float theta = 0.0; theta < 0.5 * PI; theta += sampleDelta) {
            // 球面坐标转笛卡尔坐标
            vec3 tangentSample = vec3(
                sin(theta) * cos(phi),
                sin(theta) * sin(phi),
                cos(theta)
            );
            
            // 切线空间转世界空间
            vec3 sampleVec = tangentSample.x * right + tangentSample.y * up + tangentSample.z * N;
            
            // 从环境贴图采样
            irradiance += texture(environmentMap, sampleVec).rgb * cos(theta) * sin(theta);
            sampleCount += 1.0;
        }
    }
    
    // 归一化
    irradiance = PI * irradiance * (1.0 / float(sampleCount));
    
    FragColor = vec4(irradiance, 1.0);
}
