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

void main() {
    vec3 N = faceDirection(faceIndex, faceUV);
    vec3 up = abs(N.z) < 0.999 ? vec3(0,0,1) : vec3(1,0,0);
    vec3 T = normalize(cross(up, N));
    vec3 B = cross(N, T);
    vec3 sum = vec3(0.0);
    const uint count = 128u;
    for (uint i = 0u; i < count; ++i) {
        vec2 xi = hammersley(i, count);
        float r = sqrt(xi.x);
        float phi = 6.28318530718 * xi.y;
        vec3 local = vec3(r*cos(phi), r*sin(phi), sqrt(max(1.0-xi.x,0.0)));
        vec3 L = normalize(T*local.x + B*local.y + N*local.z);
        sum += texture(environmentMap, L).rgb;
    }
    FragColor = vec4(3.14159265359 * sum / float(count), 1.0);
}
