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

"""Google Research Football."""


# 2026-09-09: register Gym entry points without importing the native engine.
# from gfootball.env import scenario_builder
#
# import gym
# from gym.envs.registration import register
#
#
# for env_name in scenario_builder.all_scenarios():
#   register(
#       id='GFootball-{env_name}-SMM-v0'.format(env_name=env_name),
#       entry_point='gfootball.env:create_environment',
#       kwargs={
#           'env_name': env_name,
#           'representation': 'extracted'
#       },
#   )
#
#   register(
#       id='GFootball-{env_name}-Pixels-v0'.format(env_name=env_name),
#       entry_point='gfootball.env:create_environment',
#       kwargs={
#           'env_name': env_name,
#           'representation': 'pixels'
#       },
#   )
#
#   register(
#       id='GFootball-{env_name}-simple115-v0'.format(env_name=env_name),
#       entry_point='gfootball.env:create_environment',
#       kwargs={
#           'env_name': env_name,
#           'representation': 'simple115'
#       },
#   )
#
#   register(
#       id='GFootball-{env_name}-simple115v2-v0'.format(env_name=env_name),
#       entry_point='gfootball.env:create_environment',
#       kwargs={
#           'env_name': env_name,
#           'representation': 'simple115v2'
#       },
#   )

# 2026-09-10: storage/network imports must remain independent of an installed
# Gym/native runtime. Gym's package entry point registers environments on demand.
# import importlib.util
# import os
# import pkgutil
# 
# # Protocol, lobby and persistence modules can run without the optional Gym runtime.
# if importlib.util.find_spec('gym') is not None:
#   from gym.envs.registration import register
# 
#   scenario_path = os.path.join(os.path.dirname(__file__), 'scenarios')
#   for scenario in pkgutil.iter_modules([scenario_path]):
#     for suffix, representation in (
#         ('SMM', 'extracted'), ('Pixels', 'pixels'),
#         ('simple115', 'simple115'), ('simple115v2', 'simple115v2')):
#       register(
#           id='GFootball-{}-{}-v0'.format(scenario.name, suffix),
#           entry_point='gfootball.env:create_environment',
#           kwargs={'env_name': scenario.name, 'representation': representation})
import os
import pkgutil
import sys
import threading

# 2026-09-10: explicit Gymnasium module discovery replaces obsolete Gym plugins.
# _gym_registration_lock = threading.RLock()
# _gym_registered = False
# 
# 
# def register_gym_envs():
#   """Gym plugin callback; also supports an explicit source-checkout import."""
#   from gym.envs.registration import register, namespace
#   global _gym_registered
#   with _gym_registration_lock:
#     if _gym_registered:
#       return
#     scenario_path = os.path.join(os.path.dirname(__file__), 'scenarios')
#     # Keep the existing public IDs under old and new Gym plugin namespaces.
#     with namespace(None):
#       for scenario in pkgutil.iter_modules([scenario_path]):
#         for suffix, representation in (
#             ('SMM', 'extracted'), ('Pixels', 'pixels'),
#             ('simple115', 'simple115'), ('simple115v2', 'simple115v2')):
#           register(
#               id='GFootball-{}-{}-v0'.format(scenario.name, suffix),
#               entry_point='gfootball.env:create_environment',
#               kwargs={'env_name': scenario.name, 'representation': representation})
#     _gym_registered = True
# 
# 
# # Source checkouts retain the usual import-gym-then-import-gfootball workflow.
# if hasattr(sys.modules.get('gym.envs.registration'), 'register'):
#   register_gym_envs()
# 
# 

_gymnasium_registration_lock = threading.RLock()


def register_gymnasium_envs():
  """Register numeric Gymnasium IDs without importing football environments."""
  from gymnasium.envs.registration import register, registry, namespace
  with _gymnasium_registration_lock, namespace(None):
    scenario_path = os.path.join(os.path.dirname(__file__), 'scenarios')
    for scenario in pkgutil.iter_modules([scenario_path]):
      if scenario.ispkg:
        continue
      for suffix, representation in (
          ('SMM', 'extracted'), ('Pixels', 'pixels'),
          ('simple115', 'simple115'), ('simple115v2', 'simple115v2')):
        key = 'GFootball-{}-{}-v0'.format(scenario.name, suffix)
        if key in registry:
          if registry[key].entry_point != 'gfootball.gymnasium:FootballEnv':
            raise RuntimeError('A different environment already owns ' + key)
          continue
        register(id=key, entry_point='gfootball.gymnasium:FootballEnv',
                 kwargs={'env_name': scenario.name, 'representation': representation})
