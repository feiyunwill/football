// 2026-09-09: retained capacity and recovery at the real reconciliation API.
#include "frame_sync/frame_simulation.hpp"
#include "frame_sync/replay_system.hpp"
#include <gtest/gtest.h>
#include <array>
#include <cstring>
#include <limits>

namespace {
namespace fs = frame_sync;
const fs::SlotInput kMove{1, 0, 0};
const fs::SlotInput kOther{-1, 0, 0};
const std::array<uint16_t, 1> kLocal{0};

struct Engine {
  Engine() = default;
  ~Engine() = default;
  Engine(const Engine&) = delete;
  Engine& operator=(const Engine&) = delete;
  Engine(Engine&&) = delete;
  Engine& operator=(Engine&&) = delete;
  std::array<int64_t, 3> state{};
  size_t padding = sizeof(state);
  size_t corrected_padding = sizeof(state);
  size_t reserve = 0;
  bool fail_corrected_save = false;
  bool fail_step = false;
  fs::EngineCallbacks Callbacks() {
    fs::EngineCallbacks cb;
    cb.save_state = [&] {
      if (fail_corrected_save && state[1] < 0) throw std::runtime_error("save failed");
      fs::StateBlob bytes(std::max(padding, state[1] < 0 ? corrected_padding : sizeof(state)));
      bytes.reserve(reserve);
      std::memcpy(bytes.data(), state.data(), sizeof(state));
      return bytes;
    };
    cb.restore_state = [&](const auto& bytes) {
      std::memcpy(state.data(), bytes.data(), sizeof(state));
    };
    cb.step_frame = [&](std::span<const fs::SlotInput> inputs) {
      state[0] += static_cast<int>(inputs[0].dir_x);
      state[1] += static_cast<int>(inputs[1].dir_x);
      ++state[2];
      if (fail_step) throw std::runtime_error("step failed");
    };
    cb.compute_hash = [&] { return static_cast<uint64_t>(state[0] * 37 + state[1] * 11 + state[2]); };
    return cb;
  }
};
}  // namespace

TEST(SnapshotBudgetTest, RejectsBadCountsAndBudgetsBeforeAllocation) {
  for (int count : {-1, 0, 1025, std::numeric_limits<int>::max()})
    EXPECT_THROW(fs::ClientState{count}, std::invalid_argument);
  EXPECT_THROW((fs::SnapshotBudget{0, 100}), std::invalid_argument);
  EXPECT_THROW((fs::SnapshotBudget{100, 99}), std::invalid_argument);
  EXPECT_THROW((fs::SnapshotBudget{1, std::numeric_limits<size_t>::max()}), std::invalid_argument);
  Engine engine;
  for (size_t slots : {size_t{0}, size_t{23}, std::numeric_limits<size_t>::max()})
    EXPECT_THROW((fs::FrameSimulation{engine.Callbacks(), slots}), std::invalid_argument);
  fs::SnapshotBudget edited;
  edited.history_bytes = 0;
  EXPECT_THROW((fs::ClientState{4, edited}), std::invalid_argument);
}

TEST(SnapshotBudgetTest, RejectsCapacityAndFailedCallbacksWithoutChangingHistory) {
  fs::ClientState history(4, fs::SnapshotBudget{64, 96});
  history.save_snapshot(7, kMove, [] { return fs::StateBlob(24, 7); });
  EXPECT_THROW(history.save_snapshot(8, kMove, [] {
    fs::StateBlob bytes(1);
    bytes.reserve(65);
    return bytes;
  }), std::length_error);
  EXPECT_THROW(history.save_snapshot(7, kOther, []() -> fs::StateBlob {
    throw std::runtime_error("save failed");
  }), std::runtime_error);
  EXPECT_THROW(history.save_snapshot(8, kMove, {}), std::invalid_argument);
  EXPECT_EQ(history.buffer_size(), 1);
  EXPECT_EQ(history.buffered_bytes(), 24u);
  ASSERT_NE(history.get_snapshot(7), nullptr);
  EXPECT_EQ(history.get_snapshot(7)->state, fs::StateBlob(24, 7));
  EXPECT_EQ(history.get_snapshot(7)->predicted_input.dir_x, 1);
}

