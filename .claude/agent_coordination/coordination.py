#!/usr/bin/env python3
"""
Multi-Agent Coordination Library
Shared utilities for task management, snapshots, and handoffs.
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
try:
    from filelock import FileLock
except ImportError:
    class FileLock:
        def __init__(self, path): self.path = path
        def __enter__(self): return self
        def __exit__(self, *args): pass

COORD_DIR = Path(__file__).parent
TASK_QUEUE_FILE = COORD_DIR / "task_queue.json"
ACTIVE_TASK_FILE = COORD_DIR / "active_task.json"
AGENT_REGISTRY_FILE = COORD_DIR / "agent_registry.json"
SNAPSHOTS_DIR = COORD_DIR / "context_snapshots"
KNOWLEDGE_DIR = COORD_DIR / "knowledge_base"
DECISIONS_DIR = COORD_DIR / "decisions"

SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
DECISIONS_DIR.mkdir(parents=True, exist_ok=True)

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

def atomic_write(path: Path, data: dict) -> None:
    tmp_path = path.with_suffix('.tmp')
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp_path.rename(path)

def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with open(path) as f:
        return json.load(f)

def write_json(path: Path, data: dict) -> None:
    lock_path = path.with_suffix('.lock')
    with FileLock(lock_path):
        atomic_write(path, data)

def load_task_queue() -> dict:
    return read_json(TASK_QUEUE_FILE, {"tasks": [], "version": 1})

def save_task_queue(queue: dict) -> None:
    write_json(TASK_QUEUE_FILE, queue)

def add_task(title: str, description: str, tags: List[str] = None, priority: str = "medium") -> str:
    queue = load_task_queue()
    task_id = f"task-{uuid.uuid4().hex[:8]}"
    task = {
        "id": task_id,
        "title": title,
        "description": description,
        "status": "PENDING",
        "assignee": None,
        "priority": priority,
        "tags": tags or [],
        "dependencies": [],
        "created_at": utc_now(),
        "claimed_at": None,
        "completed_at": None,
        "progress_notes": []
    }
    queue["tasks"].append(task)
    save_task_queue(queue)
    return task_id

def get_task(task_id: str) -> Optional[dict]:
    queue = load_task_queue()
    for task in queue["tasks"]:
        if task["id"] == task_id:
            return task
    return None

def update_task(task_id: str, **updates) -> bool:
    queue = load_task_queue()
    for task in queue["tasks"]:
        if task["id"] == task_id:
            task.update(updates)
            if updates.get("status") == "COMPLETED":
                task["completed_at"] = utc_now()
            save_task_queue(queue)
            return True
    return False

def claim_task(task_id: str, agent_id: str) -> bool:
    return update_task(task_id, status="CLAIMED", assignee=agent_id, claimed_at=utc_now())

def start_task(task_id: str, agent_id: str) -> bool:
    ok = update_task(task_id, status="IN_PROGRESS", assignee=agent_id)
    if not ok:
        return False
    active = {
        "active_task_id": task_id,
        "assignee": agent_id,
        "status": "IN_PROGRESS",
        "updated_at": utc_now()
    }
    write_json(ACTIVE_TASK_FILE, active)
    return True

def complete_task(task_id: str, agent_id: str) -> bool:
    ok = update_task(task_id, status="COMPLETED", assignee=agent_id)
    if not ok:
        return False
    active = {
        "active_task_id": None,
        "assignee": None,
        "status": "idle",
        "updated_at": utc_now()
    }
    write_json(ACTIVE_TASK_FILE, active)
    return True

def add_progress_note(task_id: str, note: str) -> bool:
    queue = load_task_queue()
    for task in queue["tasks"]:
        if task["id"] == task_id:
            task["progress_notes"].append(f"{utc_now()} - {note}")
            save_task_queue(queue)
            return True
    return False

def list_tasks(status: str = None, assignee: str = None) -> List[dict]:
    queue = load_task_queue()
    tasks = queue["tasks"]
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    if assignee:
        tasks = [t for t in tasks if t["assignee"] == assignee]
    return tasks

def get_pending_tasks() -> List[dict]:
    return list_tasks(status="PENDING")

def get_active_task() -> Optional[dict]:
    active = read_json(ACTIVE_TASK_FILE)
    if active and active.get("active_task_id"):
        return get_task(active["active_task_id"])
    return None

def register_agent(agent_id: str, capabilities: List[str] = None, metadata: dict = None) -> None:
    registry = read_json(AGENT_REGISTRY_FILE, {"agents": {}, "version": 1})
    registry["agents"][agent_id] = {
        "capabilities": capabilities or [],
        "metadata": metadata or {},
        "registered_at": utc_now(),
        "last_seen": utc_now(),
        "status": "active"
    }
    write_json(AGENT_REGISTRY_FILE, registry)

def update_agent_heartbeat(agent_id: str) -> None:
    registry = read_json(AGENT_REGISTRY_FILE, {"agents": {}, "version": 1})
    if agent_id in registry["agents"]:
        registry["agents"][agent_id]["last_seen"] = utc_now()
        write_json(AGENT_REGISTRY_FILE, registry)

def mark_agent_inactive(agent_id: str) -> None:
    registry = read_json(AGENT_REGISTRY_FILE, {"agents": {}, "version": 1})
    if agent_id in registry["agents"]:
        registry["agents"][agent_id]["status"] = "inactive"
        registry["agents"][agent_id]["last_seen"] = utc_now()
        write_json(AGENT_REGISTRY_FILE, registry)

def list_agents(active_only: bool = True) -> Dict[str, dict]:
    registry = read_json(AGENT_REGISTRY_FILE, {"agents": {}, "version": 1})
    agents = registry["agents"]
    if active_only:
        return {k: v for k, v in agents.items() if v.get("status") == "active"}
    return agents

def create_snapshot(agent_id: str, mental_model: dict, environment_state: dict = None) -> str:
    active_task = get_active_task()
    snapshot = {
        "agent_id": agent_id,
        "timestamp": utc_now(),
        "active_task_id": active_task["id"] if active_task else None,
        "mental_model": mental_model,
        "environment_state": environment_state or {
            "build_status": "unknown",
            "test_status": "unknown",
            "current_branch": get_git_branch()
        }
    }
    filename = f"snapshot_{snapshot['timestamp'].replace(':', '-')}_{agent_id}.json"
    filepath = SNAPSHOTS_DIR / filename
    atomic_write(filepath, snapshot)
    return filename

def get_latest_snapshot(agent_id: str = None) -> Optional[dict]:
    snapshots = sorted(SNAPSHOTS_DIR.glob("snapshot_*.json"), reverse=True)
    if not snapshots:
        return None
    if agent_id:
        for snap in snapshots:
            if agent_id in snap.name:
                with open(snap) as f:
                    return json.load(f)
        return None
    with open(snapshots[0]) as f:
        return json.load(f)

def get_git_branch() -> str:
    try:
        import subprocess
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd="/home/zuchangqu/project/football",
            capture_output=True, text=True
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"

def add_knowledge(category: str, content: str) -> None:
    filepath = KNOWLEDGE_DIR / f"{category}.md"
    with open(filepath, 'a') as f:
        f.write(f"\n## {utc_now()}\n{content}\n")

def read_knowledge(category: str) -> str:
    filepath = KNOWLEDGE_DIR / f"{category}.md"
    if filepath.exists():
        with open(filepath) as f:
            return f.read()
    return ""

def create_adr(title: str, content: str) -> str:
    adrs = sorted(DECISIONS_DIR.glob("ADR-*.md"))
    next_num = len(adrs) + 1
    filename = f"ADR-{next_num:03d}-{title.lower().replace(' ', '-')}.md"
    filepath = DECISIONS_DIR / filename
    adr_content = f"# ADR-{next_num:03d}: {title}\n\n**Date**: {utc_now()}\n\n---\n\n{content}\n"
    with open(filepath, 'w') as f:
        f.write(adr_content)
    return filename

def main():
    if len(sys.argv) < 2:
        print("Usage: coordination.py <command> [args...]")
        print("Commands: add_task, claim_task, start_task, complete_task, list_tasks,")
        print("          register_agent, snapshot, get_snapshot, add_knowledge, create_adr")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "add_task":
        if len(sys.argv) < 4:
            print("Usage: coordination.py add_task <title> <description> [--tags tag1,tag2] [--priority high|medium|low]")
            sys.exit(1)
        title = sys.argv[2]
        description = sys.argv[3]
        tags = []
        priority = "medium"
        for i, arg in enumerate(sys.argv[4:], 4):
            if arg == "--tags" and i + 1 < len(sys.argv):
                tags = sys.argv[i + 1].split(",")
            elif arg == "--priority" and i + 1 < len(sys.argv):
                priority = sys.argv[i + 1]
        task_id = add_task(title, description, tags, priority)
        print(f"Created task: {task_id}")

    elif cmd == "claim_task":
        if len(sys.argv) < 4:
            print("Usage: coordination.py claim_task <task_id> <agent_id>")
            sys.exit(1)
        ok = claim_task(sys.argv[2], sys.argv[3])
        print(f"Claimed: {ok}")

    elif cmd == "start_task":
        if len(sys.argv) < 4:
            print("Usage: coordination.py start_task <task_id> <agent_id>")
            sys.exit(1)
        ok = start_task(sys.argv[2], sys.argv[3])
        print(f"Started: {ok}")

    elif cmd == "complete_task":
        if len(sys.argv) < 4:
            print("Usage: coordination.py complete_task <task_id> <agent_id>")
            sys.exit(1)
        ok = complete_task(sys.argv[2], sys.argv[3])
        print(f"Completed: {ok}")

    elif cmd == "list_tasks":
        status = sys.argv[2] if len(sys.argv) > 2 else None
        tasks = list_tasks(status=status)
        for t in tasks:
            print(f"{t['id']} [{t['status']}] {t['title']} (assignee: {t['assignee']})")

    elif cmd == "register_agent":
        if len(sys.argv) < 3:
            print("Usage: coordination.py register_agent <agent_id> [--capabilities cap1,cap2]")
            sys.exit(1)
        agent_id = sys.argv[2]
        caps = []
        for i, arg in enumerate(sys.argv[3:], 3):
            if arg == "--capabilities" and i + 1 < len(sys.argv):
                caps = sys.argv[i + 1].split(",")
        register_agent(agent_id, caps)
        print(f"Registered agent: {agent_id}")

    elif cmd == "snapshot":
        if len(sys.argv) < 4 or sys.argv[2] != "--agent-id":
            print("Usage: coordination.py snapshot --agent-id <agent_id> [--focus <focus>] [--insights <insights>] [--next-steps <steps>]")
            sys.exit(1)
        agent_id = sys.argv[3]
        mental_model = {
            "current_focus": "",
            "key_files_modified": [],
            "critical_insights": [],
            "open_questions": [],
            "next_steps": []
        }
        for i, arg in enumerate(sys.argv[4:], 4):
            if arg == "--focus" and i + 1 < len(sys.argv):
                mental_model["current_focus"] = sys.argv[i + 1]
            elif arg == "--insights" and i + 1 < len(sys.argv):
                mental_model["critical_insights"] = sys.argv[i + 1].split(";")
            elif arg == "--next-steps" and i + 1 < len(sys.argv):
                mental_model["next_steps"] = sys.argv[i + 1].split(";")
        fname = create_snapshot(agent_id, mental_model)
        print(f"Created snapshot: {fname}")

    elif cmd == "get_snapshot":
        agent_id = sys.argv[2] if len(sys.argv) > 2 else None
        snap = get_latest_snapshot(agent_id)
        if snap:
            print(json.dumps(snap, indent=2))
        else:
            print("No snapshot found")

    elif cmd == "add_knowledge":
        if len(sys.argv) < 4:
            print("Usage: coordination.py add_knowledge <category> <content>")
            sys.exit(1)
        add_knowledge(sys.argv[2], sys.argv[3])
        print(f"Added to knowledge_base/{sys.argv[2]}.md")

    elif cmd == "create_adr":
        if len(sys.argv) < 4:
            print("Usage: coordination.py create_adr <title> <content>")
            sys.exit(1)
        fname = create_adr(sys.argv[2], sys.argv[3])
        print(f"Created ADR: {fname}")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

if __name__ == "__main__":
    main()
