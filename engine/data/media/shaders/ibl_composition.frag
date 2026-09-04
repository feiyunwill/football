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

// 2026-09-03 Phase 12: IBL 合成片段着色器
// 组合漫反射辐照度、镜面反射和 BRDF 查找表

#version 150

#pragma optimize(on)

const float PI = 3.14159265359;
const uint MAX_REFLECTION_LOD = 4u;

// 纹理
uniform samplerCube irradianceMap;    // 漫反射辐照度贴图
uniform samplerCube prefilterMap;     // 预滤波镜面反射贴图
uniform sampler2D brdfLUT;           // BRDF 查找表
uniform sampler2D map_albedo;        // 反照率
uniform sampler2D map_normal;        // 法线
uniform sampler2D map_metallic;      // 金属度
uniform sampler2D map_roughness;     // 粗糙度
uniform sampler2D map_ao;            // 环境光遮蔽

// 相机
uniform vec3 cameraPosition;

// 输入
in vec3 WorldPos;
in vec3 Normal;
in vec2 TexCoords;

// 输出
out vec4 FragColor;

// 菲涅尔方程（Schlick approximation）
vec3 fresnelSchlick(float cosTheta, vec3 F0) {
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}

// 带粗糙度的菲涅尔方程
vec3 fresnelSchlickRoughness(float cosTheta, vec3 F0, float roughness) {
    return F0 + (max(vec3(1.0 - roughness), F0) - F0) * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}

// 法线贴图
vec3 GetNormalFromMap() {
    vec3 normal = texture(map_normal, TexCoords).rgb;
    normal = normalize(normal * 2.0 - 1.0);
    
    vec3 Q1 = dFdx(WorldPos);
    vec3 Q2 = dFdy(WorldPos);
    vec2 st1 = dFdx(TexCoords);
    vec2 st2 = dFdy(TexCoords);
    
    vec3 N = normalize(Normal);
    vec3 T = normalize(Q1 * st2.t - Q2 * st1.t);
    vec3 B = -normalize(cross(N, T));
    mat3 TBN = mat3(T, B, N);
    
    return normalize(TBN * normal);
}

void main() {
    // 采样材质参数
    vec3 albedo = pow(texture(map_albedo, TexCoords).rgb, vec3(2.2)); // sRGB -> Linear
    float metallic = texture(map_metallic, TexCoords).r;
    float roughness = texture(map_roughness, TexCoords).r;
    float ao = texture(map_ao, TexCoords).r;
    
    // 法线
    vec3 N = GetNormalFromMap();
    
    // 视线方向
    vec3 V = normalize(cameraPosition - WorldPos);
    float NdotV = max(dot(N, V), 0.0);
    
    // 菲涅尔系数（非金属基础反射率）
    vec3 F0 = vec3(0.04);
    F0 = mix(F0, albedo, metallic);
    
    // ============================================
    // IBL 漫反射
    // ============================================
    vec3 F = fresnelSchlickRoughness(NdotV, F0, roughness);
    vec3 kD = (1.0 - F) * (1.0 - metallic);
    
    vec3 irradiance = texture(irradianceMap, N).rgb;
    vec3 diffuse = irradiance * albedo;
    
    // ============================================
    // IBL 镜面反射
    // ============================================
    vec3 R = reflect(-V, N);
    vec3 prefilteredColor = textureLod(prefilterMap, R, roughness * float(MAX_REFLECTION_LOD)).rgb;
    vec2 brdf = texture(brdfLUT, vec2(NdotV, roughness)).rg;
    vec3 specular = prefilteredColor * (F * brdf.x + brdf.y);
    
    // ============================================
    // 组合
    // ============================================
    vec3 ambient = (kD * diffuse + specular) * ao;
    
    // HDR 色调映射（Reinhard）
    vec3 color = ambient;
    color = color / (color + vec3(1.0));
    
    // Gamma 校正
    color = pow(color, vec3(1.0 / 2.2));
    
    FragColor = vec4(color, 1.0);
}
