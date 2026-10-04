"""Accepted touch animations count only after real, same-player contact."""

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "optimization/diagnostics/feel_latency_window.py"
spec = importlib.util.spec_from_file_location("feel_latency_window", SCRIPT)
feel_window = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feel_window)


def fixture_rows(touch_player="controlled", touch_time_ms=80, include_selection=True):
    start = 1_000_000_000
    ms = 1_000_000
    rows = [
        {"kind": "step", "time": start - 10 * ms, "index": 0, "x": 0,
         "owned": 7, "player_x": 0.0},
        {"kind": "step_timing", "index": 0, "vx": 0.0,
         "in_play": True, "game_mode": 0},
        {"kind": "human_command", "time": start + 5 * ms,
         "player": "controlled", "team_id": 0, "team_index": 7,
         "hid_x": 1, "desired_x": 1, "desired_speed": 5,
         "actual_vx": 0.0, "player_x": 0.0},
        {"kind": "step", "time": start + 10 * ms, "index": 1, "x": 1,
         "owned": 7, "player_x": 0.01},
        {"kind": "step_timing", "index": 1, "vx": 0.0,
         "in_play": True, "game_mode": 0},
        {"kind": "swap", "time": start + 15 * ms, "index": 1,
         "render_owner": True},
        {"kind": "step", "time": start + 30 * ms, "index": 2, "x": 1,
         "owned": 7, "player_x": 0.02},
        {"kind": "step_timing", "index": 2, "vx": 0.2,
         "in_play": True, "game_mode": 0},
        {"kind": "swap", "time": start + 35 * ms, "index": 2,
         "render_owner": True},
        {"kind": "ball_touch", "time": start + touch_time_ms * ms,
         "player": touch_player, "touch_type": 0},
    ]
    if include_selection:
        rows.append({"kind": "anim_select", "time": start + 6 * ms,
                     "player": "controlled", "command_type": 2,
                     "desired_x": 1, "accepted": True})
    return rows, [{"index": 0, "start_ns": start,
                   "end_ns": start + 100 * ms, "direction": 1}]


def analyze_case(**kwargs):
    rows, actions = fixture_rows(**kwargs)
    with TemporaryDirectory() as directory, patch.object(feel_window, "events", return_value=rows):
        return feel_window.analyze(Path(directory), actions, require_causal=True)["samples"][0]


def handoff_case(include_command=True, include_selection=True):
    start = 1_000_000_000
    ms = 1_000_000
    rows = [
        {"kind": "step", "time": start - 10 * ms, "index": 0, "x": 0,
         "owned": 7, "player_x": 0.0},
        {"kind": "step_timing", "index": 0, "vx": 0.0,
         "in_play": True, "game_mode": 0},
        {"kind": "step", "time": start + 10 * ms, "index": 1, "x": -1,
         "owned": 2, "player_x": 0.03},
        {"kind": "step_timing", "index": 1, "vx": 0.6,
         "in_play": True, "game_mode": 0},
        {"kind": "swap", "time": start + 15 * ms, "index": 1,
         "render_owner": True},
    ]
    if include_command:
        rows.extend([
            {"kind": "human_command", "time": start + 5 * ms,
             "player": "successor", "team_id": 0, "team_index": 2,
             "hid_x": -1, "desired_x": 0.5, "desired_speed": 5,
             "actual_vx": 1.0, "player_x": 0.0},
            {"kind": "human_command", "time": start + 7 * ms,
             "player": "successor", "team_id": 0, "team_index": 2,
             "hid_x": -1, "desired_x": -1, "desired_speed": 5,
             "actual_vx": 0.9, "player_x": 0.01},
        ])
    if include_selection:
        rows.append({"kind": "anim_select", "time": start + 8 * ms,
                     "player": "successor", "command_type": 1,
                     "desired_x": -1, "accepted": True})
    actions = [{"index": 0, "start_ns": start,
                "end_ns": start + 100 * ms, "direction": -1}]
    with TemporaryDirectory() as directory, patch.object(feel_window, "events", return_value=rows):
        return feel_window.analyze(Path(directory), actions, require_causal=True)["samples"][0]


