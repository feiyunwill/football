"""Bounded keyboard/controller state shared by display and simulation owners."""
import math
import threading

from gfootball.frame_sync import protocol as wire


# e_ButtonFunction indices from engine/src/ai/ai_keyboard.hpp.
KEY_BUTTONS = {'z': 2, 'x': 1, 'c': 0, 'v': 3, 'r': 4, 'b': 5, 'space': 6,
               'n': 7, 'tab': 8, 'lshift': 9, 'rshift': 9, 'm': 10}
PAD_BUTTONS = {0: 2, 1: 3, 2: 1, 3: 0, 7: 10, 8: 6, 9: 8, 10: 9}
# 2026-09-10: bounded pause commands and input release across owner transitions.
# KEYS = frozenset(KEY_BUTTONS) | frozenset(('w', 'a', 's', 'd', 'up', 'left', 'down', 'right', 'p', 'q', 'escape'))
KEYS = frozenset(KEY_BUTTONS) | frozenset(('w', 'a', 's', 'd', 'up', 'left', 'down', 'right', 'p', 'q', 'escape', 'k'))


def _keys(values):
  if type(values) not in (set, frozenset, tuple, list) or len(values) > len(KEYS):
    raise ValueError('Invalid bounded key state')
  if any(type(value) is not str or value not in KEYS for value in values):
    raise ValueError('Unknown input key')
  return frozenset(values)


def _buttons(keys, pad):
  result = 0
  for key in keys:
    if key in KEY_BUTTONS:
      result |= 1 << KEY_BUTTONS[key]
  for button, action in PAD_BUTTONS.items():
    if pad & (1 << button):
      result |= 1 << action
  return result


