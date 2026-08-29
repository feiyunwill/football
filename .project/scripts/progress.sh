#!/bin/bash
# 进度可视化脚本
# 用法: ./progress.sh

echo "=== 项目进度 ==="
echo ""

# 1. 显示阶段进度
echo "1. 阶段进度:"
echo "   Phase 1: 帧同步联机稳定版 [进行中]"
echo "   Phase 2: ECS 架构重构完成 [待开始]"
echo "   Phase 3: AI 训练基础 [待开始]"
echo "   Phase 4: 内置 AI 完善 [待开始]"
echo "   Phase 5: 商业级优化 [待开始]"
echo ""

# 2. 显示里程碑进度
echo "2. 里程碑进度:"
echo "   ms-1.1: 基础协议稳定性 [60%]"
echo "   ms-1.2: 确定性基础 [0%]"
echo "   ms-1.3: 预测回滚 [0%]"
echo "   ms-1.4: 动态追帧 [0%]"
echo "   ms-1.5: 外挂校验 [0%]"
echo "   ms-1.6: 逻辑渲染分离 [0%]"
echo "   ms-1.7: 渲染平滑 [0%]"
echo "   ms-1.8: 性能优化 [0%]"
echo ""

# 3. 显示任务统计
echo "3. 任务统计:"
TOTAL_TASKS=$(find .project/tasks -name "*.md" 2>/dev/null | wc -l)
COMPLETED_TASKS=$(grep -l "状态: COMPLETED" .project/tasks/*.md 2>/dev/null | wc -l)
echo "   总任务数: $TOTAL_TASKS"
echo "   已完成: $COMPLETED_TASKS"
echo "   完成率: $(( COMPLETED_TASKS * 100 / (TOTAL_TASKS > 0 ? TOTAL_TASKS : 1) ))%"
echo ""

# 4. 显示最近活动
echo "4. 最近活动:"
echo "   2026-08-29: 完成 plan-1.1.1 (UDP 通信基础)"
echo "   2026-08-29: 完成 task-1.1.1.1 (实现 UDP 服务器)"
echo "   2026-08-29: 完成 task-1.1.1.2 (实现 UDP 客户端)"
echo ""

# 5. 显示阻塞项
echo "5. 阻塞项:"
echo "   无"
echo ""

# 6. 显示下一步
echo "6. 下一步:"
echo "   完成 plan-1.1.2 (心跳机制)"
echo "   完成 plan-1.1.3 (e2e 测试)"
