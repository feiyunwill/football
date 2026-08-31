"""
Tutorial and training system for new players.

This module provides:
- Step-by-step tutorials
- Training modes
- Skill challenges
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable


class TutorialStep(Enum):
    """Tutorial step types."""
    MOVE = "move"
    PASS = "pass"
    SHOOT = "shoot"
    DEFEND = "defend"
    SPRINT = "sprint"
    DRIBBLE = "dribble"
    TACTIC = "tactic"
    FINISHED = "finished"


class ChallengeType(Enum):
    """Challenge types."""
    SHOOTING = "shooting"
    PASSING = "passing"
    DEFENDING = "defending"
    DRIBBLING = "dribbling"
    SET_PIECE = "set_piece"
    TIME_ATTACK = "time_attack"


@dataclass
class TutorialInstruction:
    """A single tutorial instruction."""
    step: TutorialStep
    title: str
    description: str
    control_hint: str
    target_action: str
    success_threshold: float = 1.0

    def to_dict(self) -> dict:
        return {
            "step": self.step.value,
            "title": self.title,
            "description": self.description,
            "control_hint": self.control_hint,
        }


@dataclass
class TutorialProgress:
    """Player's tutorial progress."""
    player_id: str
    current_step: TutorialStep = TutorialStep.MOVE
    completed_steps: list[TutorialStep] = field(default_factory=list)
    score: int = 0
    started_at: float = field(default_factory=time.time)
    completed: bool = False

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "current_step": self.current_step.value,
            "completed_steps": [s.value for s in self.completed_steps],
            "score": self.score,
            "completed": self.completed,
        }


class TutorialSystem:
    """Step-by-step tutorial system."""

    def __init__(self):
        self._instructions: dict[TutorialStep, TutorialInstruction] = {}
        self._progress: dict[str, TutorialProgress] = {}
        self._load_default_instructions()

    def _load_default_instructions(self) -> None:
        """Load default tutorial instructions."""
        self._instructions[TutorialStep.MOVE] = TutorialInstruction(
            step=TutorialStep.MOVE,
            title="Movement",
            description="Use the arrow keys or joystick to move your player around the pitch.",
            control_hint="Arrow Keys / Left Stick",
            target_action="move",
        )
        self._instructions[TutorialStep.PASS] = TutorialInstruction(
            step=TutorialStep.PASS,
            title="Passing",
            description="Press the pass button to pass the ball to a teammate.",
            control_hint="X / A Button",
            target_action="pass",
        )
        self._instructions[TutorialStep.SHOOT] = TutorialInstruction(
            step=TutorialStep.SHOOT,
            title="Shooting",
            description="When near the goal, press the shoot button to take a shot!",
            control_hint="Circle / B Button",
            target_action="shoot",
        )
        self._instructions[TutorialStep.DEFEND] = TutorialInstruction(
            step=TutorialStep.DEFEND,
            title="Defending",
            description="Use the pressure button to challenge for the ball.",
            control_hint="Square / X Button",
            target_action="defend",
        )
        self._instructions[TutorialStep.SPRINT] = TutorialInstruction(
            step=TutorialStep.SPRINT,
            title="Sprinting",
            description="Hold the sprint button to run faster, but be careful of stamina!",
            control_hint="R1 / RB Button",
            target_action="sprint",
        )
        self._instructions[TutorialStep.DRIBBLE] = TutorialInstruction(
            step=TutorialStep.DRIBBLE,
            title="Dribbling",
            description="Use close control to dribble past opponents.",
            control_hint="L1 / LB + Direction",
            target_action="dribble",
        )
        self._instructions[TutorialStep.TACTIC] = TutorialInstruction(
            step=TutorialStep.TACTIC,
            title="Tactics",
            description="Switch between attacking and defensive formations.",
            control_hint="D-Pad Up/Down",
            target_action="tactic",
        )

    def start_tutorial(self, player_id: str) -> TutorialInstruction:
        """Start or restart the tutorial for a player."""
        progress = TutorialProgress(player_id=player_id)
        self._progress[player_id] = progress
        return self._instructions[TutorialStep.MOVE]

    def get_current_step(self, player_id: str) -> Optional[TutorialInstruction]:
        """Get the current tutorial step for a player."""
        progress = self._progress.get(player_id)
        if not progress or progress.completed:
            return None
        return self._instructions.get(progress.current_step)

    def complete_step(self, player_id: str, score: int = 100) -> Optional[TutorialInstruction]:
        """Complete the current step and return the next one."""
        progress = self._progress.get(player_id)
        if not progress or progress.completed:
            return None

        progress.completed_steps.append(progress.current_step)
        progress.score += score

        step_order = [
            TutorialStep.MOVE, TutorialStep.PASS, TutorialStep.SHOOT,
            TutorialStep.DEFEND, TutorialStep.SPRINT, TutorialStep.DRIBBLE,
            TutorialStep.TACTIC, TutorialStep.FINISHED,
        ]

        current_idx = step_order.index(progress.current_step)
        if current_idx + 1 < len(step_order):
            next_step = step_order[current_idx + 1]
            progress.current_step = next_step
            if next_step == TutorialStep.FINISHED:
                progress.completed = True
                return None
            return self._instructions[next_step]

        progress.completed = True
        return None

    def get_progress(self, player_id: str) -> Optional[TutorialProgress]:
        """Get a player's tutorial progress."""
        return self._progress.get(player_id)

    def is_completed(self, player_id: str) -> bool:
        """Check if a player has completed the tutorial."""
        progress = self._progress.get(player_id)
        return progress.completed if progress else False

    def get_completion_rate(self, player_id: str) -> float:
        """Get tutorial completion rate (0.0 to 1.0)."""
        progress = self._progress.get(player_id)
        if not progress:
            return 0.0
        total_steps = len(TutorialStep) - 1  # Exclude FINISHED
        return len(progress.completed_steps) / total_steps


