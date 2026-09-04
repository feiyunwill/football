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

// 2026-09-03 Phase 12: 辐照度贴图顶点着色器
// 用于将 HDR 环境贴图卷积为漫反射辐照度贴图

#version 150

#pragma optimize(on)

in vec3 position;

uniform mat4 projectionMatrix;
uniform mat4 modelViewMatrix;

out vec3 WorldPos;

void main() {
    WorldPos = position;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