TEST(SnapshotBudgetTest, EnforcesBothCountAndBytesAndReleasesOnClear) {
  fs::ClientState history(4, fs::SnapshotBudget{32, 64});
  for (uint32_t frame = 0; frame < 1000; ++frame) {
    history.save_snapshot(frame, kMove, [] { return fs::StateBlob(24); });
    EXPECT_LE(history.buffer_size(), 2);
    EXPECT_LE(history.buffered_bytes(), 64u);
    ASSERT_NE(history.get_snapshot(frame), nullptr);
  }
  EXPECT_EQ(history.buffer_size(), 2);
  EXPECT_EQ(history.evict_count(), 998);
  EXPECT_EQ(history.get_snapshot(997), nullptr);
  history.clear();
  EXPECT_EQ(history.buffered_bytes(), 0u);
  EXPECT_EQ(history.get_snapshot(999), nullptr);
  fs::ClientState count_limited(2, fs::SnapshotBudget{32, 1024});
  for (uint32_t frame = 0; frame < 4; ++frame)
    count_limited.save_snapshot(frame, kMove, [] { return fs::StateBlob(1); });
  EXPECT_EQ(count_limited.buffer_size(), 2);
}

TEST(SnapshotBudgetTest, DuplicateReplacementKeepsItsIndexWhenOtherFramesAreEvicted) {
  fs::ClientState history(4, fs::SnapshotBudget{64, 64});
  for (uint32_t frame = 0; frame < 3; ++frame)
    history.save_snapshot(frame, kMove, [] { return fs::StateBlob(16); });
  history.save_snapshot(0, kOther, [] { return fs::StateBlob(48, 9); });
  ASSERT_EQ(history.buffer_size(), 2);
  EXPECT_EQ(history.buffered_bytes(), 64u);
  EXPECT_EQ(history.get_snapshot(1), nullptr);
  ASSERT_NE(history.get_snapshot(0), nullptr);
  EXPECT_EQ(history.get_snapshot(0)->state.size(), 48u);
  ASSERT_NE(history.get_snapshot(2), nullptr);
  EXPECT_EQ(history.get_snapshot(2)->frame_id, 2u);
  history.save_snapshot(0, kMove, [] { return fs::StateBlob(8); });
  EXPECT_EQ(history.buffered_bytes(), 24u);
  EXPECT_EQ(history.buffer_size(), 2);
}

TEST(SnapshotBudgetTest, CopiesAreIndependentAndMovedFromHistoriesRemainUsable) {
  fs::ClientState original(3, fs::SnapshotBudget{32, 64});
  original.save_snapshot(4, kMove, [] { return fs::StateBlob(24, 4); });
  original.record_server_hash(4, 123);
  fs::ClientState copy = original;
  fs::ClientState moved = std::move(original);
  EXPECT_EQ(original.buffer_size(), 0);
  EXPECT_EQ(original.buffered_bytes(), 0u);
  original.save_snapshot(5, kMove, [] { return fs::StateBlob(12); });
  EXPECT_EQ(copy.buffered_bytes(), 24u);
  EXPECT_EQ(moved.check_hash(4, 123), fs::ClientState::HashCheck::kMatch);
  moved = std::move(original);
  EXPECT_EQ(original.buffered_bytes(), 0u);
  EXPECT_EQ(moved.buffered_bytes(), 12u);
  moved = copy;
  copy.clear();
  EXPECT_EQ(moved.buffered_bytes(), 24u);
  EXPECT_EQ(moved.get_snapshot(4)->state, fs::StateBlob(24, 4));
}

