#!/usr/bin/env python3
"""Derive touch/ownership timelines from a completed real-window feel gate."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def offset_ms(timestamp, start):
    return round((timestamp - start) / 1e6, 3)


def analyze(directory):
    report = json.loads((directory / "report.json").read_text())
    triage_path = directory / "triage.json"
    triage = json.loads(triage_path.read_text())
    require(report.get("triage_sha256") == sha(triage_path),
            "Formal triage identity differs")
    require(report.get("presses") == 60 and triage.get("presses") == 60,
            "Expected the complete 60-press product cohort")
    require((directory / "cohort" / "report.json").is_file() and
            report.get("cohort_sha256") == sha(directory / "cohort" / "report.json"),
            "Formal cohort identity differs")
    detail = []
    for seed in range(42, 57):
        match = directory / "cohort" / f"seed-{seed}"
        seed_report = json.loads((match / "report.json").read_text())
        actions_path = match / "actions.json"
        trace_path = match / "trace/events.jsonl"
        require(seed_report.get("trace_sha256") == sha(trace_path) and
                seed_report.get("actions_sha256") == sha(actions_path),
                f"Raw touch trace identity differs for seed {seed}")
        actions = json.loads(actions_path.read_text())
        require(len(actions) == len(seed_report["samples"]) == 4,
                f"Incomplete press sequence for seed {seed}")
        events = [json.loads(line) for line in trace_path.read_text().splitlines()]
        require(all("touch_pending_before" in event for event in events
                    if event.get("kind") == "anim_select") and
                all("ball_owned_team" in event for event in events
                    if event.get("kind") == "step"),
                f"Preselection touch or ownership observer missing for seed {seed}")
        for action, sample in zip(actions, seed_report["samples"]):
            require(action["index"] == sample["index"] and
                    action["direction"] == sample["direction"],
                    f"Press identity differs for seed {seed}")
            start, end = action["start_ns"], action["end_ns"]
            humans = [event for event in events
                      if event.get("kind") == "human_command" and
                      start <= event["time"] < end and
                      event.get("team_id") == 0 and
                      event.get("team_index") == sample["owned_player"]]
            players = {event["player"] for event in humans}
            aligned = [event for event in humans
                       if event.get("hid_x") == action["direction"] and
                       event.get("desired_x", 0) * action["direction"] > 0.1]
            first_aligned = aligned[0]["time"] if aligned else None
            selections = [event for event in events
                          if event.get("kind") == "anim_select" and
                          first_aligned is not None and
                          first_aligned <= event["time"] < end and
                          event.get("player") in players]
            new_touch = [event for event in selections
                         if event.get("accepted") is True and
                         event.get("command_type") in (2, 3) and
                         event.get("touch_pending") is True and
                         event.get("touch_pending_before") is False]
            rejected = [event for event in selections
                        if event.get("command_type") == 1 and
                        event.get("accepted") is False and
                        event.get("touch_pending_before") is True]
            touches = [event for event in events
                       if event.get("kind") == "ball_touch" and
                       start <= event["time"] <= end + 100_000_000 and
                       event.get("player") in players]
            steps = [event for event in events
                     if event.get("kind") == "step" and
                     start <= event["time"] < end]
            owner_steps = sum(event["ball_owned_team"] == 0 and
                              event["ball_owned_player"] == sample["owned_player"]
                              for event in steps)
            initial_pending = bool(selections and
                                   selections[0]["touch_pending_before"])
            first_aligned_ms = (offset_ms(first_aligned, start)
                                if first_aligned is not None else None)
            if first_aligned_ms is None or first_aligned_ms > 50:
                origin = "late_aligned_command"
            elif initial_pending:
                origin = "preexisting_touch"
            elif new_touch and offset_ms(new_touch[0]["time"], start) <= 50:
                origin = "new_touch_commit"
            elif rejected:
                origin = "pending_after_first_command"
            else:
                origin = "no_pending_movement_rejection"
            detail.append({"seed": seed, "index": action["index"],
                           "direction": action["direction"],
                           "origin": origin,
                           "first_aligned_command_ms": first_aligned_ms,
                           "pending_at_first_aligned_selection": initial_pending,
                           "new_touch_selection_ms": (offset_ms(new_touch[0]["time"], start)
                                                      if new_touch else None),
                           "new_touch_frame": (new_touch[0]["touch_frame"]
                                               if new_touch else None),
                           "rejected_movement_while_touch_pending": len(rejected),
                           "first_actual_touch_ms": (offset_ms(touches[0]["time"], start)
                                                     if touches else None),
                           "actual_touch_count": len(touches),
                           "owned_steps": owner_steps, "observed_steps": len(steps),
                           "velocity_response_ms": sample.get("velocity_response_ms")})
    require(len(detail) == 60, "Incomplete touch causality summary")
    touch_cases = {(case["seed"], case["index"]) for case in triage["cases"]
                   if case["diagnostic_cause"] == "touch_pending" and
                   case["violation"]}
    selected = [row for row in detail if (row["seed"], row["index"]) in touch_cases]
    return {"formal_report_sha256": sha(directory / "report.json"),
            "formal_triage_sha256": sha(triage_path),
            "touch_cases": len(selected),
            "touch_origin_counts": dict(sorted(Counter(row["origin"]
                                                       for row in selected).items())),
            "touch_cases_with_actual_contact": sum(row["actual_touch_count"] > 0
                                                   for row in selected),
            "cases": selected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = analyze(args.input.resolve())
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items()
                      if key != "cases"}, sort_keys=True))


if __name__ == "__main__":
    main()
