"""Validated menu preferences published through the existing atomic save store."""
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from gfootball.frame_sync.save_data import SaveFormatError, SaveLimits, SaveSlot, SaveType, integer, text
from gfootball.frame_sync.save_runtime import SaveManager
from gfootball.frame_sync.server_runtime import ServerSettings

DEFAULT_SETTINGS_PATH = Path.home() / '.football' / 'settings.save'
OPTION_LIMITS = SaveLimits(slots=1, slot_bytes=32768, total_bytes=32768,
                          graph_bytes=65536, nodes=128, depth=4, container_items=32, string_bytes=4096)


@dataclass(frozen=True)
class MenuOptions:
  local_scenario: str = 'academy_empty_goal'
  host_scenario: str = '11_vs_11_stochastic'
  local_left: int = 1
  local_right: int = 0
  host_left: int = 1
  host_right: int = 1
  seed: int = 42
  host: str = '127.0.0.1'
  port: int = 12345
  # 2026-09-10: document the validated optional value type.
  # frames: object = None
  frames: Optional[int] = None
  # 2026-09-10: document the validated optional value type.
  # record_path: object = None
  record_path: Optional[str] = None
  # 2026-09-10: document the validated optional value type.
  # save_path: object = None
  save_path: Optional[str] = None

  def __post_init__(self):
    for scenario, left, right in ((self.local_scenario, self.local_left, self.local_right),
                                  (self.host_scenario, self.host_left, self.host_right)):
      text(scenario, 'scenario', 256)
      ServerSettings(scenario_name=scenario, left_agents=left, right_agents=right,
                     game_engine_random_seed=self.seed)
    text(self.host, 'server host', 253)
    integer(self.port, 'server port', 1, 65535)
    if self.frames is not None:
      integer(self.frames, 'frame limit', 1, 1000000)
    for value in (self.record_path, self.save_path):
      if value is not None:
        text(value, 'output path', 4096)

  def payload(self):
    return dict(format='football.menu_options', version=1, options=asdict(self))

  @classmethod
  def from_payload(cls, value):
    if (type(value) is not dict or set(value) != {'format', 'version', 'options'}
        or value['format'] != 'football.menu_options' or type(value['version']) is not int or value['version'] != 1
        or type(value['options']) is not dict or set(value['options']) != set(cls.__dataclass_fields__)):
      raise SaveFormatError('Invalid menu preferences')
    return cls(**value['options'])


def load_options(path=None):
  path = Path(path) if path is not None else DEFAULT_SETTINGS_PATH
  if not path.exists():
    return MenuOptions()
  with SaveManager(path=str(path), limits=OPTION_LIMITS) as manager:
    slots = manager.list_slots()
    if len(slots) != 1 or slots[0].slot_id != 'options' or slots[0].save_type is not SaveType.SETTINGS:
      raise SaveFormatError('Not a menu settings collection')
    return MenuOptions.from_payload(slots[0].data)


def save_options(options, path=None):
  if type(options) is not MenuOptions:
    raise SaveFormatError('Expected validated menu options')
  path = Path(path) if path is not None else DEFAULT_SETTINGS_PATH
  slot = SaveSlot('options', 'Football preferences', SaveType.SETTINGS, options.payload(), limits=OPTION_LIMITS)
  with SaveManager(path=str(path), limits=OPTION_LIMITS) as manager:
    old = manager.list_slots()
    if old:
      if len(old) != 1 or old[0].slot_id != 'options' or old[0].save_type is not SaveType.SETTINGS:
        raise SaveFormatError('Destination is a different save collection')
      MenuOptions.from_payload(old[0].data)
    if manager.import_slot(slot.export_bytes().decode('utf-8')) is None:
      raise SaveFormatError('Could not publish menu settings')
  return str(path)
