"""Generate an immutable native fixture from the actual current Python InputBuffer."""
from pathlib import Path
import hashlib
import json
import math
import random
import struct
import sys

# 2026-09-13: locate the current checkout for formal execution.
# ROOT = Path('/root/work_space/football')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gfootball.frame_sync.graphical_input import InputBuffer, KEYS
from gfootball.frame_sync import protocol


def main():
    output = Path(sys.argv[1])
    if output.exists():
        raise RuntimeError('Preserve existing oracle cohort')
    lines = []
    counts = {}
    buffer = None

    def emit(kind, *values):
        lines.append(' '.join([kind, *(str(int(v)) if type(v) is bool else str(v) for v in values)]))
        counts[kind] = counts.get(kind, 0) + 1

    def rejects(operation):
        try:
            operation()
        except (ValueError, RuntimeError):
            return True
        return False

    def begin(deadzone=.18):
        nonlocal buffer
        def construct():
            nonlocal buffer
            buffer = InputBuffer(deadzone)
        emit('B', struct.unpack('<Q', struct.pack('<d', deadzone))[0], rejects(construct))

    def feed(keys=(), pressed=(), axes=(0., 0.), buttons=0, pressed_buttons=0,
             focused=True, connected=False, quit=False):
        # Native SDL exposes float32 axes; promote exactly those values in Python.
        axes = struct.unpack('<ff', struct.pack('<ff', *axes))
        error = rejects(lambda: buffer.feed(keys=keys, pressed_keys=pressed, axes=axes,
            buttons=buttons, pressed_buttons=pressed_buttons, focused=focused, connected=connected, quit=quit))
        emit('F', ','.join(keys) or '-', ','.join(pressed) or '-',
             *struct.unpack('<II', struct.pack('<ff', *axes)), buttons, pressed_buttons,
             focused, connected, quit, error)

    def suspend(value, reset=False):
        emit('S', value, reset, rejects(lambda: buffer.set_suspended(value, reset=reset)))

    def take():
        emit('T', *struct.unpack('<IIH', protocol.pack_slot_input(buffer.sample())))

    def commands():
        emit('C', *buffer.commands(include_pause=True))

    def state():
        emit('R', buffer.release_required, buffer.quit_requested)

    begin()
    for deadzone in (-.1, .50001, math.nan, math.inf):
        begin(deadzone)
    for deadzone in (0., .18, .5):
        begin(deadzone)
        for key in sorted(KEYS):
            feed(keys=[key], pressed=[key]); take(); take(); commands()
            feed(); take(); commands()
            feed(pressed=[key]); feed(); take(); take(); commands()
        for button in range(16):
            feed(buttons=1 << button, pressed_buttons=1 << button, connected=True)
            take(); take(); commands()
            feed(connected=True); take()
            feed(pressed_buttons=1 << button, connected=True); feed(connected=True)
            take(); take(); commands()
        for x, y in ((0., 0.), (-0., 0.), (.18, 0.), (.17999, 0.), (.18001, 0.),
                     (-.1, .1), (.5, .5), (1., -1.), (-1., 0.)):
            feed(axes=(x, y), connected=True); take()
            feed(keys=['w', 's'], axes=(x, y), connected=True); take()
        feed(keys=['w', 'lshift'], buttons=1, connected=True)
        suspend(True); take(); feed(pressed=['v']); take()
        suspend(False); state(); feed(keys=['w', 's']); take(); state()
        feed(pressed=['v']); take(); state(); feed(); state()
        feed(keys=['w', 'lshift', 'v']); take()
        feed(keys=['w', 'lshift'], focused=False); take(); commands()
        feed(buttons=1, pressed_buttons=1, connected=True)
        feed(connected=False); take()
        for axes in ((math.nan, 0.), (math.inf, 0.), (1.001, 0.)):
            feed(axes=axes, connected=True); take()
        feed(keys=['unknown']); take()

    rng = random.Random(20260913)
    key_names = sorted(KEYS)
    for iteration in range(5000):
        if iteration % 500 == 0:
            begin((0., .18, .5)[iteration // 500 % 3])
        keys = rng.sample(key_names, rng.randrange(6))
        pressed = rng.sample(key_names, rng.randrange(4))
        axes = (rng.uniform(-1, 1), rng.uniform(-1, 1))
        feed(keys, pressed, axes, rng.randrange(1 << 16), rng.randrange(1 << 16),
             focused=rng.randrange(12) != 0, connected=rng.randrange(7) != 0)
        if iteration % 7 == 0:
            suspend(rng.choice((True, False)), reset=iteration % 49 == 0)
        if iteration % 3:
            take()
        if iteration % 5 == 0:
            take(); take()
        if iteration % 2 == 0:
            commands()
        state()
    buffer.close(); emit('X'); take(); commands(); state()
    feed(); suspend(True)
    buffer.close(); emit('X'); take(); state()
    output.write_text('\n'.join(lines) + '\n')
    sources = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
               (Path(__file__), ROOT / 'gfootball/frame_sync/graphical_input.py',
                ROOT / 'gfootball/frame_sync/protocol.py')}
    payload = dict(operations=len(lines), counts=counts, sources=sources,
                   fixture_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    output.with_suffix('.json').write_text(json.dumps(payload, indent=2) + '\n')
    print(json.dumps(payload))


if __name__ == '__main__':
    main()
