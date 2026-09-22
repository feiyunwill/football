#!/usr/bin/env python3
# 2026-09-10: describe actual available modes; rendering remains a separate milestone.
# """Football game main menu (text-based for now, SDL upgradeable in Phase 9).
# 
# Modes:
#   1. Local Play    - Single player vs AI on localhost
#   2. Host Game     - Start multiplayer server and play
#   3. Join Game     - Connect to an existing server
#   4. Settings      - Configure controls, scenario, etc.
#   5. Quit
# 
# Usage:
#     python3 -m gfootball.frame_sync.main_menu
#     python3 -m gfootball.frame_sync.main_menu --mode local  # skip menu, go directly
# """

"""Terminal match menu with local/host/join, durable preferences and replay.

Use --mode to enter an action directly and --settings-file for a specific
preferences file. Host and Join negotiate match v4 and run actual engines.
"""

import sys
# 2026-09-10: screen clearing and port allocation no longer spawn shells or probe ports.
# import os
# import socket
# import time

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent))


# 2026-09-10: connect owned multiplayer and persistent validated preferences.
# _settings_path = None
_settings_path = None
_transport = 'tcp'
_graphics = False


def _options():
    from gfootball.frame_sync.menu_options import load_options
    return load_options(_settings_path)


def _ask(label, value):
    return input(label + ' [' + str(value) + ']: ').strip() or str(value)


def _optional(label, value):
    entered = input(label + ' [' + (value or 'off') + '; - disables]: ').strip()
    return None if entered == '-' else entered or value


def _frames(value):
    entered = input('Frame limit [' + (str(value) if value else 'until Q') + ']: ').strip()
    result = int(entered) if entered else value
    from gfootball.frame_sync.multiplayer_runtime import _frame_limit
    # 2026-09-10: the SDL window supplies interactive exit in graphical mode.
    # _frame_limit(result)
    _frame_limit(result, interactive=_graphics)
    return result


def _control_reporter(can_pause):
    """Keep only the last control identity; staged and applied notices may repeat."""
    from gfootball.frame_sync.match_control import PAUSED, RESUMING
    previous = None
    def changed(control):
        nonlocal previous
        current = (control.epoch, control.phase)
        if current == previous:
            return
        previous = current
        if control.phase == PAUSED:
            print('Match paused. K: resume.' if can_pause else 'Match paused by host.')
        elif control.phase == RESUMING:
            print('Resuming: waiting for players.')
        elif control.epoch:
            print('Match resumed.')
    return changed


def _run_graphical(mode, frames=None, **options):
    from gfootball.frame_sync.graphical_runtime import run_graphical
    def ready(info):
        if mode == 'host':
            print('Hosting', _transport.upper(), 'on port', info['port'])
        # 2026-09-10: advertise available commands for this actual match role.
        # print('WASD/arrows: move | Z/X/C: pass | V: shoot | Shift: sprint | P: save | Q/Esc: exit')
        # print('Controller: left stick/D-pad, A/X/Y: pass, B: shoot, LB: switch, RB: sprint, Back: exit')
        if mode == 'replay':
            print('Replay | Esc / Back: exit')
            return
        print('WASD/arrows: move | Z/X/C: pass | V: shoot | Shift: sprint | Q/Esc: exit')
        print('Controller: left stick/D-pad, A/X/Y: pass, B: shoot, LB: switch, RB: sprint, Back: exit')
        print('K / Guide: pause or resume' if mode != 'join' else 'Host controls pause and resume')
        if options.get('save_path') and mode != 'join':
            print('P / Start: save checkpoint')
    return run_graphical(mode, max_frames=frames, options=options, on_ready=ready)


def _run_action(action):
    try:
        action()
        return 0
    except (EOFError, KeyboardInterrupt):
        print('\nReturned to menu.')
        return 0
    except (ValueError, OSError, RuntimeError, ImportError) as error:
        print('Could not complete this action:', error)
        return 1


# def _clear_screen():
#     os.system('cls' if os.name == 'nt' else 'clear')

def _clear_screen():
    if sys.stdout.isatty():
        print('\033[2J\033[H', end='')


# 2026-09-10: connect owned multiplayer and persistent validated preferences.
# def _find_free_port():
#     s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#     s.bind(('127.0.0.1', 0))
#     port = s.getsockname()[1]
#     s.close()
#     return port

# Port 0 is now passed directly to the real listener when auto allocation is requested.


