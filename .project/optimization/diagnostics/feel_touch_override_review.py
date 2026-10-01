#!/usr/bin/env python3
"""Summarize ball-relative manual input, contact and ownership in a feel cohort.

This is diagnostic evidence. It does not change or replace product acceptance.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def offset_ms(event, start):
    return round((event["time"] - start) / 1_000_000, 3)


def review(directory):
    cohort_path = directory / "report.json"
    cohort = json.loads(cohort_path.read_text())
    matches = {row["seed"]: directory / Path(row["path"]).parent
               for row in cohort["matches"]}
    if len(matches) != len(cohort["matches"]):
        raise ValueError("Duplicate match seed")
    cases = []
    raw_hashes = {}
    for seed, match_dir in sorted(matches.items()):
        actions_path = match_dir / "actions.json"
        events_path = match_dir / "trace/events.jsonl"
        actions = {row["index"]: row for row in json.loads(actions_path.read_text())}
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        steps = [row for row in events if row.get("kind") == "step"]
        commands = [row for row in events if row.get("kind") == "human_command"]
        touches = [row for row in events if row.get("kind") == "ball_touch"]
        raw_hashes[str(seed)] = {"actions": digest(actions_path),
                                 "events": digest(events_path)}
        for sample in (row for row in cohort["samples"] if row["seed"] == seed):
            action = actions[sample["index"]]
            if action["direction"] != sample["direction"]:
                raise ValueError(f"Direction mismatch: {seed}/{sample['index']}")
            start, end = action["start_ns"], action["end_ns"]
            direction = action["direction"]
            aligned = next((row for row in commands
                            if start <= row["time"] < end and
                            row.get("team_id") == 0 and
                            row.get("team_index") == sample["owned_player"] and
                            row.get("hid_x") == direction and
                            row.get("desired_x", 0) * direction > 0.1 and
                            row.get("desired_speed", 0) > 0), None)
            if aligned is None:
                raise ValueError(f"Missing aligned command: {seed}/{sample['index']}")
            if abs(offset_ms(aligned, start) - sample["first_aligned_command_ms"]) > 0.002:
                raise ValueError(f"Command timing mismatch: {seed}/{sample['index']}")
            prior_steps = [row for row in steps if row["time"] <= aligned["time"]]
            if not prior_steps:
                raise ValueError(f"Missing preceding step: {seed}/{sample['index']}")
            step = prior_steps[-1]
            ball_dx = step["ball_x"] - aligned["player_x"]
            ball_dy = step["ball_y"] - aligned["player_y"]
            ball_distance = (ball_dx * ball_dx + ball_dy * ball_dy) ** 0.5
            input_ball_dot = aligned["desired_x"] * ball_dx + aligned["desired_y"] * ball_dy
            actual_touches = [row for row in touches
                              if start <= row["time"] <= end + 100_000_000 and
                              row.get("player") == aligned["player"]]
            active_steps = [row for row in steps if start <= row["time"] < end]
            owned_steps = sum(row.get("ball_owned_team") == 0 and
                              row.get("ball_owned_player") == sample["owned_player"]
                              for row in active_steps)
            cases.append({"seed": seed, "index": sample["index"],
                          "direction": direction, "response_ms": sample.get("velocity_response_ms"),
                          "accepted_movement_ms": sample.get("first_accepted_aligned_movement_ms"),
                          "first_aligned_ms": offset_ms(aligned, start),
                          "ball_distance_m": round(ball_distance, 3),
                          "input_ball_dot_m": round(input_ball_dot, 3),
                          "input_away_from_ball": ball_distance > 0.7 and input_ball_dot < -0.1,
                          "first_actual_touch_ms": (offset_ms(actual_touches[0], start)
                                                    if actual_touches else None),
                          "actual_touch_count": len(actual_touches),
                          "owned_steps": owned_steps,
                          "observed_steps": len(active_steps)})
    if len(cases) != len(cohort["samples"]):
        raise ValueError("Cohort cases incomplete")
    violations = [row for row in cases
                  if row["response_ms"] is None or row["response_ms"] > 50]
    return {"diagnostic_only": True, "cohort_report_sha256": digest(cohort_path),
            "raw_sha256": raw_hashes, "presses": len(cases),
            "responses": sum(row["response_ms"] is not None for row in cases),
            "violations_over_50ms": len(violations),
            "away_from_ball_presses": sum(row["input_away_from_ball"] for row in cases),
            "presses_with_actual_touch": sum(row["actual_touch_count"] > 0 for row in cases),
            "cases": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cohort", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = review(args.cohort.resolve())
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("cases", "raw_sha256")}, sort_keys=True))


if __name__ == "__main__":
    main()
