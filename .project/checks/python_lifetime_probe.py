#!/usr/bin/env python3
"""Check lifecycle compatibility through the compiled Python adapter."""
import gc
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location("_gameplayfootball", sys.argv[1])
game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(game)
assertions = 0
for cycle in range(4):
    environment = game.GameEnv()
    environment.game_config.render = False
    environment.start_game()
    assert len(environment.get_info().left_team) == 11
    assertions += 1
    environment.state = game.game_running
    environment.step()
    snapshot = environment.get_state(b"lifetime-probe")
    environment.step()
    assert environment.set_state(snapshot) == b"lifetime-probe"
    assertions += 1
    assert isinstance(environment.get_state_digest(), bytes)
    assertions += 1
    # 2026-09-10: invalid native reset must preserve a match after kickoff.
    for _ in range(1000):
        environment.step()
        if environment.get_info().step >= 2:
            break
    before_step = environment.get_info().step
    assert before_step >= 2
    assertions += 1
    before_digest = environment.get_state_digest()
    invalid = game.ScenarioConfig.make()
    invalid.left_agents = 12
    try:
        environment.reset(invalid, False)
    except ValueError:
        assertions += 1
    else:
        raise AssertionError("Invalid reset was accepted")
    assert environment.get_info().step == before_step
    assertions += 1
    assert environment.get_state_digest() == before_digest
    assertions += 1
    assert environment.state == game.game_running
    assertions += 1
    environment.step()
    assert environment.get_info().step == before_step + 1
    assertions += 1
    running_digest = environment.get_state_digest()
    environment.pause()
    paused_digest = environment.get_state_digest()
    environment.step()
    assert environment.state == game.game_paused and environment.get_state_digest() == paused_digest
    assertions += 1
    environment.resume()
    assert environment.get_state_digest() == running_digest
    assertions += 1
    environment.finish()
    assert environment.state == game.game_done and len(environment.get_info().left_team) == 11
    assertions += 1
    environment.close()
    environment.close()
    assert environment.state == game.game_done
    assertions += 1
    try:
        environment.step()
    except RuntimeError:
        assertions += 1
    else:
        raise AssertionError("Closed Python environment accepted a step")
    environment.start_game()
    assert len(environment.get_info().right_team) == 11
    assertions += 1
    del environment
    gc.collect()
print(json.dumps({"passed": True, "assertions": assertions, "skipped": 0}))
