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

// 2026-09-03 Phase 14: VSM 深度片段着色器
// 输出深度和深度平方用于方差阴影映射

#version 150

#pragma optimize(on)

out vec4 FragColor;

void main() {
    float depth = gl_FragCoord.z;
    float depthSquare = depth * depth;
    
    // 输出深度和深度平方
    FragColor = vec4(depth, depthSquare, 0.0, 1.0);
}
