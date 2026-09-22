# Environment API #
<!-- 2026-09-10: distinguish the maintained API from the retained legacy protocol.
Google Research Football environment follows GYM API design:
-->

The maintained public environment uses [Gymnasium](gymnasium.md). It returns
`(observation, info)` from `reset(seed=...)` and
`(observation, reward, terminated, truncated, info)` from `step(action)`.
Use `gymnasium.make("gfootball.gymnasium:GFootball-11_vs_11_easy_stochastic-SMM-v0")`.

The existing `gfootball.env.create_environment(...)` factory retains the
four-result protocol below for existing football replay and actor code. It uses
Gymnasium spaces, but is not itself a Gymnasium Env and does not require old Gym:

* `reset()` - resets environment to the initial state.
* `observation, reward, done, info = step(action)` - performs a single step.
* `observation = observation()` - returns current observations.
* `render(mode=human|rgb_array)` - can be called at any time to enable rendering.
  The main difference from the GYM API is that calling `render` enables
  continuous rendering of the episode (no need to call the method on each step).
  Calling `render` enables pixels to be available in the observation.
  Note - rendering slows down `step` method significantly.
* `disable_render()` - disables rendering previously enabled with `render` call.
* `close()` - releases environment object.

On top of the standard API, we provide a number of additional methods:

* `state = get_state()` - provides a current environment's state containing
  all values affecting environment's behavior (random number generator state,
  current players' mental model, physics etc.). The state returned is an opaque
  object to be consumed by `set_state(state)` API method in order to restore
  environment's state from the past.
* `set_state(state)` - restores environment's state to previously snapshoted
  state using `get_state()`. This method can be used to check outcome of executing
  sequences of different actions starting at a fixed state.
* `write_dump(name)` - writes a dump of the current scenario to the disk. Dump
  contains a snapshot of observations for each step of the episode and can be used
  to analyze episode's trajectory offline.

For example API usage have a look at [play_game.py](../play_game.py).