# 2026-09-10: connect owned multiplayer and persistent validated preferences.
# def print_banner():
#     print('''
# ╔══════════════════════════════════════════════╗
# ║           FOOTBALL - Frame Sync              ║
# ║          Deterministic Multiplayer           ║
# ╠══════════════════════════════════════════════╣
# ║  WASD/Arrows - Move    Z/X/C - Pass         ║
# ║  V - Shot     Space - Pressure   Q - Back    ║
# ╚══════════════════════════════════════════════╝
# ''')

def print_banner():
    print('\nFOOTBALL\nWASD: direction | 0: stop | Z/X/C: pass | V: shoot | Space: pressure | Q: back\n')


# 2026-09-10: preserve old incomplete menu; wire actual match/save/replay entrypoints.
# def menu_local_play():
#     """Local play submenu."""
#     print('\n--- Local Play ---')
#     print('Scenario: [1] academy_empty_goal  [2] academy_run_to_score')
#     print('          [3] academy_vs德_rrimal [4] Custom')
#     choice = input('Select scenario (1-4, default=1): ').strip() or '1'
#     scenarios = {
#         '1': 'academy_empty_goal',
#         '2': 'academy_run_to_score',
#         '3': 'academy_vs德_rrimal',
#     }
#     scenario = scenarios.get(choice, 'academy_empty_goal')
# 
#     left = input('Left team players (default=1): ').strip() or '1'
#     right = input('Right team AI players (default=1): ').strip() or '1'
#     seed = input('Random seed (default=42): ').strip() or '42'
# 
#     print(f'\nStarting: {scenario}, {left}v{right}, seed={seed}')
#     print('Controls: WASD=move, Z/X/C=pass, V=shot, Space=pressure, Q=quit\n')
# 
#     from gfootball.frame_sync.local_play import LocalPlayer
#     player = LocalPlayer(
#         scenario=scenario,
#         left_agents=int(left),
#         right_agents=int(right),
#         seed=int(seed),
#     )
#     player.start()
#     player.run()
# 

# 2026-09-10: connect owned multiplayer and persistent validated preferences.
# def menu_local_play():
#     """Run the real authority/replica loop with optional durable outputs."""
#     from gfootball.frame_sync.local_play import LocalPlayer
#     scenario = input('Scenario (default=academy_empty_goal): ').strip() or 'academy_empty_goal'
#     left = int(input('Left controlled slots (default=1): ').strip() or '1')
#     right = int(input('Right controlled slots (default=0; other players use engine AI): ').strip() or '0')
#     seed = int(input('Random seed (default=42): ').strip() or '42')
#     record = input('Replay output file (empty=off): ').strip() or None
#     save = input('Checkpoint file (empty=off): ').strip() or None
#     frames = input('Frame limit (empty=play until Q): ').strip()
#     player = LocalPlayer(scenario=scenario, left_agents=left, right_agents=right, seed=seed,
#         record_path=record, save_path=save,
#         on_frame=lambda state: print('Frame {frame} score={score} ball={ball}'.format(**state)))
#     try:
#         player.start()
#         print('WASD=set direction, 0=stop, Z/X/C=pass, V=shoot, Space=pressure, P=save, Q=quit')
#         player.run(int(frames) if frames else None)
#     finally:
#         player.stop(finalize=False)

def menu_local_play():
    from gfootball.frame_sync.local_play import LocalPlayer
    options = _options()
    scenario = _ask('Scenario', options.local_scenario)
    left = int(_ask('Left controlled slots', options.local_left))
    right = int(_ask('Right controlled slots; other players use engine AI', options.local_right))
    seed = int(_ask('Random seed', options.seed))
    record = _optional('Replay output file', options.record_path)
    save = _optional('Checkpoint file', options.save_path)
    frames = _frames(options.frames)
    if _graphics:
        return _run_graphical('local', frames, scenario=scenario, left_agents=left, right_agents=right,
                              seed=seed, record_path=record, save_path=save)
    player = LocalPlayer(scenario=scenario, left_agents=left, right_agents=right, seed=seed,
        record_path=record, save_path=save,
        # 2026-09-10: print pause transitions even when no game frame changes.
        # on_frame=lambda state: print('Score {score} ball={ball}'.format(**state)))
        on_frame=lambda state: print('Score {score} ball={ball}'.format(**state)),
        on_control=_control_reporter(True))
    try:
        player.start()
        print_banner()
        # 2026-09-10: local terminal pause is independent of optional saving.
        # print('P: save checkpoint')
        print('K: pause or resume')
        if save is not None:
            print('P: save checkpoint')
        return player.run(frames)
    finally:
        player.stop(finalize=False)


