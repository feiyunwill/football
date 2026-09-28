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
in vec4 position;
out vec2 faceUV;
void main() {
    faceUV = position.xy;
    gl_Position = vec4(position.xy, 0.0, 1.0);
}
