// 2026-09-13: common checked prefix save; mid-match saving retains recording.
#pragma once
#include "frame_sync/replay_system.hpp"
// 2026-09-13: product replay records cadence and team ownership.
// #include "frame_sync/replay_directory.hpp"
#include "frame_sync/replay_directory.hpp"
#include "frame_sync/native_match_replay.hpp"
#include <cstdio>
namespace frame_sync {
// 2026-09-13: preserve legacy API while product callers supply their verified descriptor.
// inline bool SaveNativeReplay(ReplayRecorder& recorder, uint32_t seed, bool finish) {
inline bool SaveNativeReplay(ReplayRecorder& recorder, uint32_t seed, bool finish,
                             const NativeMatchContract* contract = nullptr) {
  if (recorder.GetFrameCount() == 0) return true;
  if (finish) recorder.StopRecording();
  const std::string path = "replay_" + std::to_string(seed) + ".bin";
  try {
    // 2026-09-13: header and payload share the same atomic file transaction.
    // const auto result = SaveManagedReplayFile(recorder, path);
    const auto result = contract ? SaveManagedReplayFile(NativeReplayView(recorder,*contract), path)
                                 : SaveManagedReplayFile(recorder, path);
    if (!result) {
      fprintf(stderr, "Replay save failed: %s (stage=%s, committed=%d, error=%s, cleanup=%s)\n",
              path.c_str(), result.stage, result.committed ? 1 : 0,
              result.error.message().c_str(), result.cleanup_error.message().c_str());
      if (result.cleanup_error)
        fprintf(stderr, "Replay temporary cleanup requires retry: %s\n", result.temporary_path.c_str());
      return false;
    }
    fprintf(stderr, "Replay saved: %s (%zu frames, %zu bytes)\n",
            path.c_str(), recorder.GetFrameCount(), result.bytes);
    return true;
  } catch (const std::exception& error) {
    fprintf(stderr, "Replay save failed: %s (%s)\n", path.c_str(), error.what());
    return false;
  }
}
}  // namespace frame_sync