# 2026-09-10: apply persisted optional defaults to continuation and replay too.
# def menu_resume_match():
#     from gfootball.frame_sync.local_play import LocalPlayer
#     path = input('Checkpoint file: ').strip()
#     record = input('Replay output file for this continuation (empty=off): ').strip() or None
#     frames = input('Frame limit (empty=play until Q): ').strip()
#     player = LocalPlayer(resume_path=path, save_path=path, record_path=record,
#         on_frame=lambda state: print('Frame {frame} score={score} ball={ball}'.format(**state)))
#     try:
#         player.start()
#         player.run(int(frames) if frames else None)
#     finally:
#         player.stop(finalize=False)

def menu_resume_match():
    from gfootball.frame_sync.local_play import LocalPlayer
    options = _options()
    path = _ask('Checkpoint file', options.save_path or '')
    record = _optional('Replay output for this continuation', options.record_path)
    frames = _frames(options.frames)
    if _graphics:
        return _run_graphical('local', frames, resume_path=path, save_path=path, record_path=record)
    player = LocalPlayer(resume_path=path, save_path=path, record_path=record,
        # 2026-09-10: print pause transitions even when no game frame changes.
        # on_frame=lambda state: print('Score {score} ball={ball}'.format(**state)))
        on_frame=lambda state: print('Score {score} ball={ball}'.format(**state)),
        on_control=_control_reporter(True))
    try:
        player.start()
        print('K: pause or resume | P: save checkpoint | Q: exit')
        return player.run(frames)
    finally:
        player.stop(finalize=False)


# 2026-09-10: apply persisted optional defaults to continuation and replay too.
# def menu_replay_match():
#     from gfootball.frame_sync.match_archive import playback
#     path = input('Match replay file: ').strip()
#     print(playback(path, on_frame=lambda frame, env: print('Replayed frame', frame)))

def menu_replay_match():
    from gfootball.frame_sync.match_archive import playback
    path = _ask('Match replay file', _options().record_path or '')
    if _graphics:
        return _run_graphical('replay', path=path)
    result = playback(path, on_frame=lambda frame, env: print('Replayed frame', frame))
    print(result)
    return result


# 2026-09-10: connect owned multiplayer and persistent validated preferences.
# def menu_host_game():
#     """Host multiplayer game."""
#     print('\n--- Host Game ---')
#     scenario = input('Scenario (default=academy_empty_goal): ').strip() or 'academy_empty_goal'
#     left = input('Left team players (default=1): ').strip() or '1'
#     right = input('Right team players (default=1): ').strip() or '1'
#     seed = input('Random seed (default=42): ').strip() or '42'
#     port = input('Port (default=auto): ').strip()
#
#     from gfootball.frame_sync.server import FrameSyncServer
#     port = int(port) if port else _find_free_port()
#     server = FrameSyncServer(
#         listen_host='0.0.0.0',
#         listen_port=port,
#         scenario_name=scenario,
#         left_agents=int(left),
#         right_agents=int(right),
#         game_engine_random_seed=int(seed),
#     )
#     server.start()
#     print(f'\nServer started on port {port}')
#     print(f'Scenario: {scenario}, {left}v{right}, seed={seed}')
#     print('Waiting for players... (press Ctrl+C to stop)\n')
#
#     try:
#         while True:
#             time.sleep(1)
#             n = server.get_connected_client_count()
#             print(f'\r  Connected players: {n}', end='', flush=True)
#     except KeyboardInterrupt:
#         print('\nStopping server...')
#     finally:
#         server.stop()

def menu_host_game():
    from gfootball.frame_sync.multiplayer_runtime import HostedMatch
    options = _options()
    scenario = _ask('Scenario', options.host_scenario)
    left = int(_ask('Left controlled slots', options.host_left))
    right = int(_ask('Right controlled slots', options.host_right))
    seed = int(_ask('Random seed', options.seed))
    port = int(_ask('Listen port; 0 assigns a port', options.port))
    record = _optional('Replay output file', options.record_path)
    save = _optional('Checkpoint file', options.save_path)
    frames = _frames(options.frames)
    # 2026-09-10: explicit TCP/UDP transport uses the same Host flow.
    # host = HostedMatch(scenario=scenario, left=left, right=right, seed=seed, port=port,
    #     record_path=record, save_path=save,
    if _graphics:
        return _run_graphical('host', frames, scenario=scenario, left=left, right=right, seed=seed,
                              port=port, record_path=record, save_path=save, transport=_transport)
    host = HostedMatch(scenario=scenario, left=left, right=right, seed=seed, port=port,
        record_path=record, save_path=save, transport=_transport,
        # 2026-09-10: print pause transitions even when no game frame changes.
        # on_frame=lambda state: print('Score {score} ball={ball}'.format(**state)))
        on_frame=lambda state: print('Score {score} ball={ball}'.format(**state)),
        on_control=_control_reporter(True))
    try:
        host.start()
        # 2026-09-10: peers must use the same transport.
        # print('Hosting on port', host.port, '- waiting for', left + right, 'players including this host.')
        print('Hosting', _transport.upper(), 'on port', host.port, '- waiting for', left + right, 'players including this host.')
        print_banner()
        # 2026-09-10: only the host changes pause; save requires an output.
        # print('P: save checkpoint. Each controlled slot requires a connected player.')
        print('K: pause or resume. Each controlled slot requires a connected player.')
        if save is not None:
            print('P: save checkpoint')
        result = host.run(frames)
        print('Match ended after', result['frame'], 'frames.')
        return result
    finally:
        host.close(finalize=False)


