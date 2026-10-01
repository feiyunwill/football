// Copyright 2026 Google LLC & Contributors
// Preserve the replay API while sharing checked atomic file publication.
#ifndef GFOOTBALL_FRAME_SYNC_REPLAY_FILE_HPP
#define GFOOTBALL_FRAME_SYNC_REPLAY_FILE_HPP
#include "frame_sync/replay_system.hpp"
#include "frame_sync/atomic_file.hpp"
namespace frame_sync {
using ReplayFileResult = AtomicFileResult;
namespace replay_file_detail {
using atomic_file_detail::LastError;
using atomic_file_detail::FileOperations;
template<class Operations>
using TemporaryFile = atomic_file_detail::TemporaryFile<Operations>;
template<class Recorder> bool HasReplayContent(const Recorder& recorder) {
  if constexpr (requires { recorder.HasReplayContent(); })
    return static_cast<bool>(recorder.HasReplayContent());
  else return recorder.GetFrameCount() != 0;
}
template<class Operations, class Recorder>
ReplayFileResult Save(const Recorder& recorder, const std::filesystem::path& path,
                      Operations& operations) {
  return atomic_file_detail::Save(recorder, path, operations,
                                 HasReplayContent(recorder), ".football-replay");
}
} // namespace replay_file_detail
inline ReplayFileResult SaveReplayFile(const ReplayRecorder& recorder,
                                      const std::filesystem::path& path) {
  replay_file_detail::FileOperations operations;
  return replay_file_detail::Save(recorder, path, operations);
}
} // namespace frame_sync
#endif
