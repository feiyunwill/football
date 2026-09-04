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

// 2026-09-03 Phase 15: 运动模糊顶点着色器

#version 150

#pragma optimize(on)

in vec2 position;
in vec2 texCoord;

out vec2 TexCoords;

void main() {
    TexCoords = texCoord;
    gl_Position = vec4(position, 0.0, 1.0);
}