# 2026-09-10: connect owned multiplayer and persistent validated preferences.
# def menu_join_game():
#     """Join an existing game."""
#     print('\n--- Join Game ---')
#     host = input('Server host (default=127.0.0.1): ').strip() or '127.0.0.1'
#     port = input('Server port (default=12345): ').strip() or '12345'
#
#     from gfootball.frame_sync.client import FrameSyncClient
#     from gfootball.frame_sync.protocol import default_slot_input
#
#     def get_input():
#         # Placeholder: will be replaced with SDL keyboard in Phase 9
#         return []
#
#     print(f'\nConnecting to {host}:{port}...')
#     client = FrameSyncClient(host, int(port), get_input)
#     try:
#         (seed, left, right), slots = client.connect()
#         client.send_ready()
#         print(f'Connected! slots={slots}, seed={seed}, {left}v{right}')
#         print('Game in progress... (press Ctrl+C to disconnect)')
#         while True:
#             auth = client.pop_authoritative_frame()
#             if auth:
#                 fid, inputs = auth
#                 pass  # Process frame
#             time.sleep(0.1)
#     except KeyboardInterrupt:
#         print('\nDisconnecting...')
#     except Exception as e:
#         print(f'Connection failed: {e}')
#     finally:
#         client.close()

def menu_join_game():
    from gfootball.frame_sync.multiplayer_runtime import NetworkPlayer
    options = _options()
    host = _ask('Server host', options.host)
    port = int(_ask('Server port', options.port))
    frames = _frames(options.frames)
    # 2026-09-10: explicit CLI transport applies to the actual Join owner.
    # player = NetworkPlayer(host, port,
    if _graphics:
        return _run_graphical('join', frames, host=host, port=port, transport=_transport)
    player = NetworkPlayer(host, port, transport=_transport,
        # 2026-09-10: print pause transitions even when no game frame changes.
        # on_frame=lambda state: print('Score {score} ball={ball}'.format(**state)))
        on_frame=lambda state: print('Score {score} ball={ball}'.format(**state)),
        on_control=_control_reporter(False))
    try:
        settings, slots = player.start()
        print('Connected to', settings.scenario_name, '- assigned player', slots[0] + 1)
        print_banner()
        return player.run(frames)
    finally:
        player.close()


# 2026-09-10: connect owned multiplayer and persistent validated preferences.
# def menu_settings():
#     """Settings submenu."""
#     print('\n--- Settings ---')
#     print('  (Settings will be implemented with SDL rendering)')
#     print('  For now, use command-line flags:')
#     print('    --scenario SCENARIO')
#     print('    --left N --right N')
#     print('    --seed N')
#     input('\nPress Enter to return to menu...')

def menu_settings():
    from dataclasses import asdict
    from gfootball.frame_sync.menu_options import MenuOptions, save_options
    values = asdict(_options())
    prompts = (
        ('local_scenario', 'Local scenario'), ('host_scenario', 'Hosted scenario'),
        ('local_left', 'Local left controlled slots'), ('local_right', 'Local right controlled slots'),
        ('host_left', 'Hosted left controlled slots'), ('host_right', 'Hosted right controlled slots'),
        ('seed', 'Random seed'), ('host', 'Default server host'), ('port', 'Default server port'),
        ('frames', 'Frame limit'), ('record_path', 'Replay output file'), ('save_path', 'Checkpoint file'))
    numeric = {'local_left', 'local_right', 'host_left', 'host_right', 'seed', 'port', 'frames'}
    optional = {'frames', 'record_path', 'save_path'}
    print('Enter keeps a value; - clears an optional limit or output file.')
    for field, label in prompts:
        value = input(label + ' [' + (str(values[field]) if values[field] is not None else 'off') + ']: ').strip()
        if not value:
            continue
        values[field] = None if field in optional and value == '-' else int(value) if field in numeric else value
    options = MenuOptions(**values)
    path = save_options(options, _settings_path)
    print('Preferences saved to', path)
    return options


