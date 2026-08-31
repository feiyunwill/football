# 项目管理结构

## 目录结构

```
.project/
├── PROJECT.md              ← 项目总览
├── phases/                 ← 阶段定义
│   ├── phase1.md          ← Phase 1: 帧同步联机
│   ├── phase2.md          ← Phase 2: ECS 架构重构
│   ├── phase3.md          ← Phase 3: AI 训练基础
│   ├── phase4.md          ← Phase 4: 内置 AI 完善
│   └── phase5.md          ← Phase 5: 商业级优化
├── milestones/             ← 里程碑定义
│   ├── ms-1.1-protocol.md
│   ├── ms-1.2-determinism.md
│   └── ...
├── plans/                  ← 计划定义
│   ├── ms-1.1-plan1.md
│   └── ...
├── tasks/                  ← 任务定义
│   ├── ms-1.1-plan1-task1.md
│   └── ...
├── templates/              ← 模板文件
│   ├── milestone-template.md
│   ├── plan-template.md
│   └── task-template.md
├── scripts/                ← 自动化脚本
│   ├── task_complete.sh    ← 标记任务完成
│   ├── auto_claim.sh       ← 自动认领 milestone
│   ├── progress.sh         ← 显示项目进度
│   ├── milestone_complete.sh ← 标记 milestone 完成
│   ├── plan_complete.sh    ← 标记计划完成
│   ├── auto_test.sh        ← 自动运行测试
│   ├── auto_review.sh      ← 自动代码审查
│   └── workflow.sh         ← 主工作流脚本
└── reports/                ← 审查报告
    ├── review-ms-1.1.md
    └── ...
```

## 工作流程

```
任务完成 → 代码审查 → 单元测试 → 提交
    ↓
计划完成 → 功能测试 → 补丁任务 → 完成
    ↓
里程碑完成 → 全局审查 → 集成测试 → 完成
    ↓
阶段完成 → 性能测试 → 用户验收 → 进入下一阶段
```

## 常用命令

```bash
# 任务完成自动化
bash .project/scripts/task_complete.sh <task_id> "commit message"

# 计划完成自动化
bash .project/scripts/plan_complete.sh <plan_id>

# 里程碑完成自动化
bash .project/scripts/milestone_complete.sh <milestone_id>

# 查看进度
bash .project/scripts/progress.sh

# 自动认领 milestone
bash .project/scripts/auto_claim.sh <agent_id>

# 自动测试
bash .project/scripts/auto_test.sh <target_id> [test_type]

# 自动代码审查
bash .project/scripts/auto_review.sh <target_id> [review_type]

# 完整工作流
bash .project/scripts/workflow.sh <action> <target_id> [options]
```

## 成功条件

- 代码审查通过
- 单元测试通过
- 集成测试通过
- 性能指标达标
- 用户验收通过