TEST(FrameMemoryBudgetTest, RejectsOversizedCapacityBeforeSteppingAndCanResume) {
  Engine engine;
  engine.reserve = 129;
  fs::FrameSimulation simulation(engine.Callbacks(), 2, fs::SnapshotBudget{128, 256});
  const auto tick = simulation.Tick(kMove, kLocal);
  EXPECT_TRUE(tick.prediction_limited);
  EXPECT_FALSE(tick.predicted);
  EXPECT_EQ(engine.state[2], 0);
  EXPECT_EQ(simulation.history_bytes(), 0u);
  engine.reserve = 0;
  EXPECT_TRUE(simulation.Tick(kMove, kLocal).predicted);
  EXPECT_EQ(engine.state[2], 1);
}

TEST(FrameMemoryBudgetTest, AggregateBudgetFillsThenAuthorityFreesPredictionSpace) {
  Engine engine;
  fs::FrameSimulation simulation(engine.Callbacks(), 2, fs::SnapshotBudget{64, 100});
  EXPECT_TRUE(simulation.Tick(kMove, kLocal).predicted);
  EXPECT_TRUE(simulation.Tick(kMove, kLocal).predicted);
  EXPECT_TRUE(simulation.Tick(kMove, kLocal).prediction_limited);
  EXPECT_EQ(engine.state[2], 2);
  // 2026-09-09: SlotInput is explicitly packed to ten bytes in the protocol.
  // EXPECT_EQ(simulation.history_bytes(), 96u);
  EXPECT_EQ(simulation.history_bytes(), 88u);
  ASSERT_TRUE(simulation.QueueAuthority(0, {kMove, fs::SlotInput::Default()}));
  auto tick = simulation.Tick(kMove, kLocal);
  EXPECT_EQ(tick.confirmed.size(), 1u);
  EXPECT_TRUE(tick.predicted);
  EXPECT_EQ(engine.state[2], 3);
  // 2026-09-09: two snapshots each own 24 state bytes and 20 input bytes.
  // EXPECT_EQ(simulation.history_bytes(), 96u);
  EXPECT_EQ(simulation.history_bytes(), 88u);
  EXPECT_EQ(simulation.pending_bytes(), 0u);
}

TEST(FrameMemoryBudgetTest, RollbackGrowthRecoversTheCorrectedAuthorityAndDropsSpeculation) {
  for (size_t grown : {size_t{60}, size_t{200}}) {
    Engine engine;
    engine.corrected_padding = grown;
    fs::FrameSimulation simulation(engine.Callbacks(), 2, fs::SnapshotBudget{64, 192});
    for (int i = 0; i < 3; ++i) ASSERT_TRUE(simulation.Tick(kMove, kLocal).predicted);
    ASSERT_TRUE(simulation.QueueAuthority(0, {kMove, kOther}));
    auto tick = simulation.Tick(kMove, kLocal);
    EXPECT_TRUE(tick.rolled_back);
    EXPECT_TRUE(tick.prediction_limited);
    ASSERT_EQ(tick.confirmed.size(), 1u);
    EXPECT_EQ(engine.state, (std::array<int64_t, 3>{1, -1, 1}));
    EXPECT_EQ(simulation.next_frame(), 1u);
    EXPECT_EQ(simulation.confirmed_count(), 1u);
    EXPECT_EQ(simulation.history_bytes(), 0u);
    EXPECT_EQ(simulation.history_size(), 0u);
    EXPECT_EQ(simulation.VerifyHash(0, 27), true);
    ASSERT_TRUE(simulation.QueueAuthority(1, {kMove, kOther}));
    tick = simulation.Tick(kMove, kLocal, 0);
    EXPECT_EQ(engine.state, (std::array<int64_t, 3>{2, -2, 2}));
    EXPECT_EQ(tick.confirmed.size(), 1u);
  }
}

