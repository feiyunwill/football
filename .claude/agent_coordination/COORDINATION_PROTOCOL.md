# Multi-Agent Coordination Protocol

## Overview
This protocol enables multiple Claude Code agents to collaborate on the football project with full state persistence and seamless handoffs.

## Core Components

### 1. Shared State Directory
```
.claude/agent_coordination/
├── COORDINATION_PROTOCOL.md      # This file
├── active_task.json              # Currently active task + assignee
├── task_queue.json               # Pending/in-progress/completed tasks
├── context_snapshots/            # Agent context snapshots for handoff
│   ├── snapshot_<timestamp>_<agent_id>.json
│   └── ...
├── decisions/                    # Architectural decisions (ADRs)
│   ├── ADR-<num>-<topic>.md
│   └── ...
├── knowledge_base/               # Learned facts, patterns, gotchas
│   ├── patterns.md
│   ├── gotchas.md
│   └── conventions.md
└── agent_registry.json           # Registered agents + capabilities
```

### 2. Task State Machine
```
PENDING → CLAIMED (agent_id) → IN_PROGRESS → BLOCKED (reason) → IN_PROGRESS
                                                      ↓
                                              COMPLETED → ARCHIVED
                                                      ↓
                                              FAILED (reason) → PENDING (retry)
```

### 3. Agent Handoff Protocol

#### When Agent Exits (Graceful)
1. Write context snapshot to `context_snapshots/snapshot_<ISO8601>_<agent_id>.json`
2. Update `active_task.json` with progress, next steps, blockers
3. Release task claim (set status back to PENDING or IN_PROGRESS with no assignee)
3. Update `agent_registry.json` with last_seen timestamp

#### When New Agent Starts
1. Read `active_task.json` → understand current work
2. Read latest context snapshot → restore mental model
3. Read `task_queue.json` → see full backlog
4. Read `knowledge_base/` → learn project conventions
5. Claim next task or continue active task

### 4. Context Snapshot Schema
```json
{
  "agent_id": "unique-agent-identifier",
  "timestamp": "2026-08-29T10:30:00Z",
  "active_task_id": "task-123",
  "mental_model": {
    "current_focus": "ECS system integration",
    "key_files_modified": ["src/ecs/world.cpp", "src/onthepitch/match.cpp"],
    "critical_insights": [
      "ECS pools must iterate by entity ID for determinism",
      "Match::Step() calls SystemManager::ProcessPhase() 10x per frame"
    ],
    "open_questions": [
      "How to handle component removal during iteration?"
    ],
    "next_steps": [
      "Implement ComponentPool::Remove() with swap-and-pop",
      "Add unit test for entity destruction mid-frame"
    ]
  },
  "environment_state": {
    "build_status": "clean",
    "test_status": "passing",
    "current_branch": "feature/ecs-integration"
  }
}
```

### 5. Task Queue Schema
```json
{
  "tasks": [
    {
      "id": "task-123",
      "title": "Implement ECS ComponentPool swap-and-pop removal",
      "status": "IN_PROGRESS",
      "assignee": "agent-abc",
      "priority": "high",
      "tags": ["ecs", "performance", "determinism"],
      "dependencies": [],
      "created_at": "2026-08-29T09:00:00Z",
      "claimed_at": "2026-08-29T09:15:00Z",
      "completed_at": null,
      "progress_notes": [
        "2026-08-29T09:20:00Z - Analyzed existing ComponentPool iteration",
        "2026-08-29T09:45:00Z - Implemented Remove(), need to test iteration invalidation"
      ]
    }
  ]
}
```

## Usage Commands

### For Agents (via Bash/Tools)
```bash
# Claim a task
python3 .claude/agent_coordination/claim_task.py <task_id>

# Update progress
python3 .claude/agent_coordination/update_progress.py <task_id> "note"

# Create snapshot on exit
python3 .claude/agent_coordination/snapshot.py --agent-id <id>

# List available tasks
python3 .claude/agent_coordination/list_tasks.py

# Register agent
python3 .claude/agent_coordination/register_agent.py --id <id> --capabilities "cpp,rl,networking"
```

### For Humans (Manual)
```bash
# View current state
cat .claude/agent_coordination/active_task.json
cat .claude/agent_coordination/task_queue.json | jq .

# Add new task
python3 .claude/agent_coordination/add_task.py "Title" "Description" --tags "ecs,networking" --priority high
```

## Integration with Project Memory
- This protocol COMPLEMENTS the existing `.claude/projects/.../memory/` system
- Project-level memories (architecture decisions, conventions) → `knowledge_base/`
- Session-specific memories → context snapshots
- Task-level tracking → task_queue.json

## Determinism Guarantees
- All timestamps in UTC ISO8601
- File writes are atomic (write to .tmp then rename)
- JSON files use stable key ordering
- No concurrent writes to same file (single-writer per file via task ownership)