@dataclass
class TrainingConfig:
    """Configuration for a training session."""
    mode: ChallengeType
    duration_seconds: int = 60
    target_score: int = 10
    difficulty: str = "normal"

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "duration_seconds": self.duration_seconds,
            "target_score": self.target_score,
            "difficulty": self.difficulty,
        }


@dataclass
class TrainingResult:
    """Result of a training session."""
    player_id: str
    mode: ChallengeType
    score: int
    targets_hit: int
    targets_total: int
    time_seconds: float
    completed: bool

    @property
    def accuracy(self) -> float:
        if self.targets_total == 0:
            return 0.0
        return self.targets_hit / self.targets_total

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "mode": self.mode.value,
            "score": self.score,
            "targets_hit": self.targets_hit,
            "targets_total": self.targets_total,
            "accuracy": self.accuracy,
            "time_seconds": self.time_seconds,
            "completed": self.completed,
        }


class TrainingMode:
    """Training mode for practicing specific skills."""

    def __init__(self):
        self._configs: dict[ChallengeType, TrainingConfig] = {}
        self._results: dict[str, list[TrainingResult]] = {}
        self._load_default_configs()

    def _load_default_configs(self) -> None:
        """Load default training configurations."""
        self._configs[ChallengeType.SHOOTING] = TrainingConfig(
            mode=ChallengeType.SHOOTING,
            duration_seconds=60,
            target_score=5,
        )
        self._configs[ChallengeType.PASSING] = TrainingConfig(
            mode=ChallengeType.PASSING,
            duration_seconds=60,
            target_score=10,
        )
        self._configs[ChallengeType.DEFENDING] = TrainingConfig(
            mode=ChallengeType.DEFENDING,
            duration_seconds=60,
            target_score=8,
        )
        self._configs[ChallengeType.DRIBBLING] = TrainingConfig(
            mode=ChallengeType.DRIBBLING,
            duration_seconds=45,
            target_score=3,
        )

    def get_config(self, mode: ChallengeType) -> Optional[TrainingConfig]:
        """Get training config for a mode."""
        return self._configs.get(mode)

    def record_result(self, result: TrainingResult) -> None:
        """Record a training result."""
        if result.player_id not in self._results:
            self._results[result.player_id] = []
        self._results[result.player_id].append(result)

    def get_best_score(self, player_id: str, mode: ChallengeType) -> int:
        """Get a player's best score for a mode."""
        results = self._results.get(player_id, [])
        mode_results = [r for r in results if r.mode == mode]
        if not mode_results:
            return 0
        return max(r.score for r in mode_results)

    def get_player_results(self, player_id: str) -> list[TrainingResult]:
        """Get all training results for a player."""
        return self._results.get(player_id, [])

    def get_leaderboard(self, mode: ChallengeType, limit: int = 10) -> list[tuple[str, int]]:
        """Get leaderboard for a training mode."""
        best_scores: dict[str, int] = {}
        for player_id, results in self._results.items():
            mode_results = [r for r in results if r.mode == mode]
            if mode_results:
                best_scores[player_id] = max(r.score for r in mode_results)

        sorted_scores = sorted(best_scores.items(), key=lambda x: -x[1])
        return sorted_scores[:limit]
