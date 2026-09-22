// Copyright 2026 Google LLC & Contributors
// Regressions found while reviewing the milestone implementations (2026-09-09).
#include "ecs/query.hpp"
#include "ecs/system_graph.hpp"
#include "frame_sync/state_snapshot_codec.hpp"
#include <gtest/gtest.h>
#include <string>

TEST(MilestoneEcs, MutationHistoryDoesNotChangeIterationOrder) {
  blunted::ComponentPool<std::string> pool;
  pool.Set(4, "four");
  pool.Set(1, "one");
  pool.Set(3, "three");
  pool.Set(2, "two");
  EXPECT_EQ(pool.Entities(), (std::vector<blunted::Entity>{1, 2, 3, 4}));
  pool.Remove(1);
  EXPECT_EQ(pool.Entities(), (std::vector<blunted::Entity>{2, 3, 4}));
  pool.SortIfNeeded();
  pool.SortIfNeeded();
  EXPECT_EQ(*pool.Get(2), "two");
  EXPECT_EQ(*pool.Get(3), "three");
  EXPECT_EQ(*pool.Get(4), "four");
  const auto span = pool.EntitiesSpan();
  EXPECT_TRUE(std::is_sorted(span.begin(), span.end()));
}

TEST(MilestoneEcs, QueriesStayOrderedAfterDestruction) {
  blunted::World world;
  auto a = world.CreateEntity(), b = world.CreateEntity(), c = world.CreateEntity();
  world.AddComponent(c, 30);
  world.AddComponent(a, 10);
  world.AddComponent(b, 20);
  world.DestroyEntity(a);
  auto result = blunted::Query<int>(world).Execute();
  EXPECT_EQ(result.Entities(), (std::vector<blunted::Entity>{b, c}));
  EXPECT_TRUE(result.Contains(b));
  EXPECT_FALSE(result.Contains(a));
}

TEST(MilestoneEcs, SystemOrderIsStableAndDependenciesExecuteFirst) {
  blunted::SystemGraph graph;
  std::vector<std::string> calls;
  graph.Register("player", [&](void*) { calls.push_back("player"); return true; }, {"physics"});
  graph.Register("referee", [&](void*) { calls.push_back("referee"); return true; });
  graph.Register("physics", [&](void*) { calls.push_back("physics"); return true; });
  ASSERT_TRUE(graph.Execute(nullptr));
  EXPECT_EQ(calls, (std::vector<std::string>{"physics", "player", "referee"}));
  graph.Register("physics", [&](void*) { calls.push_back("physics"); return true; });
  calls.clear();
  ASSERT_TRUE(graph.Execute(nullptr));
  EXPECT_EQ(calls, (std::vector<std::string>{"physics", "player", "referee"}));
}

TEST(MilestoneEcs, MissingDependencyDoesNotRunPartialPipeline) {
  blunted::SystemGraph graph;
  int calls = 0;
  graph.Register("player", [&](void*) { ++calls; return true; }, {"missing"});
  EXPECT_FALSE(graph.Execute(nullptr));
  EXPECT_EQ(calls, 0);
}

TEST(MilestoneCodec, EveryByteIncludingRleMarkerRoundtrips) {
  std::string bytes;
  for (int i = 0; i < 256; ++i) bytes.push_back(static_cast<char>(i));
  bytes += std::string("\xff\x00\xff\xff\x01", 5);
  auto encoded = frame_sync::StateDeltaCodec::RLECompress(bytes);
  EXPECT_EQ(frame_sync::StateDeltaCodec::RLEDecompress(encoded, bytes.size()), bytes);
  frame_sync::StateDeltaCodec encoder, decoder;
  encoder.SetBaseline(std::string(bytes.size(), '\0'));
  decoder.SetBaseline(std::string(bytes.size(), '\0'));
  EXPECT_EQ(decoder.DecodeDelta(encoder.EncodeDelta(bytes)), bytes);
}

TEST(MilestoneCodec, RejectsMalformedRunsAndTrailingBytes) {
  using Codec = frame_sync::StateDeltaCodec;
  EXPECT_TRUE(Codec::RLEDecompress(std::string("\xff\x01", 2), 1).empty());
  EXPECT_TRUE(Codec::RLEDecompress(std::string("\xff\x00x", 3), 1).empty());
  EXPECT_TRUE(Codec::RLEDecompress(std::string("\xff\x03x", 3), 2).empty());
  EXPECT_TRUE(Codec::RLEDecompress("ab", 1).empty());
}

TEST(MilestoneCodec, ResizedSnapshotsAndStatsRoundtrip) {
  frame_sync::StateSnapshotCodec encoder, decoder;
  for (const std::string state : {std::string("abc"), std::string("longer"), std::string()}) {
    const auto encoded = encoder.Compress(state);
    EXPECT_EQ(decoder.Decompress(encoded), state);
    EXPECT_EQ(encoder.GetStats().last_original_size, state.size());
    EXPECT_EQ(encoder.GetStats().last_compressed_size, encoded.size());
  }
}

TEST(MilestoneCodec, RejectedSnapshotDoesNotChangeBaseline) {
  frame_sync::StateSnapshotCodec encoder, decoder;
  encoder.SetBaseline("AAAA");
  decoder.SetBaseline("AAAA");
  const auto encoded = encoder.Compress("BBBB");
  EXPECT_TRUE(decoder.Decompress(encoded, 9).empty());
  EXPECT_EQ(decoder.Decompress(encoded, 4), "BBBB");
  frame_sync::StateSnapshotCodec uninitialized;
  EXPECT_TRUE(uninitialized.Decompress(encoded).empty());
  EXPECT_FALSE(uninitialized.HasBaseline());
}
