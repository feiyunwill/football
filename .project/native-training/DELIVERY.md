# Linux 安装与原生产物验证

在已安装工程系统依赖和 Python build/runtime 依赖的 Linux/WSL 中执行：

```sh
python .project/native-training/validate_delivery.py \
  --work-root /tmp/football-native-delivery \
  --output /tmp/football-native-delivery-evidence
```

两个目录必须不存在，避免覆盖既有产物/证据。验证器从当前 HEAD 导出 engine、
gfootball、third_party 和构建元数据，拒绝与工作树不一致的生产输入。Git 的文本
CRLF/LF 归一化单独列出；资源字节必须一致。干净导出在新目录通过 PEP517 构建
真实 wheel，在新 venv 正常安装依赖和 wheel，再从仓库外用 Python -I 运行。
无需 editable install、PYTHONPATH 或开发资源路径。

安装 probe 检查模块/extension/data/font 均来自安装 venv，运行多人、stacked、
checkpoint-reward native Gym 环境及 snapshot restore；完整安装后 suite 继续
验证原 Python/Gym 对照、快照、资源、worker、策略数学和 CLI。依赖 pip check
必须通过。wheel tags 描述实际 CPython ABI，不承诺 abi3 或跨 Python minor。

原生目录包也可以单独生成：

```sh
python .project/native-training/package_native.py \
  --build-root /tmp/football-native-package-build \
  --output /tmp/football-native-package
/tmp/football-native-package/native_ppo_train --help
```

包中包含 bin/native_ppo_train、libfootball_engine.so、data、fonts、LICENSE、
启动脚本和文件哈希 manifest。整个目录可以一起搬移；启动脚本默认从自身目录
设置资源路径，也允许显式环境变量覆盖。binary 的 $ORIGIN RUNPATH 定位 bundled
core，使用者不需要 Python。生成器使用 Python/CMake 不等于运行依赖 Python。
checkpoint 要求同源/构建/ABI、相同场景和配置，不能用跨构建搬移恢复冒充可移植
checkpoint。与历史 Gaussian 模型和 FTRN 环境快照的格式边界保持独立。

验证器将刚从干净导出编译的产物复制成目录包，再移动到另一目录。从仓库外检查
ldd/readelf、资源及实际完整训练/新进程续训/冻结评估，要求 checkpoint 字节
与评估一致。系统 SDL2/image/ttf/gfx、OpenGL/EGL、libc/libstdc++ 等动态依赖
仍需安装；本目录包及本地 wheel 都不是静态或 manylinux 可移植发布。

产物保留在 work-root 的 wheels、installed-env、relocated-native。报告保存
源码 archive/文件、wheel、native 文件及 checkpoint 哈希、命令退出码和原始
日志；没有上传、push 或发布。具体已验证平台与未验证版本在任务证据中记录，
不能从 metadata 的 requires-python 推断所有版本已通过测试。
