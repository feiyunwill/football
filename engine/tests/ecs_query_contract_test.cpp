// 2026-09-09: heterogeneous queries, ordering and structural-mutation contracts.
#include "ecs/query.hpp"
#include "ecs/system_graph.hpp"
#include <gtest/gtest.h>
#include <utility>

namespace {
struct Position { int value = 0; };
struct Velocity { int value = 0; };
struct Health { int value = 0; };

TEST(QueryContract, ConstEmptyWorldReturnsNull) {
  const blunted::World world;
  EXPECT_EQ(world.GetComponent<Position>(1), nullptr);
  EXPECT_EQ(world.GetPool<Position>(), nullptr);
}

TEST(QueryContract, ThreeDistinctComponentsUseStableEntityOrder) {
  blunted::World world;
  for (auto e : {9, 2, 7, 4}) world.AddComponent(e, Position{e});
  for (auto e : {7, 9, 4}) world.AddComponent(e, Velocity{e * 2});
  for (auto e : {9, 4}) world.AddComponent(e, Health{e * 3});
  std::vector<blunted::Entity> visited;
  world.ForEach<Position, Velocity, Health>([&](auto e, auto& p, auto& v, auto& h) {
    visited.push_back(e);
    EXPECT_EQ(p.value * 2, v.value);
    EXPECT_EQ(p.value * 3, h.value);
  });
  EXPECT_EQ(visited, (std::vector<blunted::Entity>{4, 9}));
  auto result = blunted::Query<Position, Velocity, Health>(world).Execute();
  EXPECT_EQ(result.Entities(), visited);
  EXPECT_TRUE(result.Contains(4));
  EXPECT_FALSE(result.Contains(7));
}

TEST(QueryContract, ResultCanBeReusedAfterPoolDestructionAndRecreation) {
  blunted::World world;
  world.AddComponent(10, Position{1});
  world.AddComponent(10, Velocity{2});
  blunted::QueryResult<Position, Velocity> result(world);
  ASSERT_EQ(result.Size(), 1u);
  world.Clear();
  result.Execute(world);
  EXPECT_TRUE(result.Empty());
  world.AddComponent(3, Position{3});
  world.AddComponent(3, Velocity{6});
  result.Execute(world);
  EXPECT_EQ(result.Entities(), (std::vector<blunted::Entity>{3}));
}

TEST(QueryContract, SnapshotQuerySkipsDeletedFutureMatchesAndIgnoresNewMatches) {
  blunted::World world;
  for (auto e : {1, 2, 3}) {
    world.AddComponent(e, Position{e});
    world.AddComponent(e, Velocity{e});
  }
  std::vector<blunted::Entity> visited;
  blunted::Query<Position, Velocity>(world).ForEach([&](auto e, auto&, auto&) {
    visited.push_back(e);
    if (e == 1) {
      world.DestroyEntity(2);
      world.RemoveComponent<Velocity>(3);
      world.AddComponent(4, Position{4});
      world.AddComponent(4, Velocity{4});
    }
  });
  EXPECT_EQ(visited, (std::vector<blunted::Entity>{1}));
}

TEST(QueryContract, MutableWorldTraversalPreservesFirstPoolCandidateSnapshot) {
  blunted::World world;
  for (auto e : {1, 2, 3}) world.AddComponent(e, Position{e});
  world.AddComponent(1, Velocity{1});
  std::vector<blunted::Entity> visited;
  world.ForEach<Position, Velocity>([&](auto e, auto&, auto&) {
    visited.push_back(e);
    if (e == 1) {
      world.DestroyEntity(2);
      world.AddComponent(3, Velocity{3});
      world.AddComponent(4, Position{4});
      world.AddComponent(4, Velocity{4});
    }
  });
  EXPECT_EQ(visited, (std::vector<blunted::Entity>{1, 3}));
}

TEST(QueryContract, SmallestPoolCanHaveAnyComponentPosition) {
  blunted::World world;
  for (int e = 1; e <= 100; ++e) world.AddComponent(e, Position{e});
  for (int e = 1; e <= 50; ++e) world.AddComponent(e, Velocity{e});
  for (int e : {40, 4}) world.AddComponent(e, Health{e});
  const auto a = blunted::Query<Position, Velocity, Health>(world).Execute();
  const auto b = blunted::Query<Health, Position, Velocity>(world).Execute();
  const auto c = blunted::Query<Position, Health, Velocity>(world).Execute();
  EXPECT_EQ(a.Entities(), (std::vector<blunted::Entity>{4, 40}));
  EXPECT_EQ(a.Entities(), b.Entities());
  EXPECT_EQ(a.Entities(), c.Entities());
}

TEST(QueryContract, MissingTypesDoNotAllocatePoolsDuringResultConstruction) {
  blunted::World world;
  world.AddComponent(1, Position{1});
  const auto result = blunted::Query<Position, Velocity>(world).Execute();
  EXPECT_TRUE(result.Empty());
  EXPECT_EQ(std::as_const(world).GetPool<Velocity>(), nullptr);
}

TEST(QueryContract, ThreeComponentTraversalSurvivesRemovalAndPoolGrowth) {
  blunted::World world;
  for (auto e : {1, 2, 3}) {
    world.AddComponent(e, Position{e});
    world.AddComponent(e, Velocity{e});
    world.AddComponent(e, Health{e});
  }
  std::vector<blunted::Entity> visited;
  world.ForEach<Position, Velocity, Health>([&](auto e, auto&, auto&, auto&) {
    visited.push_back(e);
    if (e == 1) {
      world.DestroyEntity(2);
      for (int fresh = 4; fresh < 100; ++fresh) {
        world.AddComponent(fresh, Position{fresh});
        world.AddComponent(fresh, Velocity{fresh});
        world.AddComponent(fresh, Health{fresh});
      }
    }
  });
  EXPECT_EQ(visited, (std::vector<blunted::Entity>{1, 3}));
}
}  // namespace
