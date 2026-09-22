# 2026-09-09: thin native/configuration binding for independently tested replay I/O.
from gfootball.env import config as cfg
from gfootball.env import football_action_set
from gfootball.recording_buffers import ActionAdapter, RecordingLimits
from gfootball.replay_io import ReplayLimits
from gfootball.replay_sources import ReplaySourcePool


ACTION_ADAPTER = ActionAdapter(
    football_action_set.CoreAction,
    lambda value: football_action_set.CoreAction(
        type(football_action_set.action_idle._backend_action)(value.backend),
        value.name, value.sticky, value.directional))


def recorded_layout(values):
  players = values.get('players')
  if type(players) is not list or len(players) > 22 or any(type(value) is not str for value in players):
    raise ValueError('Recorded configuration requires at most 22 player definitions')
  # 2026-09-09: validate individual counts before helpers multiply a player list.
  # return (sum(cfg.count_left_players(player) for player in players),
  #         sum(cfg.count_right_players(player) for player in players))
  counts = [(cfg.count_left_players(player), cfg.count_right_players(player)) for player in players]
  totals = tuple(sum(value[team] for value in counts) for team in (0, 1))
  if any(not 0 <= count <= 11 for pair in counts for count in pair) or any(total > 11 for total in totals):
    raise ValueError('Recorded player counts must fit within eleven per team')
  return totals


def make_pool(config):
  replay = config['replay_limits'] if 'replay_limits' in config else {}
  observation = config['recording_limits'] if 'recording_limits' in config else {}
  if type(replay) is not dict or type(observation) is not dict:
    raise ValueError('Replay and observation limits must be dictionaries')
  return ReplaySourcePool(ACTION_ADAPTER, recorded_layout,
                          limits=ReplayLimits(**replay), observation_limits=RecordingLimits(**observation))
