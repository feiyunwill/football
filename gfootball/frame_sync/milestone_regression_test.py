"""Behavioral regressions from the milestone review."""
import pytest
from gfootball.frame_sync.save_system import SaveManager, GameProgress
from gfootball.frame_sync.matchmaking import Matchmaker


def test_nested_save_and_load_are_independent():
    saves = SaveManager()
    saves.create_slot('career', 'Career')
    original = {'team': {'players': [1, 2]}}
    saves.save('career', original)
    original['team']['players'].append(3)
    loaded = saves.load('career')
    loaded['team']['players'].clear()
    assert saves.load('career') == {'team': {'players': [1, 2]}}
    with pytest.raises(ValueError):
        saves.create_slot('career', 'Overwrite')


def test_invalid_import_leaves_existing_save_untouched():
    saves = SaveManager()
    saves.create_slot('career', 'Career')
    saves.save('career', {'money': 10})
    assert saves.import_slot('{"slot_id":"career","name":"x","save_type":"invalid"}') is None
    assert saves.import_slot('[]') is None
    assert saves.load('career') == {'money': 10}
    exported = saves.export_slot('career')
    other = SaveManager()
    assert other.import_slot(exported).size_bytes > 0


def test_progress_export_is_an_independent_snapshot():
    progress = GameProgress()
    snapshot = progress.to_dict()
    snapshot['career']['money'] = 999
    assert progress.get('career.money') == 0


def test_matchmaking_respects_window_then_expands_for_waiting_player():
    maker = Matchmaker(max_rating_diff=100, expand_rate=10)
    maker.enqueue('beginner', 1000)
    maker.enqueue('expert', 2000)
    assert maker.find_best_match() is None
    maker._queue[0].queued_at -= 100
    assert maker.find_best_match() == ('beginner', 'expert')
