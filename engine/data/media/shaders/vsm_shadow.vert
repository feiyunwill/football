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

// 2026-09-03 Phase 14: 方差阴影贴图顶点着色器

#version 150

#pragma optimize(on)

in vec3 position;
in vec3 normal;
in vec2 texCoord;

uniform mat4 projectionMatrix;
uniform mat4 modelViewMatrix;
uniform mat3 normalMatrix;

out vec3 WorldPos;
out vec3 Normal;
out vec2 TexCoords;

void main() {
    WorldPos = vec3(modelViewMatrix * vec4(position, 1.0));
    Normal = normalMatrix * normal;
    TexCoords = texCoord;
    
    gl_Position = projectionMatrix * vec4(WorldPos, 1.0);
}
