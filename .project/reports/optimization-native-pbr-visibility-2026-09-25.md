# PBR 黑场与非空画面验收漏检

归属 ms-23.1 → plan-23.1.1 → task-23.1.1.2 的实际渲染核验。PBR 产品质量未通过，正式源码尚未修改。

## 已复现的缺陷

在 native-modifier-capture-validation-20260925-a 中，Release/完整 Debug 的基线和 RG16F 候选均使用真实 GameEnv、EGL、llvmpipe，以及相同 321×181 场景。8 案例原捕获合同均返回成功，新旧图像及状态相同。但目视检查第 160 帧：legacy 有球场、球员和 HUD；PBR 画面基本只保留 HUD。

独立检查选择中央区域 x=[96,225)、y=[54,127)，共 9417 像素，排除上方小地图和下方记分牌。所有 4 个 PBR 组合中，第 0/40 帧只有 41/40 个非黑像素，第 80/120/160 帧均全黑；所有 legacy 对照的相同区域均有 9417 个非黑像素。PBR 每案例同时记录 18 项不同的 uniform 缺失错误。

## 验收为何漏检

现有 engine_frame_capture_contract.cpp 只要求整幅画面有超过 100 个像素不同于第一个像素。HUD 已能满足该条件，所以正确读回、状态恢复、捕获开关与新旧图像相同均可通过，仍然没有证明三维场景可见。

补充的 native-pbr-visibility-validation-20260925-a/audit.py 已对 40 份完整实际 RGB 产物执行独立检查，退出 1，4/8 案例失败。它拒绝中央场地完全黑屏；非黑本身仍不能证明材质、光照或完整 PBR 正确，不把这个补充检查提升为全部渲染验收。

证据：native-modifier-capture-progress-20260925-a/field-visibility-audit.json、terminal-verification.json，以及 legacy-frame-160-raw-row-order.png、pbr-frame-160-raw-row-order.png。PNG 按原始 RGB 行序无损转换，仅供核查。捕获阶段核验 4216 份输入、12 份日志和 1138 份正式源码，全部匹配；阶段本身的成功只保留为兼容性结果。

## 源码定位与下一步

RenderViewPBR 将 IBL 合成用于全屏绘制，将 PBR 材质着色器用于光体积绘制；RenderOverlay2D 设置 orthoProjectionMatrix/orthoViewMatrix。当前 ibl_composition.vert 和 pbr.vert 接收 projectionMatrix/modelViewMatrix/normalMatrix，并输出 WorldPos/Normal/TexCoords，属于另一组输入接口。运行日志同时报告缺少全屏和光体积调用使用的多项 uniform。此处已证实接口不一致，但尚未通过运行时探针确定所有致黑环节，不能把全部缺陷归结为单个 uniform。

下一步用精确的实际调用观测核对当前着色器、顶点输入、矩阵、G-buffer 采样与 IBL 资源绑定，再实现完整一致的渲染接口。修复必须同时证明球场与球员可见、光照/材质响应正确、无错误 uniform、状态与捕获语义正确，并重新运行完整 Debug/Release 及原产品门槛。不得以切回 legacy、删除错误日志或仅增加一个非黑像素作为 PBR 修复。
