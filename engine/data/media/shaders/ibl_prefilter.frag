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
uniform samplerCube environmentMap;
uniform int faceIndex;
uniform float roughness;
uniform float resolution;
in vec2 faceUV;
out vec4 FragColor;
vec3 faceDirection(int face, vec2 uv) {
    vec2 st = uv;
    if (face == 0) return normalize(vec3( 1.0, -st.y, -st.x));
    if (face == 1) return normalize(vec3(-1.0, -st.y,  st.x));
    if (face == 2) return normalize(vec3( st.x,  1.0,  st.y));
    if (face == 3) return normalize(vec3( st.x, -1.0, -st.y));
    if (face == 4) return normalize(vec3( st.x, -st.y,  1.0));
    return normalize(vec3(-st.x, -st.y, -1.0));
}
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

void main() {
    vec3 N = faceDirection(faceIndex, faceUV);
    vec3 V = N;
    vec3 sum = vec3(0.0);
    float weight = 0.0;
    const uint count = 128u;
    for (uint i = 0u; i < count; ++i) {
        vec3 H = importanceSampleGGX(hammersley(i, count), N, roughness);
        vec3 L = normalize(2.0*dot(V,H)*H-V);
        float NdotL = max(dot(N,L),0.0);
        if (NdotL <= 0.0) continue;
        float NdotH = max(dot(N,H),0.0);
        float HdotV = max(dot(H,V),1e-4);
        float pdf = distributionGGX(NdotH,roughness)*NdotH/
                    (4.0*HdotV)+1e-4;
        float texelSolidAngle = 4.0*3.14159265359/(6.0*resolution*resolution);
        float sampleSolidAngle = 1.0/(float(count)*pdf+1e-4);
        float lod = roughness < 1e-4 ? 0.0 :
                    max(0.5*log2(sampleSolidAngle/texelSolidAngle),0.0);
        sum += textureLod(environmentMap,L,lod).rgb*NdotL;
        weight += NdotL;
    }
    FragColor = vec4(sum/max(weight,1e-5),1.0);
}