# 2026-09-10: connect owned multiplayer and persistent validated preferences.
# def main():
#     import argparse
#     parser = argparse.ArgumentParser(description='Football Frame Sync Menu')
#     # 2026-09-10: expose durable continuation and verified native replay.
#     # parser.add_argument('--mode', choices=['local', 'host', 'join', 'settings'],
#     parser.add_argument('--mode', choices=['local', 'host', 'join', 'settings', 'resume', 'replay'],
#                         help='Skip menu and go directly to mode')
#     args = parser.parse_args()
#
#     if args.mode == 'resume':
#         menu_resume_match()
#         return
#     if args.mode == 'replay':
#         menu_replay_match()
#         return
#     if args.mode == 'local':
#         menu_local_play()
#         return
#     elif args.mode == 'host':
#         menu_host_game()
#         return
#     elif args.mode == 'join':
#         menu_join_game()
#         return
#     elif args.mode == 'settings':
#         menu_settings()
#         return
#
#     while True:
#         _clear_screen()
#         print_banner()
#         print('  [1] Local Play    - Single player vs AI')
#         print('  [2] Host Game     - Start multiplayer server')
#         print('  [3] Join Game     - Connect to existing server')
#         print('  [4] Settings      - Configure options')
#         print('  [5] Quit')
#         print('  [6] Continue saved match')
#         print('  [7] Replay saved match')
#         print()
#
#         # 2026-09-10: include the two new functional storage entries.
#         # choice = input('Select (1-5): ').strip()
#         choice = input('Select (1-7): ').strip()
#
#         if choice == '1':
#             menu_local_play()
#         elif choice == '2':
#             menu_host_game()
#         elif choice == '3':
#             menu_join_game()
#         elif choice == '4':
#             menu_settings()
#         elif choice == '6':
#             menu_resume_match()
#         elif choice == '7':
#             menu_replay_match()
#         elif choice == '5' or choice.lower() == 'q':
#             print('Goodbye!')
#             break
#         else:
#             print('Invalid choice. Press Enter...')
#             input()

def main():
    import argparse
    # 2026-09-10: scope transport to this invocation like the settings path.
    # global _settings_path
    # 2026-09-10: keep graphical mode scoped to this menu invocation.
    # global _settings_path, _transport
    global _settings_path, _transport, _graphics
    parser = argparse.ArgumentParser(description='Football match menu')
    parser.add_argument('--mode', choices=['local', 'host', 'join', 'settings', 'resume', 'replay'])
    parser.add_argument('--settings-file', help='Use a specific preferences file')
    parser.add_argument('--transport', choices=['tcp', 'udp'], default='tcp', help='Host/Join transport; peers must match')
    parser.add_argument('--graphics', action='store_true', help='Play in the native SDL window')
    args = parser.parse_args()
    previous, _settings_path = _settings_path, args.settings_file
    previous_graphics, _graphics = _graphics, args.graphics
    previous_transport, _transport = _transport, args.transport
    actions = {'local': menu_local_play, 'host': menu_host_game, 'join': menu_join_game,
               'settings': menu_settings, 'resume': menu_resume_match, 'replay': menu_replay_match}
    try:
        if args.mode:
            return _run_action(actions[args.mode])
        choices = {'1': 'local', '2': 'host', '3': 'join', '4': 'settings', '6': 'resume', '7': 'replay'}
        while True:
            _clear_screen()
            print_banner()
            print('[1] Local play   [2] Host and play   [3] Join match   [4] Preferences')
            print('[5] Quit   [6] Continue saved match   [7] Replay saved match')
            choice = input('Select: ').strip().lower()
            if choice in ('5', 'q'):
                return 0
            if choice in choices:
                _run_action(actions[choices[choice]])
            else:
                print('Select one of the listed options.')
    except (EOFError, KeyboardInterrupt):
        print('\nMenu closed.')
        return 0
    finally:
        _settings_path = previous
        _transport = previous_transport
        _graphics = previous_graphics


if __name__ == '__main__':
    # 2026-09-10: failed direct modes report a nonzero process exit.
    # main()
    raise SystemExit(main())
