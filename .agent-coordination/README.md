# Multi-Agent Coordination

This directory implements a **milestone-based multi-agent coordination protocol**
for the football project. Any AI coding agent — Claude, Codex, Cursor, opencode,
etc. — participates via the same files and commands.

## Principle

Agents hand off work at **milestone boundaries**. Each milestone is a
self-contained unit of work (e.g. "Implement ECS ComponentPool Remove()",
"Add frame sync determinism check"). When an agent dies abnormally, its
heartbeat expires, the milestone is marked **ORPHANED**, and the next agent
that starts will auto-detect and adopt it.

## Directory Layout

```
.agent-coordination/
├── README.md              ← this file
├── coord.py               ← shared CLI (Python 3, no external deps)
├── recover.sh             ← agent startup: source this
├── exit.sh                ← agent exit: source this
├── milestones.json        ← milestone registry
├── agents.json            ← agent registry with heartbeats
├── active_milestone.json  ← singleton: what's being worked on now
├── snapshots/             ← per-milestone context snapshots
├── decisions/             ← Architecture Decision Records
└── knowledge/             ← shared project knowledge
```

## Quick Start for Any Agent

### On Startup

```bash
source .agent-coordination/recover.sh
```

This:
1. Registers the agent (if new)
2. Scans for zombie agents (expired heartbeats > 5 min)
3. Finds ORPHANED milestones and offers to adopt them
4. Starts a background heartbeat (every 120s)

Set `AGENT_ID` to override the default (hostname-PID).

### During Work

```bash
# Update progress on current milestone
python3 .agent-coordination/coord.py add-progress ms-abc123 "Did X, found Y"

# Quick heartbeat (or rely on recover.sh background loop)
python3 .agent-coordination/coord.py heartbeat agent-007

# Save a context snapshot (handoff point)
python3 .agent-coordination/coord.py snapshot ms-abc123 agent-007 \
  --focus "Implementing swap-and-pop removal" \
  --insights "Must update index map on removal;ECS pool iteration is deterministic" \
  --next-steps "Write unit test;benchmark vs old approach"
```

### On Milestone Completion

```bash
python3 .agent-coordination/coord.py complete-milestone ms-abc123 agent-007
```

### On Exit

```bash
source .agent-coordination/exit.sh
```

## Milestone Lifecycle

```
PENDING ──→ CLAIMED ──→ IN_PROGRESS ──→ COMPLETED
                          │    │
                          │    └──→ FAILED
                          │
                          └── (agent dies) → ORPHANED → CLAIMED (by new agent)
```

## Agent Heartbeat Protocol

- Agents write their `heartbeat_at` timestamp on registration and every 120s
- If `heartbeat_at` is older than 300s (5 min), the agent is **zombie**
- Zombie agents' milestones auto-orphan on next `recover` call
- Orphans can be adopted by any live agent

## Agent Types (Agent-Agnostic)

The registry stores a `type` field: `claude`, `codex`, `cursor`, `opencode`,
`human`. All agents use the same protocol. No special privileges per type.

## Integrating with Agent-Specific Configs

### Claude Code
Add to `~/.claude/settings.json`:
```json
{
  "startup": {
    "command": "bash .agent-coordination/recover.sh"
  }
}
```
Already referenced in `CLAUDE.md` → see project root.

### Codex CLI
Add to your Codex config or `.codexrc`:
```json
{
  "onStart": ["bash .agent-coordination/recover.sh"]
}
```

### Cursor
Use the `.cursor/rules/` file at project root (already set up).

## Migration from .claude/agent_coordination/

This new `.agent-coordination/` supersedes the old Claude-specific
`.claude/agent_coordination/`. To migrate:

```bash
# Copy old task queue as milestones (one-shot)
python3 -c "
import json
old = json.load(open('.claude/agent_coordination/task_queue.json'))
for t in old.get('tasks', []):
  import subprocess
  subprocess.run(['python3', '.agent-coordination/coord.py', 'add-milestone',
    t['title'], t.get('description','')])
"
```

## Determinism (Same Philosophy as Frame Sync)

- All timestamps: UTC ISO8601
- File writes: atomic (write .tmp, then rename)
- No concurrent writers per file (single-writer by milestone ownership)