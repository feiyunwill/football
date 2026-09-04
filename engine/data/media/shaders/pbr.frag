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

// 2026-09-03 Phase 12: PBR 片段着色器
// Cook-Torrance BRDF 实现

#version 150

#pragma optimize(on)

// PBR 材质参数
uniform sampler2D map_albedo;      // 反照率
uniform sampler2D map_normal;      // 法线
uniform sampler2D map_metallic;    // 金属度
uniform sampler2D map_roughness;   // 粗糙度
uniform sampler2D map_ao;          // 环境光遮蔽

// 光照参数
uniform vec3 lightPosition;
uniform vec3 lightColor;
uniform float lightRadius;
uniform vec3 cameraPosition;

// 常量
const float PI = 3.14159265359;

// 输入
in vec3 WorldPos;
in vec3 Normal;
in vec2 TexCoords;

// 输出
out vec4 FragColor;

// ============================================
// 法线分布函数 (GGX/Trowbridge-Reitz)
// ============================================
float DistributionGGX(vec3 N, vec3 H, float roughness) {
    float a = roughness * roughness;
    float a2 = a * a;
    float NdotH = max(dot(N, H), 0.0);
    float NdotH2 = NdotH * NdotH;
    
    float num = a2;
    float denom = (NdotH2 * (a2 - 1.0) + 1.0);
    denom = PI * denom * denom;
    
    return num / denom;
}

// ============================================
// 几何函数 (Schlick-GGX)
// ============================================
float GeometrySchlickGGX(float NdotV, float roughness) {
    float r = (roughness + 1.0);
    float k = (r * r) / 8.0;
    
    float num = NdotV;
    float denom = NdotV * (1.0 - k) + k;
    
    return num / denom;
}

float GeometrySmith(vec3 N, vec3 V, vec3 L, float roughness) {
    float NdotV = max(dot(N, V), 0.0);
    float NdotL = max(dot(N, L), 0.0);
    float ggx2 = GeometrySchlickGGX(NdotV, roughness);
    float ggx1 = GeometrySchlickGGX(NdotL, roughness);
    
    return ggx1 * ggx2;
}

// ============================================
// 菲涅尔方程 (Schlick approximation)
// ============================================
vec3 fresnelSchlick(float cosTheta, vec3 F0) {
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}

// ============================================
// 法线贴图
// ============================================
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
    
    // ============================================
    // 计算直接光照 (Cook-Torrance BRDF)
    // ============================================
    
    // 光源方向
    vec3 L = normalize(lightPosition - WorldPos);
    
    // 半程向量
    vec3 H = normalize(V + L);
    
    // 光源衰减
    float distance = length(lightPosition - WorldPos);
    float attenuation = max(0.0, lightRadius - distance) / lightRadius;
    attenuation = attenuation * attenuation;
    vec3 radiance = lightColor * attenuation;
    
    // 菲涅尔系数（非金属基础反射率）
    vec3 F0 = vec3(0.04);
    F0 = mix(F0, albedo, metallic);
    
    // Cook-Torrance BRDF
    float NDF = DistributionGGX(N, H, roughness);
    float G = GeometrySmith(N, V, L, roughness);
    vec3 F = fresnelSchlick(max(dot(H, V), 0.0), F0);
    
    // 镜面反射
    vec3 numerator = NDF * G * F;
    float denominator = 4.0 * max(dot(N, V), 0.0) * max(dot(N, L), 0.0) + 0.0001;
    vec3 specular = numerator / denominator;
    
    // 能量守恒
    vec3 kS = F;
    vec3 kD = vec3(1.0) - kS;
    kD *= 1.0 - metallic;
    
    // 漫反射
    float NdotL = max(dot(N, L), 0.0);
    vec3 diffuse = kD * albedo / PI;
    
    // 直接光照贡献
    vec3 Lo = (diffuse + specular) * radiance * NdotL;
    
    // ============================================
    // 环境光照（简化版）
    // ============================================
    vec3 ambient = vec3(0.03) * albedo * ao;
    
    // 总颜色
    vec3 color = ambient + Lo;
    
    // HDR 色调映射（Reinhard）
    color = color / (color + vec3(1.0));
    
    // Gamma 校正
    color = pow(color, vec3(1.0 / 2.2));
    
    FragColor = vec4(color, 1.0);
}