class CausalTouchTests(unittest.TestCase):
    def test_same_owner_uses_velocity_at_command_instead_of_older_step(self):
        rows, actions = fixture_rows()
        rows[1]["vx"] = -.245
        rows[2]["actual_vx"] = -.497
        rows[4]["vx"] = -.198
        next(row for row in rows if row["kind"] == "anim_select")["command_type"] = 1
        with TemporaryDirectory() as directory, patch.object(feel_window, "events", return_value=rows):
            sample = feel_window.analyze(Path(directory), actions, require_causal=True)["samples"][0]
        self.assertEqual(sample["status"], "admitted")
        self.assertEqual(sample["baseline_vx"], -.497)
        self.assertEqual(sample["pre_selection_vx"], -.497)
        self.assertEqual(sample["velocity_response_ms"], 10)

    def test_command_after_input_admission_uses_next_physics_step(self):
        rows, actions = fixture_rows()
        start = actions[0]["start_ns"]
        command = next(row for row in rows if row["kind"] == "human_command")
        choice = next(row for row in rows if row["kind"] == "anim_select")
        command["time"] = start + 35_000_000
        choice["time"] = start + 36_000_000
        choice["command_type"] = 1
        rows.extend([{"kind": "step", "time": start + 45_000_000,
                      "index": 3, "x": 1, "owned": 7, "player_x": 0.03},
                     {"kind": "step_timing", "index": 3, "vx": 0.3,
                      "in_play": True, "game_mode": 0},
                     {"kind": "swap", "time": start + 50_000_000,
                      "index": 3, "render_owner": True}])
        with TemporaryDirectory() as directory, patch.object(feel_window, "events", return_value=rows):
            sample = feel_window.analyze(Path(directory), actions, require_causal=True)["samples"][0]
        self.assertEqual(sample["status"], "admitted")
        self.assertEqual(sample["input_admission_ms"], 10)
        self.assertEqual(sample["velocity_response_ms"], 45)

    def test_transition_retry_requires_only_off_play_simulation_steps(self):
        start = 1_000_000_000
        off_play = [{"kind": "step", "time": start + 10, "index": 1},
                    {"kind": "step_timing", "index": 1, "in_play": False}]
        self.assertTrue(feel_window.unplayable_transition(off_play, start, start + 100))
        self.assertFalse(feel_window.unplayable_transition([], start, start + 100))
        self.assertFalse(feel_window.unplayable_transition(
            off_play + [{"kind": "step", "time": start + 20, "index": 2},
                        {"kind": "step_timing", "index": 2, "in_play": True}],
            start, start + 100))

    def test_selection_handoff_uses_successor_precommand_velocity(self):
        sample = handoff_case()
        self.assertEqual(sample["status"], "admitted")
        self.assertEqual(sample["selection_owned_player"], 7)
        self.assertEqual(sample["owned_player"], 2)
        self.assertTrue(sample["selection_handoff"])
        self.assertEqual(sample["pre_selection_vx"], 0.9)
        self.assertEqual(sample["first_accepted_aligned_action_ms"], 8)
        self.assertEqual(sample["velocity_response_ms"], 10)

    def test_handoff_needs_real_command_and_accepted_action(self):
        self.assertEqual(handoff_case(include_command=False)["status"],
                         "handoff_without_human_command")
        sample = handoff_case(include_selection=False)
        self.assertEqual(sample["status"], "no_velocity_response")
        self.assertEqual(sample["raw_velocity_change_ms"], 10)
        self.assertIsNone(sample["velocity_response_ms"])

    def test_new_touch_with_same_player_contact_is_causal(self):
        sample = analyze_case()
        self.assertEqual(sample["velocity_response_ms"], 30)
        self.assertIsNone(sample["first_accepted_aligned_movement_ms"])
        self.assertEqual(sample["first_accepted_aligned_touch_ms"], 6)
        self.assertEqual(sample["causal_action_type"], 2)

    def test_render_stall_is_recorded_as_failed_press(self):
        rows, actions = fixture_rows()
        rows = [row for row in rows
                if not (row["kind"] in ("step", "step_timing") and row["index"] > 0)]
        start = actions[0]["start_ns"]
        rows.append({"kind": "render_timing", "start": start - 20_000_000,
                     "end": start + 120_000_000})
        with TemporaryDirectory() as directory, patch.object(feel_window, "events", return_value=rows):
            report = feel_window.analyze(Path(directory), actions, require_causal=True)
        sample = report["samples"][0]
        self.assertEqual(sample["status"], "no_simulation_step_during_press")
        self.assertEqual(sample["render_blocking_during_press_ms"], 100)
        self.assertEqual(report["admitted_count"], 0)
        self.assertIsNone(report["observed_admission_p95_ms"])

    def test_unconfirmed_or_preexisting_touch_cannot_claim_response(self):
        for case in ({"touch_player": "another-player"},
                     {"touch_time_ms": 201},
                     {"include_selection": False}):
            with self.subTest(case=case):
                sample = analyze_case(**case)
                self.assertEqual(sample["raw_velocity_change_ms"], 30)
                self.assertIsNone(sample["velocity_response_ms"])
                self.assertIsNone(sample["first_accepted_aligned_touch_ms"])


if __name__ == "__main__":
    unittest.main()
