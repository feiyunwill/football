#!/usr/bin/env python3
"""
coord.py — universal multi-agent coordination for the football project.

Agent-agnostic milestone-based coordination system. Works with Claude, Codex,
Cursor, or any AI coding agent. Every agent participates via the same protocol.

Usage:
  coord.py register-agent <agent_id> --type <claude|codex|cursor|human> [--capabilities cap1,cap2]
  coord.py add-milestone <title> <description> [--tags tag1,tag2] [--priority high|medium|low]
  coord.py claim-milestone <milestone_id> <agent_id>
  coord.py start-milestone <milestone_id> <agent_id>
  coord.py complete-milestone <milestone_id> <agent_id>
  coord.py fail-milestone <milestone_id> <agent_id> <reason>
  coord.py list-milestones [--status PENDING|CLAIMED|IN_PROGRESS|COMPLETED|ORPHANED] [--assignee <agent_id>]
  coord.py add-progress <milestone_id> <note>
  coord.py heartbeat <agent_id>
  coord.py recover [--agent-id <agent_id>]   # Startup: find orphaned/interrupted milestones
  coord.py snapshot <milestone_id> <agent_id> [--focus <text>] [--insights <text>] [--next-steps <text>]
  coord.py which-active                    # Show current active milestone
  coord.py agents [--all]                  # List registered agents
  coord.py status                          # Full project coordination status
  coord.py adopt <milestone_id> <agent_id> # Adopt an ORPHANED milestone
  coord.py add-knowledge <category> <content>
"""
import json, os, sys, uuid, subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).parent
MILESTONES_FILE = BASE_DIR / "milestones.json"
AGENTS_FILE = BASE_DIR / "agents.json"
SNAPSHOTS_DIR = BASE_DIR / "snapshots"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
DECISIONS_DIR = BASE_DIR / "decisions"

HEARTBEAT_TTL_SECONDS = 300  # 5 min without heartbeat = zombie

SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
DECISIONS_DIR.mkdir(parents=True, exist_ok=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def now_epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


def atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
    tmp.rename(path)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with open(path) as f:
        return json.load(f)


def write_json(path: Path, data: dict) -> None:
    atomic_write(path, data)


# ─── Milestones ─────────────────────────────────────────────────

def load_milestones() -> dict:
    return read_json(MILESTONES_FILE, {"milestones": [], "version": 1})


def save_milestones(data: dict) -> None:
    write_json(MILESTONES_FILE, data)


def find_milestone(ms_id: str) -> Optional[dict]:
    data = load_milestones()
    for ms in data["milestones"]:
        if ms["id"] == ms_id:
            return ms
    return None


def update_milestone(ms_id: str, **updates) -> bool:
    data = load_milestones()
    for ms in data["milestones"]:
        if ms["id"] == ms_id:
            ms.update(updates)
            save_milestones(data)
            return True
    return False


def add_milestone(title: str, description: str, tags: List[str] = None,
                  priority: str = "medium") -> str:
    data = load_milestones()
    ms_id = f"ms-{uuid.uuid4().hex[:8]}"
    ms = {
        "id": ms_id,
        "title": title,
        "description": description,
        "status": "PENDING",
        "claimed_by": None,
        "claimed_at": None,
        "heartbeat_at": None,
        "completed_at": None,
        "priority": priority,
        "tags": tags or [],
        "dependencies": [],
        "created_at": utc_now(),
        "progress_notes": [],
        "snapshot_count": 0,
    }
    data["milestones"].append(ms)
    save_milestones(data)
    return ms_id


def adopt_milestone(ms_id: str, agent_id: str) -> bool:
    ms = find_milestone(ms_id)
    if ms is None or ms["status"] not in ("ORPHANED", "PENDING"):
        return False
    return update_milestone(ms_id, status="CLAIMED", claimed_by=agent_id,
                            claimed_at=utc_now(), heartbeat_at=utc_now(),
                            failed_reason=None)


def claim_milestone(ms_id: str, agent_id: str) -> bool:
    ms = find_milestone(ms_id)
    if ms is None or ms["status"] != "PENDING":
        if ms and ms["status"] == "ORPHANED":
            return adopt_milestone(ms_id, agent_id)
        return False
    ok = update_milestone(ms_id, status="CLAIMED", claimed_by=agent_id,
                          claimed_at=utc_now(), heartbeat_at=utc_now())
    sync_active_milestone(ms_id, agent_id)
    return ok


def start_milestone(ms_id: str, agent_id: str) -> bool:
    ok = update_milestone(ms_id, status="IN_PROGRESS", claimed_by=agent_id,
                          heartbeat_at=utc_now())
    if ok:
        sync_active_milestone(ms_id, agent_id)
    return ok


def complete_milestone(ms_id: str, agent_id: str) -> bool:
    ok = update_milestone(ms_id, status="COMPLETED", claimed_by=agent_id,
                          completed_at=utc_now(), heartbeat_at=utc_now())
    if ok:
        clear_active_milestone()
    return ok


def fail_milestone(ms_id: str, agent_id: str, reason: str) -> bool:
    ok = update_milestone(ms_id, status="FAILED", claimed_by=agent_id,
                          completed_at=utc_now(), failed_reason=reason,
                          heartbeat_at=utc_now())
    if ok:
        clear_active_milestone()
    return ok


_ACTIVE_FILE = BASE_DIR / "active_milestone.json"


def sync_active_milestone(ms_id: str, agent_id: str) -> None:
    write_json(_ACTIVE_FILE, {
        "milestone_id": ms_id,
        "claimed_by": agent_id,
        "status": "IN_PROGRESS",
        "updated_at": utc_now(),
    })


def clear_active_milestone() -> None:
    write_json(_ACTIVE_FILE, {
        "milestone_id": None,
        "claimed_by": None,
        "status": "idle",
        "updated_at": utc_now(),
    })


def get_active_milestone() -> Optional[dict]:
    return read_json(_ACTIVE_FILE)


def add_progress_note(ms_id: str, note: str) -> bool:
    data = load_milestones()
    for ms in data["milestones"]:
        if ms["id"] == ms_id:
            ms["progress_notes"].append(f"{utc_now()} - {note}")
            ms["heartbeat_at"] = utc_now()
            save_milestones(data)
            return True
    return False


def list_milestones(status: str = None, assignee: str = None) -> List[dict]:
    data = load_milestones()
    ms_list = data["milestones"]
    if status:
        ms_list = [m for m in ms_list if m["status"] == status]
    if assignee:
        ms_list = [m for m in ms_list if m.get("claimed_by") == assignee]
    return ms_list


# ─── Agents ──────────────────────────────────────────────────────

def load_agents() -> dict:
    return read_json(AGENTS_FILE, {"agents": {}, "version": 1})


def save_agents(data: dict) -> None:
    write_json(AGENTS_FILE, data)


def register_agent(agent_id: str, agent_type: str = "unknown",
                   capabilities: List[str] = None,
                   metadata: dict = None) -> None:
    data = load_agents()
    data["agents"][agent_id] = {
        "type": agent_type,
        "capabilities": capabilities or [],
        "metadata": metadata or {},
        "registered_at": utc_now(),
        "heartbeat_at": utc_now(),
        "current_milestone": None,
        "status": "active",
    }
    save_agents(data)


def agent_heartbeat(agent_id: str) -> None:
    data = load_agents()
    if agent_id in data["agents"]:
        data["agents"][agent_id]["heartbeat_at"] = utc_now()
        data["agents"][agent_id]["status"] = "active"
        save_agents(data)


def mark_agent_dead(agent_id: str) -> None:
    data = load_agents()
    if agent_id in data["agents"]:
        data["agents"][agent_id]["status"] = "zombie"
        save_agents(data)


def list_agents(include_all: bool = False) -> Dict[str, dict]:
    data = load_agents()
    agents = data["agents"]
    if not include_all:
        now = now_epoch()
        live = {}
        for aid, info in agents.items():
            hb = info.get("heartbeat_at", "")
            try:
                hb_ts = datetime.fromisoformat(hb.replace('Z', '+00:00')).timestamp()
            except (ValueError, AttributeError):
                hb_ts = 0
            if info.get("status") == "active" and (now - hb_ts) < HEARTBEAT_TTL_SECONDS:
                live[aid] = info
        return live
    return agents


def detect_zombie_agents() -> List[str]:
    """Return list of agent_ids whose heartbeats have expired."""
    data = load_agents()
    now = now_epoch()
    zombies = []
    for aid, info in data["agents"].items():
        if info.get("status") != "active":
            continue
        hb = info.get("heartbeat_at", "")
        try:
            hb_ts = datetime.fromisoformat(hb.replace('Z', '+00:00')).timestamp()
        except (ValueError, AttributeError):
            hb_ts = 0
        if (now - hb_ts) > HEARTBEAT_TTL_SECONDS:
            zombies.append(aid)
    return zombies


def expire_zombie_agents() -> List[str]:
    """Mark zombie agents as inactive and orphan their milestones."""
    zombies = detect_zombie_agents()
    data = load_agents()
    for aid in zombies:
        if aid in data["agents"]:
            data["agents"][aid]["status"] = "zombie"
    save_agents(data)
    return zombies


# ─── Orphan Detection ────────────────────────────────────────────

def find_orphaned_milestones() -> List[dict]:
    """Find milestones stuck in CLAIMED/IN_PROGRESS with a zombie agent."""
    agents_data = load_agents()
    zombie_agents = {
        aid for aid, info in agents_data["agents"].items()
        if info.get("status") == "zombie"
    }
    data = load_milestones()
    orphans = []
    for ms in data["milestones"]:
        if ms["status"] in ("CLAIMED", "IN_PROGRESS"):
            if ms.get("claimed_by") in zombie_agents:
                orphans.append(ms)
    return orphans


def adopt_orphaned_milestones(agent_id: str) -> List[dict]:
    """Adopt all orphaned milestones. Returns adopted milestones."""
    orphans = find_orphaned_milestones()
    adopted = []
    for ms in orphans:
        ok = update_milestone(ms["id"], status="CLAIMED", claimed_by=agent_id,
                              claimed_at=utc_now(), heartbeat_at=utc_now(),
                              progress_notes=
                              ms.get("progress_notes", []) +
                              [f"{utc_now()} - ADOPTED by {agent_id} (previous: {ms['claimed_by']})"])
        if ok:
            adopted.append(ms)
    if adopted:
        sync_active_milestone(adopted[0]["id"], agent_id)
    return adopted


# ─── Snapshots ───────────────────────────────────────────────────

def create_snapshot(ms_id: str, agent_id: str,
                    current_focus: str = "",
                    critical_insights: List[str] = None,
                    next_steps: List[str] = None) -> str:
    ms = find_milestone(ms_id)
    snap = {
        "milestone_id": ms_id,
        "milestone_title": ms["title"] if ms else "unknown",
        "agent_id": agent_id,
        "timestamp": utc_now(),
        "mental_model": {
            "current_focus": current_focus,
            "critical_insights": critical_insights or [],
            "next_steps": next_steps or [],
        },
        "environment_state": {
            "current_branch": _get_git_branch(),
        },
    }
    filename = f"snap_{ms_id}_{agent_id}_{snap['timestamp'].replace(':', '-')}.json"
    filepath = SNAPSHOTS_DIR / filename
    atomic_write(filepath, snap)
    update_milestone(ms_id, snapshot_count=ms.get("snapshot_count", 0) + 1 if ms else 0)
    return str(filepath)


def get_latest_snapshot(ms_id: str = None) -> Optional[dict]:
    snaps = sorted(SNAPSHOTS_DIR.glob("snap_*.json"), reverse=True)
    if ms_id:
        snaps = [s for s in snaps if s.name.startswith(f"snap_{ms_id}_")]
    if not snaps:
        return None
    with open(snaps[0]) as f:
        return json.load(f)


# ─── Knowledge ───────────────────────────────────────────────────

def add_knowledge(category: str, content: str) -> None:
    path = KNOWLEDGE_DIR / f"{category}.md"
    with open(path, 'a') as f:
        f.write(f"\n## {utc_now()}\n{content}\n")


def read_knowledge(category: str) -> str:
    path = KNOWLEDGE_DIR / f"{category}.md"
    if path.exists():
        with open(path) as f:
            return f.read()
    return ""


# ─── Helpers ─────────────────────────────────────────────────────

def _get_git_branch() -> str:
    try:
        r = subprocess.run(["git", "branch", "--show-current"],
                           capture_output=True, text=True,
                           cwd=BASE_DIR.parent)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _format_milestone_row(ms: dict) -> str:
    a = ms.get("claimed_by", "") or "(unclaimed)"
    return f"  {ms['id']:22s} {ms['status']:12s} {ms['priority']:7s} {ms['title'][:48]:48s} [{a}]"


# ─── CLI ─────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    # ── register-agent ──
    if cmd == "register-agent":
        if len(sys.argv) < 4:
            print("Usage: coord.py register-agent <agent_id> --type <type> [--capabilities cap1,cap2]")
            sys.exit(1)
        agent_id = sys.argv[2]
        atype = "unknown"
        caps = []
        for i, arg in enumerate(sys.argv[3:], 3):
            if arg == "--type" and i + 1 < len(sys.argv):
                atype = sys.argv[i + 1]
            elif arg == "--capabilities" and i + 1 < len(sys.argv):
                caps = sys.argv[i + 1].split(",")
        register_agent(agent_id, atype, caps)
        print(f"Registered agent: {agent_id} ({atype})")

    # ── add-milestone ──
    elif cmd == "add-milestone":
        if len(sys.argv) < 4:
            print("Usage: coord.py add-milestone <title> <description> [--tags t1,t2] [--priority high|med|low]")
            sys.exit(1)
        title = sys.argv[2]
        desc = sys.argv[3]
        tags = []
        prio = "medium"
        for i, arg in enumerate(sys.argv[4:], 4):
            if arg == "--tags" and i + 1 < len(sys.argv):
                tags = sys.argv[i + 1].split(",")
            elif arg == "--priority" and i + 1 < len(sys.argv):
                prio = sys.argv[i + 1]
        ms_id = add_milestone(title, desc, tags, prio)
        print(f"Milestone created: {ms_id}")

    # ── claim-milestone ──
    elif cmd == "claim-milestone":
        if len(sys.argv) < 4:
            print("Usage: coord.py claim-milestone <milestone_id> <agent_id>")
            sys.exit(1)
        ok = claim_milestone(sys.argv[2], sys.argv[3])
        print(f"{'Claimed' if ok else 'FAILED (not PENDING or ORPHANED)'}: {sys.argv[2]} → {sys.argv[3]}")

    # ── start-milestone ──
    elif cmd == "start-milestone":
        if len(sys.argv) < 4:
            print("Usage: coord.py start-milestone <milestone_id> <agent_id>")
            sys.exit(1)
        ok = start_milestone(sys.argv[2], sys.argv[3])
        print(f"{'Started' if ok else 'FAILED'}: {sys.argv[2]} → {sys.argv[3]}")

    # ── complete-milestone ──
    elif cmd == "complete-milestone":
        if len(sys.argv) < 4:
            print("Usage: coord.py complete-milestone <milestone_id> <agent_id>")
            sys.exit(1)
        ok = complete_milestone(sys.argv[2], sys.argv[3])
        print(f"{'Completed' if ok else 'FAILED'}: {sys.argv[2]}")

    # ── fail-milestone ──
    elif cmd == "fail-milestone":
        if len(sys.argv) < 5:
            print("Usage: coord.py fail-milestone <milestone_id> <agent_id> <reason>")
            sys.exit(1)
        ok = fail_milestone(sys.argv[2], sys.argv[3], sys.argv[4])
        print(f"{'Failed' if ok else 'FAILED'}: {sys.argv[2]}")

    # ── adopt ──
    elif cmd == "adopt":
        if len(sys.argv) < 4:
            print("Usage: coord.py adopt <milestone_id> <agent_id>")
            sys.exit(1)
        ok = adopt_milestone(sys.argv[2], sys.argv[3])
        print(f"{'Adopted' if ok else 'FAILED (not ORPHANED/PENDING)'}: {sys.argv[2]} → {sys.argv[3]}")

    # ── list-milestones ──
    elif cmd == "list-milestones":
        status_filter = None
        assignee_filter = None
        for i, arg in enumerate(sys.argv[2:], 2):
            if arg == "--status" and i + 1 < len(sys.argv):
                status_filter = sys.argv[i + 1]
            elif arg == "--assignee" and i + 1 < len(sys.argv):
                assignee_filter = sys.argv[i + 1]
        ms_list = list_milestones(status_filter, assignee_filter)
        if not ms_list:
            print("No milestones found.")
            return
        print(f"{'ID':22s} {'STATUS':12s} {'PRIO':7s} {'TITLE':48s} ASSIGNEE")
        print("-" * 100)
        for ms in ms_list:
            print(_format_milestone_row(ms))

    # ── add-progress ──
    elif cmd == "add-progress":
        if len(sys.argv) < 4:
            print("Usage: coord.py add-progress <milestone_id> <note>")
            sys.exit(1)
        ok = add_progress_note(sys.argv[2], sys.argv[3])
        print(f"Note added: {ok}")

    # ── heartbeat ──
    elif cmd == "heartbeat":
        if len(sys.argv) < 3:
            print("Usage: coord.py heartbeat <agent_id>")
            sys.exit(1)
        agent_heartbeat(sys.argv[2])
        print(f"Heartbeat: {sys.argv[2]}")

    # ── recover ──
    elif cmd == "recover":
        agent_id = None
        if sys.argv[2:]:
            for i, arg in enumerate(sys.argv[2:], 2):
                if arg == "--agent-id" and i + 1 < len(sys.argv):
                    agent_id = sys.argv[i + 1]
        # Phase 1: detect zombies
        zombies = expire_zombie_agents()
        if zombies:
            print(f"Zombie agents detected: {', '.join(zombies)}")
        # Phase 2: find orphans
        orphans = find_orphaned_milestones()
        if not orphans:
            print("No orphaned milestones. Project is clean.")
            # Show active milestone if any
            active = get_active_milestone()
            if active and active.get("milestone_id"):
                print(f"Active milestone: {active['milestone_id']} (by {active.get('claimed_by', '?')})")
            return
        print(f"\nOrphaned milestones ({len(orphans)}):")
        for ms in orphans:
            print(f"\n  {ms['id']}: {ms['title']}")
            print(f"    Status: {ms['status']} | Claimed by: {ms['claimed_by']}")
            print(f"    Notes: {len(ms.get('progress_notes', []))} entries")
            snap = get_latest_snapshot(ms['id'])
            if snap:
                print(f"    Latest snapshot: {snap.get('timestamp', '?')}")
                mm = snap.get("mental_model", {})
                if mm.get("current_focus"):
                    print(f"    Focus: {mm['current_focus']}")
                if mm.get("next_steps"):
                    print(f"    Next steps: {'; '.join(mm['next_steps'][:3])}")
        if agent_id:
            adopted = adopt_orphaned_milestones(agent_id)
            if adopted:
                print(f"\n✅ Adopted {len(adopted)} milestone(s) as {agent_id}")
                snap = get_latest_snapshot(adopted[0]["id"])
                if snap:
                    print(f"📋 Restored context from snapshot: {snap.get('timestamp', '?')}")
            else:
                print("\nNo milestones available for adoption.")

    # ── snapshot ──
    elif cmd == "snapshot":
        if len(sys.argv) < 4:
            print("Usage: coord.py snapshot <milestone_id> <agent_id> [--focus <text>] [--insights <text>] [--next-steps <text>]")
            sys.exit(1)
        ms_id = sys.argv[2]
        agent_id = sys.argv[3]
        focus = ""
        insights = []
        nsteps = []
        for i, arg in enumerate(sys.argv[4:], 4):
            if arg == "--focus" and i + 1 < len(sys.argv):
                focus = sys.argv[i + 1]
            elif arg == "--insights" and i + 1 < len(sys.argv):
                insights = sys.argv[i + 1].split(";")
            elif arg == "--next-steps" and i + 1 < len(sys.argv):
                nsteps = sys.argv[i + 1].split(";")
        fp = create_snapshot(ms_id, agent_id, focus, insights, nsteps)
        print(f"Snapshot saved: {fp}")

    # ── which-active ──
    elif cmd == "which-active":
        active = get_active_milestone()
        if not active or not active.get("milestone_id"):
            print("No active milestone.")
            return
        ms = find_milestone(active["milestone_id"])
        if ms:
            print(f"Active: {ms['id']} — {ms['title']} [{ms['status']}] by {active.get('claimed_by', '?')}")
        else:
            print(f"Active milestone record exists but not found in registry: {active['milestone_id']}")

    # ── agents ──
    elif cmd == "agents":
        all_flag = "--all" in sys.argv
        agents = list_agents(include_all=all_flag)
        if not agents:
            print("No active agents." if not all_flag else "No agents registered.")
            return
        for aid, info in agents.items():
            hb = info.get("heartbeat_at", "?")
            print(f"  {aid:24s} type={info.get('type','?'):10s} status={info.get('status','?'):10s} hb={hb}")

    # ── status ──
    elif cmd == "status":
        agents = list_agents(include_all=True)
        milestones = load_milestones()["milestones"]
        active = get_active_milestone()
        print(f"=== Project Coordination Status ===")
        print(f"Agents: {len(agents)} registered ({sum(1 for a in agents.values() if a.get('status')=='active')} active)")
        print(f"Milestones: {len(milestones)} total")
        for s in ("PENDING", "CLAIMED", "IN_PROGRESS", "COMPLETED", "FAILED", "ORPHANED"):
            cnt = sum(1 for m in milestones if m["status"] == s)
            if cnt:
                print(f"  {s}: {cnt}")
        if active and active.get("milestone_id"):
            ms = find_milestone(active["milestone_id"])
            if ms:
                print(f"Active: {ms['id']} — {ms['title']} by {active.get('claimed_by', '?')}")
        zombies = detect_zombie_agents()
        if zombies:
            print(f"⚠️  Zombie agents: {', '.join(zombies)} (heartbeat expired)")
        orphans = find_orphaned_milestones()
        if orphans:
            print(f"⚠️  Orphaned milestones: {len(orphans)}")

    # ── add-knowledge ──
    elif cmd == "add-knowledge":
        if len(sys.argv) < 4:
            print("Usage: coord.py add-knowledge <category> <content>")
            sys.exit(1)
        add_knowledge(sys.argv[2], sys.argv[3])
        print(f"Added to knowledge/{sys.argv[2]}.md")

    else:
        print(f"Unknown command: {cmd}\n")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()