TEST(FrameMemoryBudgetTest, FailedSaveDuringResimulationLeavesRetryableAuthority) {
  Engine engine;
  fs::FrameSimulation simulation(engine.Callbacks(), 2, fs::SnapshotBudget{64, 256});
  for (int i = 0; i < 3; ++i) ASSERT_TRUE(simulation.Tick(kMove, kLocal).predicted);
  ASSERT_TRUE(simulation.QueueAuthority(0, {kMove, kOther}));
  engine.fail_corrected_save = true;
  EXPECT_THROW(simulation.Tick(kMove, kLocal), std::runtime_error);
  EXPECT_EQ(engine.state, (std::array<int64_t, 3>{1, -1, 1}));
  EXPECT_EQ(simulation.confirmed_count(), 0u);
  EXPECT_EQ(simulation.history_size(), 1u);
  // 2026-09-09: account for the packed ten-byte SlotInput.
  // EXPECT_EQ(simulation.history_bytes(), 48u);
  EXPECT_EQ(simulation.history_bytes(), 44u);
  engine.fail_corrected_save = false;
  auto tick = simulation.Tick(kMove, kLocal, 0);
  ASSERT_EQ(tick.confirmed.size(), 1u);
  EXPECT_EQ(simulation.confirmed_count(), 1u);
  EXPECT_EQ(simulation.history_bytes(), 0u);
  EXPECT_EQ(engine.state[2], 1);
}

TEST(FrameMemoryBudgetTest, FailedPredictionDoesNotCommitAFrameOrHistoryNode) {
  Engine engine;
  fs::FrameSimulation simulation(engine.Callbacks(), 2);
  engine.fail_step = true;
  EXPECT_THROW(simulation.Tick(kMove, kLocal), std::runtime_error);
  EXPECT_EQ(engine.state, (std::array<int64_t, 3>{0, 0, 0}));
  EXPECT_EQ(simulation.next_frame(), 0u);
  EXPECT_EQ(simulation.history_size(), 0u);
  EXPECT_EQ(simulation.history_bytes(), 0u);
  engine.fail_step = false;
  EXPECT_TRUE(simulation.Tick(kMove, kLocal).predicted);
}

TEST(FrameMemoryBudgetTest, AuthorityOwnsOnlyItsBoundedPayloadAndRecoversAfterDrain) {
  Engine engine;
  fs::FrameSimulation simulation(engine.Callbacks(), 2);
  std::vector<fs::SlotInput> large_capacity{kMove, kOther};
  large_capacity.reserve(4096);
  for (uint32_t frame = 0; frame < 1024; ++frame)
    ASSERT_TRUE(simulation.QueueAuthority(frame, large_capacity));
  EXPECT_EQ(simulation.pending_size(), 1024u);
  EXPECT_EQ(simulation.pending_bytes(), 1024 * 2 * sizeof(fs::SlotInput));
  EXPECT_FALSE(simulation.QueueAuthority(1024, large_capacity));
  EXPECT_TRUE(simulation.QueueAuthority(500, large_capacity));
  EXPECT_EQ(simulation.pending_size(), 1024u);
  const auto tick = simulation.Tick(kMove, kLocal, 0);
  EXPECT_EQ(tick.confirmed.size(), fs::kMaxCatchupFramesPerTick);
  EXPECT_LT(simulation.pending_bytes(), 1024 * 2 * sizeof(fs::SlotInput));
  EXPECT_TRUE(simulation.QueueAuthority(1024, large_capacity));
}

TEST(SnapshotBudgetTest, InvalidCorrectionCannotRestoreOrStep) {
  fs::ClientState history;
  history.save_snapshot(0, kMove, [] { return fs::StateBlob(24); });
  int called = 0;
  const auto restore = [&](const fs::StateBlob&) { ++called; };
  const auto step = [&](const fs::SlotInput&) { ++called; };
  EXPECT_THROW(history.rollback_to(0, fs::SlotInput{99, 0, 0}, restore, step),
               std::invalid_argument);
  EXPECT_THROW(history.rollback_to(0, kMove, {}, step), std::invalid_argument);
  EXPECT_THROW(history.restore_snapshot(0, {}), std::invalid_argument);
  EXPECT_EQ(called, 0);
  EXPECT_EQ(history.rollback_count(), 0);
}

