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


"""Set of functions used by command line scripts."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from gfootball.env import config
from gfootball.env import football_action_set
from gfootball.env import football_env
from gfootball.env import observation_processor

import copy
from dataclasses import asdict
import itertools
from gfootball.env import constants, replay_support
from gfootball.recording_buffers import ObservationState, RecordingLimits
from gfootball.replay_io import (
    AtomicReplayFile, ReplayFormatError, ReplayLimits, ReplayReader, drive_replay,
    expanded_actions, export_text, first_config, load_replay, replay_timing, temporary_replay_directory,
)
import six.moves.cPickle
import os
import tempfile


# 2026-09-09: stream replay records/actions/text, bound conversion output,
# preserve existing targets until success and close environment/temp ownership.
# class ScriptHelpers(object):
#   """Set of methods used by command line scripts."""
#
#   def __init__(self):
#     pass
#
#   def __modify_trace(self, replay, fps):
#     """Adopt replay to the new framerate and add additional steps at the end."""
#     trace = []
#     min_fps = replay[0]['debug']['config']['physics_steps_per_frame']
#     assert fps % min_fps == 0, (
#         'Trace has to be rendered in framerate being multiple of {}'.format(
#             min_fps))
#     assert fps <= 100, ('Framerate of up to 100 is supported')
#     empty_steps = int(fps / min_fps) - 1
#     for f in replay:
#       trace.append(f)
#       idle_step = copy.deepcopy(f)
#       idle_step['debug']['action'] = [football_action_set.action_idle
#                                      ] * len(f['debug']['action'])
#       for _ in range(empty_steps):
#         trace.append(idle_step)
#     # Add some empty steps at the end, so that we can record videos.
#     for _ in range(10):
#       trace.append(idle_step)
#     return trace
#
#   def __build_players(self, dump_file, spec):
#     players = []
#     for player in spec:
#       players.extend(['replay:path={},left_players=1'.format(
#           dump_file)] * config.count_left_players(player))
#       players.extend(['replay:path={},right_players=1'.format(
#           dump_file)] * config.count_right_players(player))
#     return players
#
#   def load_dump(self, dump_file):
#     dump = []
#     with open(dump_file, 'rb') as in_fd:
#       while True:
#         try:
#           step = six.moves.cPickle.load(in_fd)
#         except EOFError:
#           return dump
#         dump.append(step)
#
#   def dump_to_txt(self, dump_file, output, include_debug):
#     with open(output, 'w') as out_fd:
#       dump = self.load_dump(dump_file)
#     if not include_debug:
#       for s in dump:
#         if 'debug' in s:
#           del s['debug']
#     with open(output, 'w') as f:
#       f.write(str(dump))
#
#   def dump_to_video(self, dump_file):
#     dump = self.load_dump(dump_file)
#     cfg = config.Config(dump[0]['debug']['config'])
#     cfg['dump_full_episodes'] = True
#     cfg['write_video'] = True
#     cfg['display_game_stats'] = True
#     processor = observation_processor.ObservationProcessor(cfg)
#     # 2026-09-09: output commits require explicit success, including short dumps.
#     # processor.write_dump('episode_done')
#     # for frame in dump:
#     #   processor.update(frame)
#     try:
#       processor.write_dump('episode_done')
#       for frame in dump:
#         processor.update(frame)
#     except BaseException:
#       processor.close(finalize=False)
#       raise
#     return processor.close()
#
#   def replay(self, dump, fps=10, config_update={}, directory=None, render=True):
#     replay = self.load_dump(dump)
#     trace = self.__modify_trace(replay, fps)
#     fd, temp_path = tempfile.mkstemp(suffix='.dump')
#     with open(temp_path, 'wb') as f:
#       for step in trace:
#         six.moves.cPickle.dump(step, f)
#     assert replay[0]['debug']['frame_cnt'] == 0, (
#         'Trace does not start from the beginning of the episode, can not replay')
#     cfg = config.Config(replay[0]['debug']['config'])
#     cfg['players'] = self.__build_players(temp_path, cfg['players'])
#     config_update['physics_steps_per_frame'] = int(100 / fps)
#     config_update['real_time'] = False
#     if directory:
#       config_update['tracesdir'] = directory
#     config_update['write_video'] = True
#     cfg.update(config_update)
#     env = football_env.FootballEnv(cfg)
#     if render:
#       env.render()
#     env.reset()
#     done = False
#     try:
#       while not done:
#         _, _, done, _ = env.step([])
#     except KeyboardInterrupt:
#       env.write_dump('shutdown')
#       exit(1)
#     os.close(fd)
class ScriptHelpers(object):
  """Bounded compatibility APIs and streaming replay conversion."""
  def __init__(self, *, replay_limits=None, observation_limits=None, directory_limits=None):
    # 2026-09-09: distinguish omitted settings from invalid false-like policies.
    for value, kind in ((replay_limits, ReplayLimits), (observation_limits, RecordingLimits)):
      if value is not None and type(value) is not dict and not isinstance(value, kind):
        raise ValueError('Expected a limits object, dictionary or None')
    if directory_limits is not None and type(directory_limits) is not dict:
      raise ValueError('directory_limits must be a dictionary or None')
    self._limits = replay_limits if isinstance(replay_limits, ReplayLimits) else ReplayLimits(**(replay_limits or {}))
    self._observation_limits = (observation_limits if isinstance(observation_limits, RecordingLimits)
                                else RecordingLimits(**(observation_limits or {})))
    self._directory_limits = dict(directory_limits) if directory_limits is not None else None

  def _reader(self, path):
    return ReplayReader(path, limits=self._limits, observation_limits=self._observation_limits,
                         action_adapter=replay_support.ACTION_ADAPTER)

  def iter_dump(self, path):
    with self._reader(path) as reader:
      for state in reader:
        yield state.to_record()

  def load_dump(self, path):
    return load_replay(path, limits=self._limits, observation_limits=self._observation_limits,
                        action_adapter=replay_support.ACTION_ADAPTER)

  def __modify_trace(self, replay, fps):
    states = (value if isinstance(value, ObservationState) else ObservationState(
        value, limits=self._observation_limits, action_adapter=replay_support.ACTION_ADAPTER) for value in replay)
    return expanded_actions(states, fps, football_action_set.action_idle,
                             action_adapter=replay_support.ACTION_ADAPTER, limits=self._limits,
                             physics_hz=constants.PHYSICS_STEPS_PER_SECOND)

  def __build_players(self, spec):
    # The private replay path is a config value, not embedded in delimiter-based
    # player definitions; Windows drive letters, commas and '=' remain valid paths.
    # 2026-09-09: reject oversized counts before materializing repeated strings.
    replay_support.recorded_layout({'players': spec})
    players = []
    for player in spec:
      players.extend(['replay:left_players=1'] * config.count_left_players(player))
      players.extend(['replay:right_players=1'] * config.count_right_players(player))
    return players

  def dump_to_txt(self, dump_file, output, include_debug):
    return export_text(dump_file, output, include_debug, limits=self._limits,
                        observation_limits=self._observation_limits,
                        action_adapter=replay_support.ACTION_ADAPTER,
                        directory_limits=self._directory_limits)

  def dump_to_video(self, dump_file):
    with self._reader(dump_file) as reader:
      try:
        first = next(reader)
      except StopIteration as error:
        raise ReplayFormatError('Replay input is empty') from error
      cfg = config.Config(first_config(first))
      cfg['dump_full_episodes'] = True
      cfg['write_video'] = True
      cfg['display_game_stats'] = True
      if self._directory_limits is not None:
        cfg['recording_output_limits'] = self._directory_limits
      processor = observation_processor.ObservationProcessor(cfg)
      try:
        processor.write_dump('episode_done')
        for state in itertools.chain((first,), reader):
          processor.update(state.to_record())
      except BaseException as error:
        try:
          processor.close(finalize=False)
        except BaseException:
          if hasattr(error, 'add_note'):
            error.add_note('Replay video cleanup also failed.')
        raise
      return processor.close()

  def replay(self, dump, fps=10, config_update=None, directory=None, render=True):
    if config_update is not None and type(config_update) is not dict:
      raise ValueError('config_update must be a dictionary')
    with temporary_replay_directory() as workspace:
      input_path = workspace / 'input.dump'
      with self._reader(dump) as reader:
        try:
          first = next(reader)
        except StopIteration as error:
          raise ReplayFormatError('Replay input is empty') from error
        initial = first_config(first)
        steps, _ = replay_timing(initial.get('physics_steps_per_frame'), fps,
                                  constants.PHYSICS_STEPS_PER_SECOND)
        converted = expanded_actions(itertools.chain((first,), reader), fps,
                                      football_action_set.action_idle,
                                      action_adapter=replay_support.ACTION_ADAPTER,
                                      limits=self._limits, physics_hz=constants.PHYSICS_STEPS_PER_SECOND)
        count = 0
        with AtomicReplayFile(input_path, self._limits.output_bytes) as output:
          for record in converted:
            output.dump(record)
            count += 1
      cfg = config.Config(initial)
      # 2026-09-09: bounded structural copy of caller configuration; arbitrary
      # deepcopy hooks and unbounded duplicated containers are not needed here.
      # updates = copy.deepcopy(config_update) if config_update is not None else {}
      updates = ObservationState({'observation': {}, 'debug': {'config': config_update or {}}},
                                  limits=self._observation_limits,
                                  action_adapter=replay_support.ACTION_ADAPTER).to_record()['debug']['config']
      # Conversion fixes the input cadence; callers cannot silently change it.
      updates['physics_steps_per_frame'] = steps
      updates['real_time'] = False
      updates['write_video'] = True
      # 2026-09-09: keep explicit caller player overrides, as the previous API did.
      # updates['players'] = self.__build_players(initial['players'])
      updates.setdefault('players', self.__build_players(initial['players']))
      updates['replay_path'] = str(input_path)
      playback_limits = asdict(self._limits)
      playback_limits.update(file_bytes=self._limits.output_bytes, records=self._limits.output_records)
      updates['replay_limits'] = playback_limits
      if directory is not None:
        updates['tracesdir'] = directory
      if self._directory_limits is not None:
        updates['recording_output_limits'] = self._directory_limits
      cfg.update(updates)
      return drive_replay(football_env.FootballEnv, cfg, count, render=render)
