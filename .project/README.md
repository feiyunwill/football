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

## 成功条件

- 代码审查通过
- 单元测试通过
- 集成测试通过
- 性能指标达标
- 用户验收通过
