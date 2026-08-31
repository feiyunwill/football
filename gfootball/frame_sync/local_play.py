#!/usr/bin/env python3
"""Local single-player mode: local server + client over localhost TCP.

Usage:
    python3 -m gfootball.frame_sync.local_play [--scenario SCENARIO] [--port PORT]

The server runs in-process (background thread). The client connects via
localhost TCP, reads keyboard input (stdin for now), and sends frame inputs.
Rendering is added in Phase 9 (main menu).

Architecture:
    FrameSyncServer (thread) <-> FrameSyncClient (main thread)
    Server runs GameEnv headless.
    Client reads input, sends FrameInput, receives AuthoritativeFrame.
"""

import socket
import sys
import time
import threading
import select

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent))

from gfootball.frame_sync.server import FrameSyncServer
from gfootball.frame_sync.client import FrameSyncClient
from gfootball.frame_sync.protocol import SlotInput, default_slot_input


def _find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class LocalPlayer(object):
    """Manages local server + client for single-player mode."""

    def __init__(self, scenario='academy_empty_goal', port=None,
                 left_agents=1, right_agents=0, seed=42,
                 controlled_slots=None):
        self.scenario = scenario
        self.port = port or _find_free_port()
        self.left_agents = left_agents
        self.right_agents = right_agents
        self.seed = seed
        self.server = None
        self.client = None
        self._slot_inputs = {}  # slot -> SlotInput (current frame)
        # Slots the player controls (default: slot 0)
        self._controlled_slots = controlled_slots or [0]
        self._running = False

    def _get_input_callback(self):
        """Return callback that client uses to get input each frame."""
        def callback():
            entries = []
            for slot in self._controlled_slots:
                inp = self._slot_inputs.get(slot, default_slot_input())
                entries.append((slot, inp))
            return entries
        return callback

    def start(self):
        """Start local server and connect client."""
        print(f'LocalPlay: starting server on 127.0.0.1:{self.port}')
        print(f'  scenario={self.scenario}, {self.left_agents}v{self.right_agents}, seed={self.seed}')
        print(f'  controlled slots={self._controlled_slots}')

        self.server = FrameSyncServer(
            listen_host='127.0.0.1',
            listen_port=self.port,
            scenario_name=self.scenario,
            left_agents=self.left_agents,
            right_agents=self.right_agents,
            game_engine_random_seed=self.seed,
            state_hash_interval=0,
        )
        self.server.start()
        time.sleep(0.3)  # wait for server to start listening

        self.client = FrameSyncClient(
            '127.0.0.1',
            self.port,
            self._get_input_callback(),
        )
        (seed, left, right), slots = self.client.connect()
        self.client.send_ready()
        print(f'LocalPlay: connected! slots={slots}, seed={seed}')
        self._running = True

    def read_keyboard(self):
        """Read keyboard input from stdin (non-blocking).
        Returns dict of slot -> SlotInput for controlled slots.
        """
        dir_x, dir_y = 0.0, 0.0
        buttons = 0

        # Non-blocking read from stdin
        if sys.stdin.isatty():
            try:
                if select.select([sys.stdin], [], [], 0)[0]:
                    ch = sys.stdin.read(1)
                    if ch in ('w', 'W'):
                        dir_y = 1.0
                    elif ch in ('s', 'S'):
                        dir_y = -1.0
                    elif ch in ('a', 'A'):
                        dir_x = -1.0
                    elif ch in ('d', 'D'):
                        dir_x = 1.0
                    elif ch == 'z':
                        buttons |= (1 << 2)   # ShortPass
                    elif ch == 'x':
                        buttons |= (1 << 1)   # HighPass
                    elif ch == 'c':
                        buttons |= (1 << 0)   # LongPass
                    elif ch == 'v':
                        buttons |= (1 << 3)   # Shot
                    elif ch == ' ':
                        buttons |= (1 << 6)   # Pressure
                    elif ch == 'q' or ch == '\x1b':
                        self._running = False
            except (OSError, IOError):
                pass

        inp = SlotInput(dir_x, dir_y, buttons)
        # All controlled slots get the same input (shared keyboard)
        return {slot: inp for slot in self._controlled_slots}

    def run(self, max_frames=None):
        """Run the game loop."""
        print('LocalPlay: running! Controls: WASD=move, Z/X/C=pass, V=shot, Space=pressure, Q=quit')
        frame = 0
        try:
            while self._running:
                # Read keyboard input
                kb_inputs = self.read_keyboard()
                for slot, inp in kb_inputs.items():
                    self._slot_inputs[slot] = inp

                # Send input to server
                self.client.send_frame_input(frame)

                # Run server frame
                self.server.run_one_frame(timeout_ms=100)

                # Receive authoritative frame
                auth = self.client.pop_authoritative_frame()
                if auth:
                    auth_fid, auth_inputs = auth
                    # Apply authoritative inputs to local state
                    for slot_idx, inp in auth_inputs:
                        self._slot_inputs[slot_idx] = inp

                frame += 1
                if max_frames and frame >= max_frames:
                    break

                # Maintain ~10 fps
                time.sleep(0.1)

        except KeyboardInterrupt:
            print('\nLocalPlay: interrupted')
        finally:
            self.stop()

    def stop(self):
        self._running = False
        if self.client:
            self.client.close()
        if self.server:
            self.server.stop()
        print('LocalPlay: stopped')


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Local single-player football')
    parser.add_argument('--scenario', default='academy_empty_goal', help='Scenario name')
    parser.add_argument('--port', type=int, default=None, help='Port (auto if not set)')
    parser.add_argument('--left', type=int, default=1, help='Left team agents')
    parser.add_argument('--right', type=int, default=0, help='Right team agents')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    parser.add_argument('--frames', type=int, default=None, help='Max frames (None=infinite)')
    parser.add_argument('--controlled', type=str, default='0',
                        help='Comma-separated slot indices to control (default: 0)')
    args = parser.parse_args()

    controlled = [int(s.strip()) for s in args.controlled.split(',') if s.strip()]

    player = LocalPlayer(
        scenario=args.scenario,
        port=args.port,
        left_agents=args.left,
        right_agents=args.right,
        seed=args.seed,
        controlled_slots=controlled,
    )
    player.start()
    player.run(max_frames=args.frames)


if __name__ == '__main__':
    main()