class InputBuffer:
  """One latest direction, held mask and latched press mask; no event history.

  feed belongs to the UI coordinator; sample is called once for each new logic
  input. A quick press/release remains visible for one sample. Focus loss or
  controller removal clears that source, including pending taps.
  """
  def __init__(self, deadzone=.18):
    if type(deadzone) not in (int, float) or not math.isfinite(deadzone) or not 0 <= deadzone <= .5:
      raise ValueError('Controller deadzone must be within 0..0.5')
    self.deadzone = float(deadzone)
    self._lock = threading.Lock()
    self._quit_event = threading.Event()
    self._keys = frozenset()
    self._pad = self._keyboard_pending = self._pad_pending = 0
    self._direction = (0., 0.)
    self._quit = self._save = self._closed = False
    # 2026-09-10: bounded pause commands and input release across owner transitions.
    # self._suspended = self._resume_neutral = False
    self._suspended = self._resume_neutral = self._pause_toggle = False

  # 2026-09-10: bounded pause commands and input release across owner transitions.
  # def set_suspended(self, suspended):
  def set_suspended(self, suspended, *, reset=False):
    """Discard gameplay edges at a control barrier; require release on resume.

    Physical held state remains available for command edge detection. A neutral
    focused UI observation after resume is required before new gameplay input.
    Save and quit remain available throughout the barrier.
    """
    # 2026-09-10: bounded pause commands and input release across owner transitions.
    # if type(suspended) is not bool:
    if type(suspended) is not bool or type(reset) is not bool:
      raise ValueError('Suspension must be boolean')
    with self._lock:
      if self._closed:
        raise RuntimeError('Input buffer is closed')
      # 2026-09-10: bounded pause commands and input release across owner transitions.
      # if suspended == self._suspended:
      if suspended == self._suspended and not reset:
        return
      self._suspended, self._resume_neutral = suspended, True
      self._keyboard_pending = self._pad_pending = 0
      self._direction = (0., 0.)

  def feed(self, *, keys=(), axes=(0., 0.), buttons=0, pressed_keys=(), pressed_buttons=0,
           focused=True, connected=False, quit=False):
    keys, pressed_keys = _keys(keys), _keys(pressed_keys)
    if (type(axes) not in (tuple, list) or len(axes) != 2
        or any(type(v) not in (int, float) or not math.isfinite(v) or not -1 <= v <= 1 for v in axes)
        or any(type(v) is not int or not 0 <= v <= 0xffff for v in (buttons, pressed_buttons))
        or any(type(v) is not bool for v in (focused, connected, quit))):
      raise ValueError('Invalid graphical input state')
    with self._lock:
      if self._closed:
        raise RuntimeError('Input buffer is closed')
      self._quit |= quit
      if self._quit:
        self._quit_event.set()
      if not focused:
        self._keys, self._pad = frozenset(), 0
        self._keyboard_pending = self._pad_pending = 0
        # 2026-09-10: bounded pause commands and input release across owner transitions.
        # self._direction, self._save = (0., 0.), False
        self._direction, self._save, self._pause_toggle = (0., 0.), False, False
        return
      new_keys = (keys - self._keys) | pressed_keys
      new_pad = ((buttons & ~self._pad) | pressed_buttons) if connected else 0
      self._keyboard_pending |= _buttons(new_keys, 0)
      self._pad_pending = (self._pad_pending | _buttons((), new_pad)) if connected else 0
      self._quit |= bool(new_keys & {'q', 'escape'} or new_pad & (1 << 4))
      if self._quit:
        self._quit_event.set()
      # 2026-09-10: bounded pause commands and input release across owner transitions.
      # self._save |= bool('p' in new_keys or new_pad & (1 << 6))
      self._save |= bool('p' in new_keys or new_pad & (1 << 6))
      self._pause_toggle ^= bool('k' in new_keys or new_pad & (1 << 5))
      self._keys, self._pad = keys, buttons if connected else 0
      if self._suspended or self._resume_neutral:
        self._keyboard_pending = self._pad_pending = 0
        self._direction = (0., 0.)
        # Check physical inputs, not their net direction: opposite held keys or
        # a masked stick are still held. Press/release events in this poll also
        # prevent it from being mistaken for the required release observation.
        # 2026-09-10: bounded pause commands and input release across owner transitions.
        # gameplay_keys = (KEYS - {'p', 'q', 'escape'}) & (keys | pressed_keys)
        gameplay_keys = (KEYS - {'p', 'q', 'escape', 'k'}) & (keys | pressed_keys)
        gameplay_pad = (buttons | pressed_buttons) & (sum(1 << b for b in PAD_BUTTONS) | (15 << 11))
        neutral = not gameplay_keys and not (connected and (
            gameplay_pad or math.hypot(*axes) > self.deadzone))
        if not self._suspended and neutral:
          self._resume_neutral = False
        return
      digital = bool(keys & {'w', 's', 'a', 'd', 'up', 'down', 'left', 'right'})
      x = int(bool(keys & {'d', 'right'})) - int(bool(keys & {'a', 'left'}))
      y = int(bool(keys & {'w', 'up'})) - int(bool(keys & {'s', 'down'}))
      if not digital and connected:
        # SDL controller D-pad: up=11/down=12/left=13/right=14.
        if buttons & (15 << 11):
          x = int(bool(buttons & (1 << 14))) - int(bool(buttons & (1 << 13)))
          y = int(bool(buttons & (1 << 11))) - int(bool(buttons & (1 << 12)))
        else:
          x, y = axes
          length = math.hypot(x, y)
          scale = (min(length, 1.) - self.deadzone) / (1. - self.deadzone) if length > self.deadzone else 0.
          x, y = (x * scale / length, y * scale / length) if length else (0., 0.)
      length = math.hypot(x, y)
      self._direction = (x / length, y / length) if length > 1 else (float(x), float(y))

  def sample(self, frame=None):
    with self._lock:
      if self._suspended or self._resume_neutral:
        self._keyboard_pending = self._pad_pending = 0
        return wire.default_slot_input()
      value = wire.SlotInput(*self._direction,
          _buttons(self._keys, self._pad) | self._keyboard_pending | self._pad_pending)
      self._keyboard_pending = self._pad_pending = 0
      # Match prediction and transmission see the same representable float32.
      return wire.unpack_slot_input(wire.pack_slot_input(value))[0]

  # 2026-09-10: bounded pause commands and input release across owner transitions.
  # def commands(self):
  #   with self._lock:
  #     result = self._quit, self._save
  #     self._save = False
  #     return result
  def commands(self, *, include_pause=False):
    if type(include_pause) is not bool:
      raise ValueError('Pause command selection must be boolean')
    with self._lock:
      result = self._quit, self._save
      self._save = False
      if include_pause:
        result += (self._pause_toggle,)
        self._pause_toggle = False
      return result

  @property
  def release_required(self):
    with self._lock:
      return self._resume_neutral and not self._suspended

  @property
  def quit_requested(self):
    """Startup/replay may inspect cancellation without consuming a save edge."""
    with self._lock:
      return self._quit

  def request_quit(self):
    with self._lock:
      self._quit = True
      self._quit_event.set()

  def wait_for_quit(self, seconds):
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds <= 1:
      raise ValueError('Input wait must be within 0..1 seconds')
    return self._quit_event.wait(seconds)

  def close(self):
    with self._lock:
      self._closed = self._quit = True
      self._quit_event.set()
      self._keys, self._pad = frozenset(), 0
      self._keyboard_pending = self._pad_pending = 0
      # 2026-09-10: bounded pause commands and input release across owner transitions.
      # self._direction, self._save = (0., 0.), False
      self._direction, self._save, self._pause_toggle = (0., 0.), False, False


class BufferedControls:
  """run() command source; action sampling uses InputBuffer.sample separately."""
  is_graphical = True

  def __init__(self, buffer):
    if not isinstance(buffer, InputBuffer):
      raise ValueError('Expected InputBuffer')
    self.buffer = buffer
    # 2026-09-10: bounded pause commands and input release across owner transitions.
    # self.quit = self.save = False
    self.quit = self.save = self.pause = False

  def __enter__(self):
    return self

  def __exit__(self, *args):
    pass

  def read(self):
    # 2026-09-10: bounded pause commands and input release across owner transitions.
    # self.quit, self.save = self.buffer.commands()
    self.quit, self.save, self.pause = self.buffer.commands(include_pause=True)
    return wire.default_slot_input()

  # 2026-09-10: bounded pause commands and input release across owner transitions.
  # def wait(self, seconds):
  #   return self.buffer.wait_for_quit(seconds)
  def set_suspended(self, suspended):
    self.buffer.set_suspended(suspended)

  def wait(self, seconds):
    return self.buffer.wait_for_quit(seconds)
