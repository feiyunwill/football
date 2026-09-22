"""Version 7 match cadence: 50 input/authority frames per simulated second.

Each frame configures two fixed 10 ms physics steps. Real-time scheduling and
offline replay share that definition; missed wall-clock opportunities never
skip simulation frames. Legacy scenario durations are expressed at 10 Hz.
"""
from dataclasses import dataclass, asdict

LEGACY_HZ = 10
LEGACY_PHYSICS_STEPS = 10


@dataclass(frozen=True)
class MatchCadence:
  input_hz: int = 50
  network_hz: int = 50
  physics_steps: int = 2
  physics_step_us: int = 10000

  def __post_init__(self):
    for name, expected in (('input_hz', 50), ('network_hz', 50),
                           ('physics_steps', 2), ('physics_step_us', 10000)):
      value = getattr(self, name)
      if type(value) is not int or value != expected:
        raise ValueError('Unsupported match cadence: ' + name)

  @property
  def frame_ms(self):
    return self.physics_steps * self.physics_step_us // 1000

  def scenario_frames(self, legacy_frames):
    """Convert once before reset, preserving scenario time and signed ABI bounds."""
    if type(legacy_frames) is not int or not 1 <= legacy_frames <= 0x7fffffff:
      raise ValueError('Invalid legacy scenario duration')
    microseconds = legacy_frames * LEGACY_PHYSICS_STEPS * self.physics_step_us
    frames, remainder = divmod(microseconds, self.physics_steps * self.physics_step_us)
    if remainder or frames > 0x7fffffff:
      raise ValueError('Scenario duration cannot fit the match cadence')
    return frames

  def to_dict(self):
    return asdict(self)

  def require_rate(self, rate_hz):
    if type(rate_hz) not in (int, float) or rate_hz != self.network_hz:
      raise ValueError('Match cadence requires a 50 Hz real-time loop')


MATCH_CADENCE = MatchCadence()


def parse_cadence(data):
  if type(data) is not dict or set(data) != {'input_hz', 'network_hz', 'physics_steps', 'physics_step_us'}:
    raise ValueError('Invalid match cadence fields')
  return MatchCadence(**data)


# 2026-09-13: preserve the prior 10 Hz contract; v7 explicitly rejects v6 cadence.
# """The single supported v5 match cadence, independent of wall-clock speed.
# 
# One authoritative frame consumes one input sample and ten 10 ms physics steps.
# Manual stepping/offline playback may run faster; they keep this simulated time.
# Changing this contract requires a new negotiated match protocol version.
# """
# from dataclasses import dataclass, asdict
# 
# 
# @dataclass(frozen=True)
# class MatchCadence:
#   input_hz: int = 10
#   network_hz: int = 10
#   physics_steps: int = 10
#   physics_step_us: int = 10000
# 
#   def __post_init__(self):
#     for name, expected in (('input_hz', 10), ('network_hz', 10),
#                            ('physics_steps', 10), ('physics_step_us', 10000)):
#       value = getattr(self, name)
#       if type(value) is not int or value != expected:
#         raise ValueError('Unsupported match cadence: ' + name)
# 
#   def to_dict(self):
#     return asdict(self)
# 
#   def require_rate(self, rate_hz):
#     if type(rate_hz) not in (int, float) or rate_hz != self.network_hz:
#       raise ValueError('Match cadence requires a 10 Hz real-time loop')
# 
# 
# MATCH_CADENCE = MatchCadence()
# 
# 
# def parse_cadence(data):
#   if type(data) is not dict or set(data) != {'input_hz', 'network_hz', 'physics_steps', 'physics_step_us'}:
#     raise ValueError('Invalid match cadence fields')
#   return MatchCadence(**data)
