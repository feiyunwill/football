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


from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import logging
import os
import sys



game_path = os.path.dirname(os.path.abspath(__file__))
# 2026-09-10: package-relative native loading must not alter sys.path.
# if game_path not in sys.path:
#   sys.path.append(game_path)

gfootball_dir = os.path.dirname(os.path.abspath(__file__))
font_file = os.path.join(gfootball_dir, 'fonts/AlegreyaSansSC-ExtraBold.ttf')
if 'MESA_GL_VERSION_OVERRIDE' not in os.environ:
  os.environ['MESA_GL_VERSION_OVERRIDE'] = '3.2'
if 'MESA_GLSL_VERSION_OVERRIDE' not in os.environ:
  os.environ['MESA_GLSL_VERSION_OVERRIDE'] = '150'
if 'GFOOTBALL_FONT' not in os.environ:
  os.environ['GFOOTBALL_FONT'] = font_file
data_dir = os.path.join(gfootball_dir, 'data')
if 'GFOOTBALL_DATA_DIR' not in os.environ:
  os.environ['GFOOTBALL_DATA_DIR'] = data_dir

# 2026-09-10: one native module identity prevents duplicate pybind type registration.
# try:
#   from _gameplayfootball import *
# except:
#   if not (os.path.isfile(os.path.join(game_path, 'libgame.so')) and
#           os.path.isfile(os.path.join(game_path, '_gameplayfootball.so'))):
#     logging.warning('Looks like game engine is not compiled, please run:')
#     engine_path = os.path.abspath(os.path.dirname(__file__))
#     logging.warning(
#         '  pushd {} && cmake . && make -j `nproc` && popd'.format(game_path))
#     logging.warning('  pushd {} && ln -s libgame.so '
#                     '_gameplayfootball.so && popd'.format(engine_path))
#   raise

try:
  _existing_native = sys.modules.get('_gameplayfootball')
  if _existing_native is not None:
    _existing_file = getattr(_existing_native, '__file__', None)
    if not _existing_file or not os.path.samefile(os.path.dirname(_existing_file), game_path):
      raise ImportError('A football native module from a different installation is already loaded')
    # Support callers which loaded this same library by its historical name first.
    sys.modules[__name__ + '._gameplayfootball'] = _existing_native
  from . import _gameplayfootball
  from ._gameplayfootball import *
  # Preserve old pickles/imports while using one extension instance.
  sys.modules.setdefault('_gameplayfootball', _gameplayfootball)
except ImportError:
  logging.error('Could not load the football native extension. Build this checkout '
                'with python -m pip install . and verify its system library dependencies.')
  raise
