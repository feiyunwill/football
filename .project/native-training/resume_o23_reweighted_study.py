"""Recover an interrupted preregistered schema6 study without rerunning a chunk."""
import argparse, hashlib, json, math, os, subprocess, sys, time
from pathlib import Path

import psutil

from run_o23_averaging import policy as decode_policy
from audit_o23_study import native_start
from validate import ROOT, sha, source_fingerprint

SEEDS = (42, 123, 2026, 31415, 271828)


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def resource_peak(path, name):
    peak = 0
    if path.exists():
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row["command"] == name:
                peak = max(peak, row["rss"])
    return peak


def verified_chunk(root, seed, target):
    name = f"train-reweighted-{seed}-u{target}"
    data = read(root / f"{name}.log")
    checkpoint = root / "models" / f"reweighted-{seed}-u{target}.fppo"
    assert checkpoint.exists() and (root / f"{name}.stderr").read_text() == ""
    assert data["scenario"] == "2v1_broad_reweighted" and data["seed"] == seed
    assert data["hidden"] == 64 and data["cadence"] == 10 and data["episode_limit"] == 256
    assert data["start_version"] == target - 256 and data["version"] == target
    assert data["total_transitions"] == target * 256
    assert data["evaluation"]["isolated"] and data["state_before_evaluation_sha256"] == data["state_sha256"] == sha(checkpoint)
    assert len(data["iterations"]) == 256
    for row in data["iterations"]:
        assert row["learning_rate"] == .0003 * max(.1, (8193 - row["version"]) / 8192)
        assert row["optimizer_steps"] == 16 and row["transitions"] == 256
        assert all(math.isfinite(row[key]) for key in ("loss", "entropy", "gradient_norm", "parameter_delta"))
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--starts", type=Path, required=True)
    args = parser.parse_args()
    root = args.study.resolve()
    protocol = read(root / "protocol.json")
    progress = read(root / "progress.json")
    assert not (root / "report.json").exists()
    assert source_fingerprint() == protocol["source"]
    assert all(sha(Path(path)) == digest for path, digest in protocol["frozen"].items())
    build = args.build.resolve()
    binary = build / "bin" / "native_ppo_train"
    assert binary.exists() and sha(binary) == protocol["frozen"][str(binary)]
    assert sha(args.starts) == protocol["frozen"][str(args.starts.resolve())]
    resources = root / "resources.jsonl"
    commands = list(progress["commands"])
    records = list(progress["models"])
    existing = {row["name"] for row in commands}
    recovered = []
    training_seconds = sum(row["seconds"] for row in commands if row["name"].startswith("train-reweighted-"))
    env = dict(os.environ, LD_LIBRARY_PATH=str(build), GFOOTBALL_DATA_DIR=str(ROOT / "engine/data"), GFOOTBALL_FONT=str(ROOT / "engine/fonts/AlegreyaSansSC-ExtraBold.ttf"))

    def append_existing(name, argv, training=False):
        nonlocal training_seconds
        if name in existing:
            return
        log = root / f"{name}.log"
        stderr = root / f"{name}.stderr"
        assert log.exists() and stderr.exists() and stderr.read_text() == ""
        # The child had completed and flushed its result when the parent disappeared.
        row = dict(name=name, argv=list(map(str, argv)), exit_code=0, seconds=0.0,
                   observed_peak_rss=resource_peak(resources, name), stdout_sha256=sha(log), stderr_sha256=sha(stderr),
                   recovered_after_parent_interruption=True)
        commands.append(row); existing.add(name); recovered.append(name)

    def run(name, argv, cap):
        nonlocal training_seconds
        start = time.monotonic(); peak = 0; reason = None; last_sample = 0
        print(name, flush=True)
        with (root / f"{name}.log").open("w") as stream, (root / f"{name}.stderr").open("w") as errors, resources.open("a") as samples:
            child = subprocess.Popen(list(map(str, argv)), cwd=build, env=env, stdout=stream, stderr=errors)
            proc = psutil.Process(child.pid)
            while child.poll() is None:
                elapsed = time.monotonic() - start
                if elapsed > cap: reason = "Wall budget"
                try:
                    rss = proc.memory_info().rss; peak = max(peak, rss)
                    if rss > 512 * 1024 * 1024: reason = "RSS budget"
                    if elapsed - last_sample >= 2:
                        cpu = proc.cpu_times(); samples.write(json.dumps(dict(command=name, seconds=elapsed, rss=rss, fds=proc.num_fds(), user=cpu.user, system=cpu.system)) + "\n"); samples.flush(); last_sample = elapsed
                        if sum(item.stat().st_size for item in root.rglob("*") if item.is_file()) > 2 * 1024**3: reason = "Output budget"
                except psutil.NoSuchProcess:
                    pass
                if reason:
                    child.terminate()
                    try: child.wait(timeout=5)
                    except subprocess.TimeoutExpired: child.kill(); child.wait()
                    break
                time.sleep(.2)
        seconds = time.monotonic() - start
        commands.append(dict(name=name, argv=list(map(str, argv)), exit_code=child.returncode, seconds=seconds, observed_peak_rss=peak, stdout_sha256=sha(root / f"{name}.log"), stderr_sha256=sha(root / f"{name}.stderr")))
        assert reason is None and child.returncode == 0, (name, reason)
        return seconds

    try:
        for seed in SEEDS:
            if any(model["seed"] == seed for model in records):
                continue
            seed_seconds = 0.0; completed = 0; chunks = []
            for target in range(256, 8193, 256):
                name = f"train-reweighted-{seed}-u{target}"
                checkpoint = root / "models" / f"reweighted-{seed}-u{target}.fppo"
                policy = root / "models" / f"reweighted-{seed}-u{target}.fpol"
                argv = [binary, "--scenario", "2v1_broad_reweighted", "--seed", seed, "--hidden", 64, "--epochs", 4, "--minibatch", 64, "--rollout", 256, "--cadence", 10, "--episode-limit", 256, "--no-initial-eval", "--eval-episodes", 0, "--updates", 256, "--save", checkpoint]
                if target > 256: argv += ["--load", root / "models" / f"reweighted-{seed}-u{target-256}.fppo"]
                if target in (7424, 7680, 7936, 8192): argv += ["--export-policy", policy]
                log = root / f"{name}.log"
                if log.exists() and log.stat().st_size:
                    data = verified_chunk(root, seed, target); append_existing(name, argv, True)
                else:
                    # A zero-byte log proves that the child did not emit its terminal
                    # JSON. Preserve its checkpoint for forensics, then replay this
                    # exact deterministic chunk from the preceding durable checkpoint.
                    if log.exists():
                        for artifact in (log, root / f"{name}.stderr", checkpoint):
                            if artifact.exists():
                                artifact.replace(artifact.with_name(artifact.name + ".interrupted"))
                    cap = min(protocol["budget"]["max_wall_seconds_per_training_run"] - seed_seconds, protocol["budget"]["max_total_training_wall_seconds"] - training_seconds)
                    assert cap > 0
                    elapsed = run(name, argv, cap); seed_seconds += elapsed; training_seconds += elapsed
                    data = verified_chunk(root, seed, target)
                completed += sum(row["completed_episodes"] for row in data["iterations"])
                chunks.append(dict(version=target, checkpoint_sha256=sha(checkpoint)))
            start_name = f"starts-reweighted_mean4-{seed}"
            start_log = root / f"{start_name}.log"
            if start_log.exists(): append_existing(start_name, [args.starts, 6, seed, completed + 1])
            else: run(start_name, [args.starts, 6, seed, completed + 1], 120)
            rows = [json.loads(line) for line in start_log.read_text().splitlines()]
            final = root / "models" / f"reweighted-{seed}-u8192.fppo"
            assert len(rows) == completed + 1
            actual = native_start(final, seed, 6, 8192)
            assert all(actual[key] == rows[actual["episode"]][key] for key in ("engine_seed", "geometry", "ball"))
            members = []; weights = []; headers = []
            for version in (7424, 7680, 7936, 8192):
                checkpoint = root / "models" / f"reweighted-{seed}-u{version}.fppo"; policy = root / "models" / f"reweighted-{seed}-u{version}.fpol"
                header, values = decode_policy(policy); assert int(header[3]) == seed and int(header[4]) == 64 and header[6] == sha(checkpoint)
                headers.append(header); weights.append(values); members.append(dict(version=version, weight=.25, checkpoint=str(checkpoint), checkpoint_sha256=sha(checkpoint), policy=str(policy), policy_sha256=sha(policy)))
            assert len({header[5] for header in headers}) == 1
            manifest = root / "models" / f"{seed}-provenance.json"; write(manifest, dict(schema="within_seed_mean4_v1", seed=seed, members=members, derived_inference_only=True, algorithm="Binary64 fsum,ascending versions,divide by4"))
            averaged = [math.fsum(column) / 4 for column in zip(*weights)]; assert len(averaged) == 8724
            header = headers[0].copy(); header[6] = sha(manifest); payload = " ".join(header) + "\n" + "".join(format(value, ".17g") + "\n" for value in averaged)
            derived = root / "models" / f"reweighted-mean4-{seed}.fpol"; derived.write_text("FPOL1\n" + hashlib.sha256(payload.encode()).hexdigest() + "\n" + payload)
            records.append(dict(configuration="reweighted_mean4", seed=seed, chunks=chunks, initial_version=0, final_version=8192, path=str(final), sha256=sha(final), raw_policy=str(root / "models" / f"reweighted-{seed}-u8192.fpol"), raw_policy_sha256=sha(root / "models" / f"reweighted-{seed}-u8192.fpol"), policy=str(derived), policy_sha256=sha(derived), policy_kind="within_seed_mean4_v1", members=members, provenance_manifest=str(manifest), provenance_sha256=sha(manifest), conservative_episode_starts=completed+1, starts_sha256=sha(start_log), training_seconds=seed_seconds))
        validation = []
        cases = root / "cases.txt"; ids = [tuple(map(int, line.split()[:2] + [line.split()[3]])) for line in cases.read_text().splitlines()]
        for model in records:
            seed = model["seed"]; name = f"validation-reweighted_mean4-{seed}"; argv = [binary, "--inference-mode", "balanced", "--policy", model["policy"], "--inference-cases", cases]
            if (root / f"{name}.log").exists(): append_existing(name, argv)
            else: run(name, argv, 300)
            rows = [json.loads(line) for line in (root / f"{name}.log").read_text().splitlines()]; summary = rows.pop(); assert summary["complete"] and len(rows) == 200 and [(row["index"], row["group"], row["engine_seed"]) for row in rows] == ids
            validation.append(dict(seed=seed, goals=sum(row["controlled_score_delta"] > 0 for row in rows), passes=sum(row["completed_passes"] > 0 for row in rows), joint=sum(row["completed_passes"] > 0 and row["controlled_score_delta"] > 0 for row in rows), groups=[sum(row["controlled_score_delta"] > 0 for row in rows if row["group"] == group) for group in range(5)]))
        total = sum(cell["goals"] for cell in validation); groups = [sum(cell["groups"][group] for cell in validation) for group in range(5)]
        old = read(Path(protocol["old_study"]) / "report.json")
        gates = dict(mean=total >= 970, every_seed=all(cell["goals"] >= 180 for cell in validation), groups=all(value >= 180 for value in groups), cooperation=all(cell["passes"] >= 40 and cell["joint"] >= 40 for cell in validation), original_legacy_improvement=total >= sum(cell["legacy"]["success_count"] for cell in old["validation"]) + 20)
        report = dict(passed=True, validation_passed=all(gates.values()), source_before=protocol["source"], source_after=source_fingerprint(), protocol_sha256=sha(root / "protocol.json"), quality=read(Path(protocol["quality"]) / "report.json"), commands=commands, models=records, regressions=progress["regressions"], portable_regression_passed=True, validation=validation, known_pilot_prefix_matches=progress["known_pilot_prefix_matches"], candidate_mean=total/1000, candidate_group_means=[value/200 for value in groups], gates=gates, selected="reweighted_mean4" if all(gates.values()) else None, confirmation_opened=False, training_seconds=training_seconds, resources_sha256=sha(resources), interruption_recovery=dict(parent_progress_active=progress["active_command"], recovered_commands=recovered, method="verified completed child outputs before continuing from exact FPPO checkpoints"))
    except BaseException as error:
        report = dict(passed=False, validation_passed=False, error=f"{type(error).__name__}: {error}", source_before=protocol["source"], source_after=source_fingerprint(), protocol_sha256=sha(root / "protocol.json"), commands=commands, models=records, regressions=progress.get("regressions", []), validation=[], training_seconds=training_seconds, resources_sha256=sha(resources))
    write(root / "report.json", report)
    print(json.dumps({key: report.get(key) for key in ("passed", "validation_passed", "candidate_mean", "error")}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