TEST(ReplayMemoryBudgetTest, FrameCapPreservesSerializablePrefixAndRestartResetsMetadata) {
  fs::ReplayRecorder recorder(fs::ReplayBudget{2, 1024});
  recorder.StartRecording(42, "s", 2);
  ASSERT_TRUE(recorder.RecordFrame(0, 123, {kMove, kOther}));
  ASSERT_TRUE(recorder.RecordFrame(1, 456, {kOther, kMove}));
  EXPECT_FALSE(recorder.IsRecording());
  EXPECT_EQ(recorder.GetStopReason(), fs::ReplayStopReason::Capacity);
  EXPECT_FALSE(recorder.RecordFrame(2, 999, {kMove, kOther}));
  recorder.StopRecording();
  EXPECT_EQ(recorder.GetStopReason(), fs::ReplayStopReason::Capacity);
  fs::ReplayPlayer player;
  ASSERT_TRUE(player.LoadReplay(recorder.Serialize()));
  EXPECT_EQ(player.GetMetadata().final_state_hash, 456u);
  EXPECT_EQ(player.GetTotalFrames(), 2u);
  EXPECT_THROW(recorder.StartRecording(1, "bad", 23), std::invalid_argument);
  EXPECT_THROW(recorder.StartRecording(1, std::string(1025, 'x'), 2), std::length_error);
  EXPECT_EQ(recorder.GetFrameCount(), 2u);
  recorder.StartRecording(7, "new", 1);
  EXPECT_EQ(recorder.GetMetadata().total_frames, 0u);
  EXPECT_EQ(recorder.GetMetadata().final_state_hash, 0u);
  EXPECT_EQ(recorder.GetFrameCount(), 0u);
  EXPECT_TRUE(recorder.IsRecording());
}

TEST(ReplayMemoryBudgetTest, ByteCapRejectsWithoutLosingTheLastAcceptedFrame) {
  fs::ReplayRecorder recorder(fs::ReplayBudget{100, 128});
  recorder.StartRecording(42, "s", 2);
  ASSERT_TRUE(recorder.RecordFrame(0, 5, {kMove, kOther}));
  EXPECT_FALSE(recorder.RecordFrame(1, 6, {kMove, kOther}));
  EXPECT_EQ(recorder.GetStopReason(), fs::ReplayStopReason::Capacity);
  EXPECT_LE(recorder.GetRetainedBytes(), 128u);
  fs::ReplayPlayer player(fs::ReplayBudget{100, 128});
  ASSERT_TRUE(player.LoadReplay(recorder.Serialize()));
  EXPECT_EQ(player.GetTotalFrames(), 1u);
  EXPECT_EQ(player.GetMetadata().final_state_hash, 5u);
  recorder.Clear();
  EXPECT_EQ(recorder.GetFrameCount(), 0u);
  EXPECT_LE(recorder.GetRetainedBytes(), 32u);
  recorder.StartRecording(43, "again", 1);
  EXPECT_TRUE(recorder.RecordFrame(0, 7, {kMove}));
}

TEST(ReplayMemoryBudgetTest, LiveSerializationIsConsistentAndUsesExplicitLittleEndian) {
  fs::ReplayRecorder recorder;
  recorder.StartRecording(0x12345678, "x", 2);
  ASSERT_TRUE(recorder.RecordFrame(0, 0x0102030405060708ULL, {kMove, kOther}));
  const auto bytes = recorder.Serialize();
  ASSERT_GE(bytes.size(), 29u);
  EXPECT_EQ(static_cast<uint8_t>(bytes[0]), 0x78);
  EXPECT_EQ(static_cast<uint8_t>(bytes[3]), 0x12);
  EXPECT_EQ(static_cast<uint8_t>(bytes[9]), 1);  // total_frames, while still recording
  EXPECT_EQ(static_cast<uint8_t>(bytes[13]), 2); // input slots
  EXPECT_EQ(static_cast<uint8_t>(bytes[17]), 8); // low byte of final hash
  fs::ReplayPlayer player;
  ASSERT_TRUE(player.LoadReplay(bytes));
  ASSERT_TRUE(recorder.IsRecording());
  ASSERT_TRUE(player.GetFrameAt(0));
  EXPECT_EQ(player.GetFrameAt(0)->inputs, (std::vector<fs::SlotInput>{kMove, kOther}));
}

