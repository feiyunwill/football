# Saving replays, logs, traces #

GFootball environment supports recording of scenarios for later watching or
analysis. Each trace dump consists of a pickled episode trace (observations,
reward, additional debug info) and optionally an AVI file with the rendered episode.
Pickled episode trace can be played back later on using `replay.py` script.
By default trace dumps are disabled to not occupy disk space. They
are controlled by the following set of flags:

-  `dump_full_episodes` - should trace for each entire episode be recorded.
-  `dump_scores` - should sample traces for scores be recorded.
-  `tracesdir` - directory in which trace dumps are saved.
-  `write_video` - should a video be recorded together with the trace.
    If rendering is disabled (`render` config flag), the video contains a simple
    episode animation.

There are following scripts provided to operate on trace dumps:

-  `dump_to_txt.py` - converts trace dump to human-readable form.
-  `dump_to_video.py` - converts trace dump to a 2D representation video.
-  `replay.py` - replays a given trace dump using environment.

## Recording resource limits

`recording_limits` configures the observation cache. Defaults retain up to 100
steps and 256 MiB, with separate limits for one observation, additional video
frames and debug text. Old cached observations are evicted when the history is
full. Invalid or oversized individual observations raise `RecordingCapacityError`.

`recording_output_limits` configures output files. Defaults allow 128 MiB per
dump, 512 MiB per video, 4 GiB of directory payload, 256 payload files and four
active recordings. Each recording reserves its full file allowance before it
starts. Existing direct files and active reservations count toward the directory
limit; subdirectory contents do not. Writers sharing a directory must use the
same `total_bytes`, `total_files`, `active_dumps` and `scan_entries` settings while
any recording is active. Per-file limits may differ. Independent cooperating
processes coordinate these reservations through OS file locks.

Successful recordings are published on explicit close. Recording errors abort
the incomplete output and preserve existing files. The hidden
`.football-recording-v1` directory retains bounded lock metadata across runs;
it is separate from the payload allowance and must remain in place while
recorders are active. Process exit releases reservations automatically. Partial
payload files left by a crashed process continue to count toward capacity.

Video size checks happen after encoder writes and release, so encoder buffers
can temporarily exceed the file limit. Publication requires hard-link support
on the output filesystem; the dump/video pair is not an atomic file group.
Windows local-file coordination has automated coverage. POSIX and the complete
native environment recording path still require the optimization acceptance run.

## Replay reads and conversion

Replay dumps are trusted local pickle files. Pickle can execute code; resource
limits do not make files from unknown sources safe to load.

`ScriptHelpers` accepts `replay_limits` and `observation_limits` dictionaries.
`replay_limits` in the environment configuration also controls replay players.
Defaults allow 128 MiB per input file, 32 MiB per serialized record, 10,000 input
records, and 256 MiB retained by the compatibility `load_dump()` list API.
`iter_dump()` reads one validated record at a time; its arrays are read-only.
`load_dump()` continues returning mutable records and arrays within its limits.
Truncated records, changed input files and exceeded budgets raise errors.

Text export streams to a temporary file and replaces its explicitly named target
only after success. Large arrays are displayed as summaries with shape and dtype;
NumPy's global display settings are unchanged. Text output is limited to 128 MiB
by default. Converted playback input is limited to 128 MiB and 100,000 records,
including intermediate actions and ten final idle records.

Playback requires consecutive records starting at frame zero. Requested FPS must
divide the 100 Hz physics rate and preserve every original action boundary. For
example, a recording with 20 physics steps per observation runs at 5 FPS; replay
at 10 FPS inserts one idle action between recorded inputs. A request for 60 FPS
is rejected because it cannot be represented exactly by integer physics steps.

Replay players in one environment share an action reader for the same resolved
path. Each source retains its configuration and current action vector, with an
8 MiB aggregate cache limit, at most 22 sources and 22 consumers. File buffers and
fixed control objects are separately bounded by those counts. Observations are
not retained by action players. All consumers finish a row before advancing and
reset together. EOF raises `ReplayExhausted` instead of exiting the application.
Independent environments own independent playback positions.

The helper closes playback resources before removing its private temporary
directory and does not mutate the caller's configuration updates. These budgets
cover owned retained data and output, not arbitrary pickle reducer allocations,
caller-retained records, total process RSS, native engine memory or GPU memory.
Replay objects have one explicit process owner; sharing them across fork is not
supported. Streaming/file/lifecycle checks run on Windows; actual native replay
identity, pooled-engine cadence and POSIX acceptance still need the native suite.

## Environment logs
Environment uses `absl.logging` module for logging.
You can change logging level by setting --verbosity flag to one of the following values:

-  `-1` - warning, only warnings and above are logged when problems are encountered,
-  `0` - info (the default), some per-episode statistics and similar are logged as well,
-  `1` - debug, additional debugging messages are included.
