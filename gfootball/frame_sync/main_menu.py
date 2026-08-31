#!/usr/bin/env python3
"""Football game main menu (text-based for now, SDL upgradeable in Phase 9).

Modes:
  1. Local Play    - Single player vs AI on localhost
  2. Host Game     - Start multiplayer server and play
  3. Join Game     - Connect to an existing server
  4. Settings      - Configure controls, scenario, etc.
  5. Quit

Usage:
    python3 -m gfootball.frame_sync.main_menu
    python3 -m gfootball.frame_sync.main_menu --mode local  # skip menu, go directly
"""

import sys
import os
import socket
import time

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent))


def _clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def _find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def print_banner():
    print('''
╔══════════════════════════════════════════════╗
║           FOOTBALL - Frame Sync              ║
║          Deterministic Multiplayer           ║
╠══════════════════════════════════════════════╣
║  WASD/Arrows - Move    Z/X/C - Pass         ║
║  V - Shot     Space - Pressure   Q - Back    ║
╚══════════════════════════════════════════════╝
''')


def menu_local_play():
    """Local play submenu."""
    print('\n--- Local Play ---')
    print('Scenario: [1] academy_empty_goal  [2] academy_run_to_score')
    print('          [3] academy_vs德_rrimal [4] Custom')
    choice = input('Select scenario (1-4, default=1): ').strip() or '1'
    scenarios = {
        '1': 'academy_empty_goal',
        '2': 'academy_run_to_score',
        '3': 'academy_vs德_rrimal',
    }
    scenario = scenarios.get(choice, 'academy_empty_goal')

    left = input('Left team players (default=1): ').strip() or '1'
    right = input('Right team AI players (default=1): ').strip() or '1'
    seed = input('Random seed (default=42): ').strip() or '42'

    print(f'\nStarting: {scenario}, {left}v{right}, seed={seed}')
    print('Controls: WASD=move, Z/X/C=pass, V=shot, Space=pressure, Q=quit\n')

    from gfootball.frame_sync.local_play import LocalPlayer
    player = LocalPlayer(
        scenario=scenario,
        left_agents=int(left),
        right_agents=int(right),
        seed=int(seed),
    )
    player.start()
    player.run()


def menu_host_game():
    """Host multiplayer game."""
    print('\n--- Host Game ---')
    scenario = input('Scenario (default=academy_empty_goal): ').strip() or 'academy_empty_goal'
    left = input('Left team players (default=1): ').strip() or '1'
    right = input('Right team players (default=1): ').strip() or '1'
    seed = input('Random seed (default=42): ').strip() or '42'
    port = input('Port (default=auto): ').strip()

    from gfootball.frame_sync.server import FrameSyncServer
    port = int(port) if port else _find_free_port()
    server = FrameSyncServer(
        listen_host='0.0.0.0',
        listen_port=port,
        scenario_name=scenario,
        left_agents=int(left),
        right_agents=int(right),
        game_engine_random_seed=int(seed),
    )
    server.start()
    print(f'\nServer started on port {port}')
    print(f'Scenario: {scenario}, {left}v{right}, seed={seed}')
    print('Waiting for players... (press Ctrl+C to stop)\n')

    try:
        while True:
            time.sleep(1)
            n = server.get_connected_client_count()
            print(f'\r  Connected players: {n}', end='', flush=True)
    except KeyboardInterrupt:
        print('\nStopping server...')
    finally:
        server.stop()


def menu_join_game():
    """Join an existing game."""
    print('\n--- Join Game ---')
    host = input('Server host (default=127.0.0.1): ').strip() or '127.0.0.1'
    port = input('Server port (default=12345): ').strip() or '12345'

    from gfootball.frame_sync.client import FrameSyncClient
    from gfootball.frame_sync.protocol import default_slot_input

    def get_input():
        # Placeholder: will be replaced with SDL keyboard in Phase 9
        return []

    print(f'\nConnecting to {host}:{port}...')
    client = FrameSyncClient(host, int(port), get_input)
    try:
        (seed, left, right), slots = client.connect()
        client.send_ready()
        print(f'Connected! slots={slots}, seed={seed}, {left}v{right}')
        print('Game in progress... (press Ctrl+C to disconnect)')
        while True:
            auth = client.pop_authoritative_frame()
            if auth:
                fid, inputs = auth
                pass  # Process frame
            time.sleep(0.1)
    except KeyboardInterrupt:
        print('\nDisconnecting...')
    except Exception as e:
        print(f'Connection failed: {e}')
    finally:
        client.close()


def menu_settings():
    """Settings submenu."""
    print('\n--- Settings ---')
    print('  (Settings will be implemented with SDL rendering)')
    print('  For now, use command-line flags:')
    print('    --scenario SCENARIO')
    print('    --left N --right N')
    print('    --seed N')
    input('\nPress Enter to return to menu...')


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Football Frame Sync Menu')
    parser.add_argument('--mode', choices=['local', 'host', 'join', 'settings'],
                        help='Skip menu and go directly to mode')
    args = parser.parse_args()

    if args.mode == 'local':
        menu_local_play()
        return
    elif args.mode == 'host':
        menu_host_game()
        return
    elif args.mode == 'join':
        menu_join_game()
        return
    elif args.mode == 'settings':
        menu_settings()
        return

    while True:
        _clear_screen()
        print_banner()
        print('  [1] Local Play    - Single player vs AI')
        print('  [2] Host Game     - Start multiplayer server')
        print('  [3] Join Game     - Connect to existing server')
        print('  [4] Settings      - Configure options')
        print('  [5] Quit')
        print()

        choice = input('Select (1-5): ').strip()

        if choice == '1':
            menu_local_play()
        elif choice == '2':
            menu_host_game()
        elif choice == '3':
            menu_join_game()
        elif choice == '4':
            menu_settings()
        elif choice == '5' or choice.lower() == 'q':
            print('Goodbye!')
            break
        else:
            print('Invalid choice. Press Enter...')
            input()


if __name__ == '__main__':
    main()
