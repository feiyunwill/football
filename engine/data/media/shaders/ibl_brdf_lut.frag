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
in vec2 TexCoords;
out vec2 FragColor;
float radicalInverse(uint bits) {
    bits = (bits << 16u) | (bits >> 16u);
    bits = ((bits & 0x55555555u) << 1u) | ((bits & 0xAAAAAAAAu) >> 1u);
    bits = ((bits & 0x33333333u) << 2u) | ((bits & 0xCCCCCCCCu) >> 2u);
    bits = ((bits & 0x0F0F0F0Fu) << 4u) | ((bits & 0xF0F0F0F0u) >> 4u);
    bits = ((bits & 0x00FF00FFu) << 8u) | ((bits & 0xFF00FF00u) >> 8u);
    return float(bits) * 2.3283064365386963e-10;
}
vec2 hammersley(uint i, uint count) {
    return vec2(float(i) / float(count), radicalInverse(i));
}
vec3 importanceSampleGGX(vec2 xi, vec3 N, float roughness) {
    float a = roughness * roughness;
    float phi = 6.28318530718 * xi.x;
    float cosTheta = sqrt((1.0 - xi.y) / max(1.0 + (a*a - 1.0)*xi.y, 1e-6));
    float sinTheta = sqrt(max(1.0 - cosTheta*cosTheta, 0.0));
    vec3 H = vec3(cos(phi)*sinTheta, sin(phi)*sinTheta, cosTheta);
    vec3 up = abs(N.z) < 0.999 ? vec3(0,0,1) : vec3(1,0,0);
    vec3 T = normalize(cross(up, N));
    vec3 B = cross(N, T);
    return normalize(T*H.x + B*H.y + N*H.z);
}
float distributionGGX(float NdotH, float roughness) {
    float a = max(roughness*roughness, 0.001);
    float a2 = a*a;
    float d = NdotH*NdotH*(a2-1.0)+1.0;
    return a2 / max(3.14159265359*d*d, 1e-7);
}

float geometrySchlickGGX(float value, float roughness) {
    float k = (roughness+1.0)*(roughness+1.0)/8.0;
    return value/max(value*(1.0-k)+k,1e-6);
}
void main() {
    float NdotV = clamp(TexCoords.x,1e-4,1.0);
    float roughness = clamp(TexCoords.y,0.045,1.0);
    vec3 N = vec3(0,0,1);
    vec3 V = vec3(sqrt(max(1.0-NdotV*NdotV,0.0)),0,NdotV);
    float A = 0.0;
    float B = 0.0;
    const uint count = 256u;
    for (uint i=0u;i<count;++i) {
        vec3 H = importanceSampleGGX(hammersley(i,count),N,roughness);
        vec3 L = normalize(2.0*dot(V,H)*H-V);
        float NdotL = max(L.z,0.0);
        if (NdotL <= 0.0) continue;
        float NdotH = max(H.z,0.0);
        float VdotH = max(dot(V,H),0.0);
        float G = geometrySchlickGGX(NdotL,roughness)*
                  geometrySchlickGGX(NdotV,roughness);
        float visibility = (G*VdotH)/max(NdotH*NdotV,1e-5);
        float fresnel = pow(1.0-VdotH,5.0);
        A += (1.0-fresnel)*visibility;
        B += fresnel*visibility;
    }
    FragColor = vec2(A,B)/float(count);
}
