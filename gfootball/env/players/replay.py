# coding=utf-8
# Copyright 2019 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Player with actions coming from specific game replay."""

from gfootball.env import player_base
# 2026-09-09: avoid the ScriptHelpers/FootballEnv replay import cycle.
# from gfootball.env import script_helpers
from gfootball.env import replay_support


# 2026-09-09: replace per-player full replay lists/process exit with a
# shared streaming cursor, proper team offsets, reset and explicit close.
# class Player(player_base.PlayerBase):
#   """Player with actions coming from specific game replay."""
#
#   def __init__(self, player_config, env_config):
#     player_base.PlayerBase.__init__(self, player_config)
#     self._can_play_right = True
#     self._replay = script_helpers.ScriptHelpers().load_dump(player_config['path'])
#     self._step = 0
#     self._player = player_config['index']
#
#   def take_action(self, observations):
#     if self._step == len(self._replay):
#       print("Replay finished.")
#       exit(0)
#     actions = self._replay[self._step]['debug']['action'][
#         self._player:self.num_controlled_players() + self._player]
#     self._step += 1
#     return actions
class Player(player_base.PlayerBase):
  """Consume a bounded shared action row; EOF is a library exception."""
  def __init__(self, player_config, env_config):
    player_base.PlayerBase.__init__(self, player_config)
    self._can_play_right = True
    self._cursor = None
    self._pool = player_config.get('_replay_sources')
    self._owns_pool = self._pool is None
    if self._owns_pool:
      self._pool = replay_support.make_pool(env_config)
    try:
      path = player_config.get('path')
      if path is None and 'replay_path' in env_config:
        path = env_config['replay_path']
      if path is None:
        raise ValueError('Replay player requires a path or replay_path configuration')
      source = self._pool.source(path)
      if '_left_action_offset' in player_config:
        left = player_config['_left_action_offset']
        right = player_config['_right_action_offset']
        if (left + self.num_controlled_left_players() > source.layout[0]
            or right + self.num_controlled_right_players() > source.layout[1]):
          raise ValueError('Replay player exceeds the recorded team action layout')
        indices = list(range(left, left + self.num_controlled_left_players()))
        indices.extend(range(source.layout[0] + right,
                             source.layout[0] + right + self.num_controlled_right_players()))
      else:
        # Preserve explicit standalone construction's original absolute index API.
        start = player_config['index']
        indices = list(range(start, start + self.num_controlled_players()))
      self._cursor = source.subscribe(indices)
    # 2026-09-09: preserve the construction failure if cleanup also fails.
    # except BaseException:
    #   self.close()
    #   raise
    except BaseException as error:
      try:
        self.close()
      except BaseException:
        if hasattr(error, 'add_note'):
          error.add_note('Replay player construction cleanup also failed.')
      raise

  def take_action(self, observations):
    return self._cursor.take()

  def reset(self):
    self._cursor.reset()

  def close(self):
    try:
      if self._cursor is not None:
        self._cursor.close()
    finally:
      if self._owns_pool:
        self._pool.close()

  def __del__(self):
    if hasattr(self, '_owns_pool'):
      try:
        self.close()
      except BaseException:
        pass