TEST(ReplayMemoryBudgetTest, MalformedLoadsPreservePreviousPositionAndPlayback) {
  fs::ReplayRecorder recorder;
  recorder.StartRecording(42, "x", 2);
  ASSERT_TRUE(recorder.RecordFrame(0, 123, {kMove, kOther}));
  ASSERT_TRUE(recorder.RecordFrame(1, 456, {kOther, kMove}));
  const auto valid = recorder.Serialize();
  fs::ReplayPlayer player;
  ASSERT_TRUE(player.LoadReplay(valid));
  player.Play();
  ASSERT_TRUE(player.Advance());
  auto unchanged = [&] {
    EXPECT_TRUE(player.IsPlaying());
    EXPECT_EQ(player.GetCurrentFrameIndex(), 1u);
    EXPECT_EQ(player.GetMetadata().seed, 42u);
    EXPECT_EQ(player.GetTotalFrames(), 2u);
    ASSERT_TRUE(player.GetCurrentFrame());
    EXPECT_EQ(player.GetCurrentFrame()->state_hash, 456u);
  };
  for (size_t length = 0; length < valid.size(); ++length) {
    EXPECT_FALSE(player.LoadReplay(valid.substr(0, length))) << length;
    unchanged();
  }
  for (size_t offset : {size_t{4}, size_t{9}, size_t{13}, size_t{25}}) {
    auto damaged = valid;
    damaged.replace(offset, 4, 4, '\xff');  // huge scene/count/slots before allocation
    EXPECT_FALSE(player.LoadReplay(damaged)) << offset;
    unchanged();
  }
  EXPECT_FALSE(player.LoadReplay(valid + "trailing"));
  unchanged();
  auto bad_hash = valid;
  bad_hash[17] ^= 1;
  EXPECT_FALSE(player.LoadReplay(bad_hash));
  unchanged();
  auto bad_direction = valid;
  // First input starts after the 29-byte header and 12-byte frame prefix.
  bad_direction.replace(41, 4, "\0\0\xc0\x7f", 4);
  EXPECT_FALSE(player.LoadReplay(bad_direction));
  unchanged();
}

TEST(ReplayMemoryBudgetTest, BadInputsStopRecordingWithoutAppending) {
  fs::ReplayRecorder recorder;
  recorder.StartRecording(42, "x", 2);
  ASSERT_TRUE(recorder.RecordFrame(0, 1, {kMove, kOther}));
  EXPECT_FALSE(recorder.RecordFrame(1, 2, {kMove}));
  EXPECT_EQ(recorder.GetFrameCount(), 1u);
  EXPECT_EQ(recorder.GetStopReason(), fs::ReplayStopReason::InvalidInput);
  recorder.StartRecording(42, "x", 1);
  EXPECT_FALSE(recorder.RecordFrame(0, 0, {fs::SlotInput{99, 0, 0}}));
  EXPECT_EQ(recorder.GetFrameCount(), 0u);
  recorder.StartRecording(42, "x", 1);
  ASSERT_TRUE(recorder.RecordFrame(0, 1, {kMove}));
  EXPECT_FALSE(recorder.RecordFrame(0, 2, {kOther}));
}

