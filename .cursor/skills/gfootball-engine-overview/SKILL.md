---
name: gfootball-engine-overview
description: Describes the structure, build, and Python boundary of the gfootball_engine C++ engine (gameplayfootball/blunted2). Use when the user asks about project layout, module boundaries, CMake build, or Python-C++ interface in football repo.
---

# gfootball_engine 工程概览

## 适用范围

仅针对 **third_party/gfootball_engine**（C++ 引擎）。仓库根目录下还有 Python 层（gfootball/），本 skill 不涵盖。

## 构建与产物

- **构建**：`third_party/gfootball_engine/CMakeLists.txt` + `sources.cmake` 列出所有源文件。
- **产物**：单一共享库。Linux 名为 `game`，Windows 名为 `_gameplayfootball.pyd`，供 Python 加载。
- **依赖**：OpenGL、SDL2（及 image/ttf/gfx）、Boost（thread、system、filesystem、Boost.Python）、Python；Unix 可选 EGL。

## 模块划分（与 sources.cmake 对应）

- **base**：数学（vector3, matrix3/4, quaternion, bluntmath）、几何（aabb, line, plane, triangle）、日志、properties、sdl_surface。数学与几何库（`src/base/math`、`src/base/geometry`）调用量大，修改时需**最大量考虑性能优化**，见规则 `cpp-math-optimization.mdc`。
- **types**：RefCounted、Observer、Subject、Command、Resource、Loader、MessageQueue、Spatial 等；大量 `boost::intrusive_ptr`。
- **systems/graphics**：GraphicsSystem、GraphicsScene、GraphicsTask；物体（Camera、Light、Geometry、Overlay2D）；渲染（OpenGL）；VertexBuffer、Texture。
- **scene**：Object、Scene2D/3D、Node、ObjectFactory；Geometry、Light、Camera、Skybox、Image2D；GeometryData、Surface。
- **loaders**：ASE、Image。
- **utils**：Animation、ObjectLoader、XmlLoader、Gui2（WindowManager、Page、View、Widgets）、OrbitCamera、SplitGeometry。
- **onthepitch**：Match、Team、Player、Humanoid、Ball、Referee、TeamAIController、ProceduralPitch、各类 Controller 与 Strategy。
- **menu / data**：菜单、MatchData、TeamData、PlayerData。
- **Python 对接**：main.cpp、game_env、ai、gamedefines 等；通过 Boost.Python 暴露。

## 库链接关系（简化）

OBJECT 库（baselib、systemsgraphicslib、loaderslib、typeslib、scenelib、utilslib、gui2lib）→ 合并进 blunted2；blunted2 + gamelib + menulib + datalib → 与 Boost/Python/SDL2/OpenGL 链接 → 最终共享库。

## 关键路径

- 入口与全局：`src/main.cpp`、`src/main.hpp`、`src/blunted.cpp`、`src/defines.hpp`。
- 引用计数与观察者：`src/types/refcounted.hpp`、`src/types/observer.hpp`、`src/types/subject.hpp`。
- 场景与对象：`src/scene/object.hpp`、`src/scene/scene.hpp`、`src/scene/objectfactory.hpp`。
