#!/usr/bin/env python3
"""Evidence-backed milestone / plan / task acceptance, executed serially in WSL."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import time


class QualityError(RuntimeError):
    pass


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def exclusive_lock(path):
    # Kernel locks are released even if the agent or runner crashes. Never delete
    # this file: unlinking it would let another process lock a different inode.
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise QualityError("Another acceptance run is active; concurrent builds are forbidden") from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class Program:
    def __init__(self, root, manifest=None):
        self.root = Path(root).resolve()
        self.manifest_path = manifest or self.root / ".project/optimization/program.json"
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.evidence_dir = self.root / ".project/optimization/evidence"
        self.nodes = self._unique(self.manifest["nodes"], "node")
        self.checks = self._unique(self.manifest["checks"], "check")
        self.validate()

    @staticmethod
    def _unique(items, label):
        result = {}
        for item in items:
            name = item["id"]
            if not re.fullmatch(r"[a-z][a-z0-9_.-]*", name) or name in result:
                raise QualityError(f"Invalid or duplicate {label}: {name}")
            result[name] = item
        return result

    def validate(self):
        if self.manifest.get("version") != 1:
            raise QualityError("Unsupported manifest version")
        owners = {}
        for name, node in self.nodes.items():
            kind = node["kind"]
            if kind not in ("milestone", "plan", "task") or not node.get("acceptance"):
                raise QualityError(f"Missing kind or acceptance criteria: {name}")
            children = node.get("children", [])
            if (kind == "task") == bool(children):
                raise QualityError(f"Tasks must be leaves; plans/milestones must have children: {name}")
            for child in children:
                if child in owners or child not in self.nodes:
                    raise QualityError(f"Missing child or multiple parents: {child}")
                owners[child] = name
                expected = "plan" if kind == "milestone" else "task"
                if self.nodes[child]["kind"] != expected:
                    raise QualityError(f"Invalid hierarchy: {name} -> {child}")
            for dependency in node.get("depends_on", []):
                if dependency not in self.nodes:
                    raise QualityError(f"Missing dependency: {name} -> {dependency}")
            if not node.get("checks"):
                raise QualityError(f"Missing acceptance checks: {name}")
            for check in node["checks"]:
                if check not in self.checks:
                    raise QualityError(f"Unknown check {check} in {name}")
        for name, node in self.nodes.items():
            if (node["kind"] != "milestone") != (name in owners):
                raise QualityError(f"Invalid parent for {name}")
        for name, check in self.checks.items():
            if not check.get("acceptance") or type(check.get("ready")) is not bool:
                raise QualityError(f"Missing readiness or acceptance: {name}")
            if check["ready"]:
                argv = check.get("argv")
                if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
                    raise QualityError(f"Expected nonempty argv array: {name}")
                if check.get("kind") not in ("command", "unittest", "json"):
                    raise QualityError(f"Unsupported check kind: {name}")
                if not check.get("sources") or not 0 < check.get("timeout", 0) <= 7200:
                    raise QualityError(f"Missing source scope or timeout: {name}")
                if check["kind"] != "command" and check.get("min_assertions", 0) < 1:
                    raise QualityError(f"Tests require a positive assertion count: {name}")
        self.order(list(self.nodes))

    def order(self, targets):
        visiting, visited, ordered = set(), set(), []

        def visit(name):
            if name not in self.nodes:
                raise QualityError(f"Unknown target: {name}")
            if name in visiting:
                raise QualityError(f"Dependency cycle at {name}")
            if name in visited:
                return
            visiting.add(name)
            node = self.nodes[name]
            for dependency in node.get("depends_on", []) + node.get("children", []):
                visit(dependency)
            visiting.remove(name)
            visited.add(name)
            ordered.append(name)

        for target in targets:
            visit(target)
        return ordered

    def fingerprint(self, name):
        check = self.checks[name]
        sources = {}
        # Check definition and runner implementation also invalidate old evidence.
        runner = Path(__file__).resolve()
        sources["@runner"] = file_hash(runner)
        for pattern in check["sources"]:
            relative = Path(pattern)
            if relative.is_absolute() or ".." in relative.parts:
                raise QualityError(f"Source scope escapes workspace: {pattern}")
            paths = sorted(path for path in self.root.glob(pattern) if path.is_file())
            if not paths:
                raise QualityError(f"Source scope matched no files: {pattern}")
            for path in paths:
                if not path.resolve().is_relative_to(self.root):
                    raise QualityError(f"Source symlink escapes workspace: {path}")
                sources[str(path.relative_to(self.root))] = file_hash(path)
        toolchain = {}
        for tool in check.get("tools", [check["argv"][0]]):
            executable = shutil.which(tool)
            if executable is None:
                toolchain[tool] = "missing"
            else:
                resolved = Path(executable).resolve()
                toolchain[tool] = {"path": str(resolved), "sha256": file_hash(resolved)}
        environment = {name: os.environ.get(name) for name in check.get("environment", [])}
        payload = {"check": check, "sources": sources, "root": str(self.root),
                   "platform": platform.platform(), "python": sys.version,
                   "toolchain": toolchain, "environment": environment}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def check_state(self, name):
        if not self.checks[name]["ready"]:
            return "planned"
        evidence = self.evidence_dir / f"{name}.json"
        if not evidence.exists():
            return "pending"
        try:
            record = json.loads(evidence.read_text())
            if record["fingerprint"] != self.fingerprint(name):
                return "stale"
            log = self.evidence_dir / record["log"]
            if log.parent != self.evidence_dir or not log.is_file():
                return "invalid"
            if file_hash(log) != record["log_sha256"]:
                return "invalid"
            return "verified" if record["passed"] is True else "failed"
        except (KeyError, ValueError, OSError, QualityError):
            return "invalid"

    def states(self):
        check_states = {name: self.check_state(name) for name in self.checks}
        result = {}
        for name in self.order(list(self.nodes)):
            node = self.nodes[name]
            own = [check_states[check] for check in node["checks"]]
            dependencies = [result[item] for item in node.get("depends_on", []) + node.get("children", [])]
            statuses = own + dependencies
            result[name] = ("verified" if all(s == "verified" for s in statuses)
                            else next((s for s in ("failed", "invalid", "stale", "planned", "pending") if s in statuses), "pending"))
        return result

    @staticmethod
    def assess(check, returncode, output):
        if returncode != 0:
            return False, f"Command exited with {returncode}"
        if check["kind"] == "command":
            return True, "Command completed"
        minimum = check["min_assertions"]
        if check["kind"] == "unittest":
            counts = re.findall(r"^Ran (\d+) tests? in ", output, re.MULTILINE)
            success = bool(counts) and int(counts[-1]) >= minimum and bool(re.search(r"^OK\s*$", output, re.MULTILINE))
            return success, "unittest requires sufficient tests, zero failures, zero skips"
        try:
            summary = json.loads(output.strip().splitlines()[-1])
            success = (summary["passed"] is True and type(summary["assertions"]) is int
                       and summary["assertions"] >= minimum and summary.get("skipped", 0) == 0)
            return success, "Structured assertions evaluated"
        except (ValueError, KeyError, IndexError, TypeError):
            return False, "Missing structured assertion summary"

    def run_check(self, name):
        check = self.checks[name]
        fingerprint = self.fingerprint(name)
        started = time.time()
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        log_name = f"{name}-{time.time_ns()}.log"
        log_path = self.evidence_dir / log_name
        reason, passed = "", False
        returncode = None
        # A real file avoids pipe deadlocks and unbounded parent-process memory.
        # Process groups allow timeout cleanup of the compiler/test descendants.
        with log_path.open("wb") as log:
            process = None
            try:
                process = subprocess.Popen(check["argv"], cwd=self.root, stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                returncode = process.wait(timeout=check["timeout"])
            except subprocess.TimeoutExpired:
                reason = f"Timeout after {check['timeout']} seconds"
            except OSError as error:
                reason = str(error)
            finally:
                if process is not None:
                    # Kill only this check's group, including descendants left
                    # behind by a wrapper which returned early.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
        # Keep the final 1 MiB for parsing; preserve the complete log as evidence.
        with log_path.open("rb") as log:
            log.seek(max(0, log_path.stat().st_size - 1024 * 1024))
            output = log.read().decode("utf-8", errors="replace")
        if not reason:
            passed, reason = self.assess(check, returncode, output)
        if fingerprint != self.fingerprint(name):
            passed, reason = False, "Sources changed while the check was running"
        record = {"check": name, "fingerprint": fingerprint, "passed": passed,
                  "reason": reason, "returncode": returncode, "started": started,
                  "duration_seconds": round(time.time() - started, 3), "argv": check["argv"],
                  "log": log_name, "log_sha256": file_hash(log_path)}
        atomic_json(self.evidence_dir / f"{name}.json", record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
        if not passed:
            raise QualityError(f"Check failed: {name}; see {log_path}")

    def run(self, target, force=False):
        with exclusive_lock(self.evidence_dir / "run.lock"):
            ordered = self.order([target])
            checks = list(dict.fromkeys(check for name in ordered for check in self.nodes[name]["checks"]))
            unavailable = [check for check in checks if not self.checks[check]["ready"]]
            if unavailable:
                raise QualityError(f"Acceptance implementation is still planned: {', '.join(unavailable)}")
            for check in checks:
                if force or self.check_state(check) != "verified":
                    self.run_check(check)
            if self.states()[target] != "verified":
                raise QualityError(f"Target has no current passing evidence: {target}")

    def docs(self):
        for name, node in self.nodes.items():
            folder = {"milestone": "milestones", "plan": "plans", "task": "tasks"}[node["kind"]]
            path = self.root / ".project" / folder / f"{name}.md"
            lines = [f"# {name} — {node['title']}", "", f"类型：{node['kind']}", "",
                     "状态由 `python3 .project/quality.py status` 根据当前源码和验收证据计算。", "",
                     "验收条件：", ""] + [f"- {item}" for item in node["acceptance"]]
            for field, title in (("depends_on", "依赖"), ("children", "执行顺序"), ("checks", "验收检查")):
                lines += ["", f"{title}：" + ("、".join(node.get(field, [])) or "无")]
            lines += ["", f"执行：`python3 .project/quality.py run {name}`", "",
                      "实现未就绪、检查失败、证据过期或子任务未通过时，不能完成。", ""]
            content = "\n".join(lines)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                path.write_text(content, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "status", "next", "run", "verify", "docs"))
    parser.add_argument("target", nargs="?")
    parser.add_argument("--force", action="store_true", help="Rerun even with current passing evidence")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        if os.name != "posix":
            raise QualityError("Run acceptance inside WSL/Linux; Windows Git misreports this workspace")
        program = Program(args.root)
        if args.action == "validate":
            print(f"Valid: {len(program.nodes)} nodes, {len(program.checks)} checks")
        elif args.action == "docs":
            program.docs()
        elif args.action == "run":
            program.run(args.target, args.force)
        else:
            states = program.states()
            if args.action == "next":
                for name in program.order(list(program.nodes)):
                    node = program.nodes[name]
                    if node["kind"] == "task" and states[name] != "verified" and all(
                        states[dependency] == "verified" for dependency in node.get("depends_on", [])
                    ):
                        print(json.dumps({"id": name, "state": states[name], "title": node["title"]}, ensure_ascii=False))
                        break
            elif args.action == "verify":
                if args.target not in states or states[args.target] != "verified":
                    raise QualityError(f"Not verified: {args.target} ({states.get(args.target, 'unknown')})")
                print(f"Verified: {args.target}")
            else:
                if args.target and args.target not in states:
                    raise QualityError(f"Unknown target: {args.target}")
                print(json.dumps({name: {"state": state, "title": program.nodes[name]["title"]}
                                  for name, state in states.items()
                                  if name == args.target or (not args.target and program.nodes[name]["kind"] == "milestone")},
                                 ensure_ascii=False, indent=2))
    except (QualityError, ValueError, KeyError, OSError) as error:
        print(f"quality: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