TEST(ReplayMemoryBudgetTest, CopiesMovesAndCapacityRecoveryPreserveIndependentData) {
  fs::ReplayRecorder recorder;
  recorder.StartRecording(42, "x", 1);
  recorder.RecordFrame(0, 99, {kMove});
  fs::ReplayRecorder copy = recorder;
  fs::ReplayRecorder moved = std::move(recorder);
  EXPECT_EQ(recorder.GetFrameCount(), 0u);
  recorder.StartRecording(7, "y", 1);
  recorder.RecordFrame(0, 88, {kOther});
  EXPECT_EQ(copy.GetMetadata().final_state_hash, 99u);
  EXPECT_EQ(moved.GetMetadata().final_state_hash, 99u);
  fs::ReplayPlayer first;
  ASSERT_TRUE(first.LoadReplay(moved.Serialize()));
  first.Play();
  fs::ReplayPlayer second = std::move(first);
  EXPECT_FALSE(first.IsLoaded());
  EXPECT_TRUE(second.IsPlaying());
  ASSERT_TRUE(first.LoadReplay(recorder.Serialize()));
  EXPECT_EQ(first.GetMetadata().seed, 7u);
  EXPECT_EQ(second.GetMetadata().seed, 42u);
}

TEST(ReplayMemoryBudgetTest, FullDefaultBudgetSupportsAFullMatchAndThenStops) {
  fs::ReplayRecorder recorder;
  recorder.StartRecording(42, "full_22_slots", 22);
  std::vector<fs::SlotInput> inputs(22, kMove);
  inputs.reserve(4096);  // excess caller capacity must not be retained per frame
  for (uint32_t frame = 0; frame < 100000; ++frame) {
    ASSERT_TRUE(recorder.RecordFrame(frame, frame, inputs));
    ASSERT_LE(recorder.GetRetainedBytes(), 32u * 1024 * 1024);
  }
  EXPECT_FALSE(recorder.IsRecording());
  EXPECT_EQ(recorder.GetFrameCount(), 100000u);
  EXPECT_FALSE(recorder.RecordFrame(100000, 100000, inputs));
  fs::ReplayPlayer player;
  ASSERT_TRUE(player.LoadReplay(recorder.Serialize()));
  EXPECT_EQ(player.GetTotalFrames(), 100000u);
  EXPECT_LE(player.GetRetainedBytes(), 32u * 1024 * 1024);
}
// 2026-09-09: appending partial messages cannot grow retained receive capacity.
TEST(ReceiveMemoryBudget, FillRejectPreservesBytesThenConsumeAndRecover) {
  std::vector<uint8_t> buffer;
  const std::array<uint8_t, 5> input{1, 2, 3, 4, 5};
  EXPECT_TRUE(frame_sync::AppendBoundedBytes(buffer, input.data(), 5, 8));
  EXPECT_EQ(buffer.capacity(), 8u);
  const auto before = buffer;
  EXPECT_FALSE(frame_sync::AppendBoundedBytes(buffer, input.data(), 5, 8));
  EXPECT_EQ(buffer, before);
  buffer.erase(buffer.begin(), buffer.begin() + 2);
  EXPECT_TRUE(frame_sync::AppendBoundedBytes(buffer, input.data(), 5, 8));
  EXPECT_EQ(buffer.size(), 8u);
  EXPECT_EQ(buffer.capacity(), 8u);
  buffer.clear();
  EXPECT_TRUE(frame_sync::AppendBoundedBytes(buffer, input.data(), 5, 8));
}

TEST(ReceiveMemoryBudget, BadLengthsAndExcessCallerCapacityAreRejected) {
  std::vector<uint8_t> buffer;
  uint8_t value = 1;
  EXPECT_FALSE(frame_sync::AppendBoundedBytes(buffer, nullptr, 1, 8));
  EXPECT_FALSE(frame_sync::AppendBoundedBytes(buffer, &value, size_t(-1), 8));
  EXPECT_FALSE(frame_sync::AppendBoundedBytes(buffer, &value, 1, 0));
  EXPECT_FALSE(frame_sync::AppendBoundedBytes(buffer, &value, 1, size_t(-1)));
  EXPECT_EQ(buffer.capacity(), 0u);
  EXPECT_TRUE(frame_sync::AppendBoundedBytes(buffer, nullptr, 0, 8));
  buffer.reserve(16);
  EXPECT_FALSE(frame_sync::AppendBoundedBytes(buffer, &value, 1, 8));
  EXPECT_TRUE(buffer.empty());
}
