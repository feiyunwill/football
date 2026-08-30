// Copyright 2026 Google LLC & Contributors
// ECS 单元测试：验证 World / ComponentPool / Entity 的基本操作。

#include "ecs/world.hpp"
#include "ecs/entity.hpp"
// 注意：transform.hpp 依赖 Vector3/Quaternion（需要链接引擎 math 库），
// 此处仅测试 World/Entity/ComponentPool 的纯模板逻辑，不引入 transform。

#include <gtest/gtest.h>

using namespace blunted;

// ===== 测试用组件 =====

struct Position {
  float x = 0.f;
  float y = 0.f;
};

struct Velocity {
  float dx = 0.f;
  float dy = 0.f;
};

struct Health {
  int hp = 100;
};

// ===== Entity =====

TEST(EntityTest, NullEntityIsZero) {
  EXPECT_EQ(kNullEntity, 0u);
}

TEST(EntityTest, EntityTypeIsUint64) {
  Entity e = 42;
  EXPECT_EQ(e, 42u);
}

// ===== World 基本操作 =====

TEST(WorldTest, CreateEntity) {
  World w;
  Entity e = w.CreateEntity();
  EXPECT_NE(e, kNullEntity);
}

TEST(WorldTest, CreateMultipleEntities) {
  World w;
  Entity e1 = w.CreateEntity();
  Entity e2 = w.CreateEntity();
  Entity e3 = w.CreateEntity();
  EXPECT_NE(e1, e2);
  EXPECT_NE(e2, e3);
  EXPECT_NE(e1, e3);
}

TEST(WorldTest, EntityIdsAreMonotonic) {
  World w;
  Entity prev = kNullEntity;
  for (int i = 0; i < 100; ++i) {
    Entity e = w.CreateEntity();
    EXPECT_GT(e, prev);
    prev = e;
  }
}

// ===== Component 操作 =====

TEST(WorldTest, AddAndGetComponent) {
  World w;
  Entity e = w.CreateEntity();
  Position pos{1.0f, 2.0f};
  w.AddComponent(e, pos);

  Position* got = w.GetComponent<Position>(e);
  ASSERT_NE(got, nullptr);
  EXPECT_FLOAT_EQ(got->x, 1.0f);
  EXPECT_FLOAT_EQ(got->y, 2.0f);
}

TEST(WorldTest, GetComponentReturnsNullForMissing) {
  World w;
  Entity e = w.CreateEntity();
  EXPECT_EQ(w.GetComponent<Position>(e), nullptr);
}

TEST(WorldTest, HasComponent) {
  World w;
  Entity e = w.CreateEntity();
  EXPECT_FALSE(w.HasComponent<Position>(e));
  w.AddComponent(e, Position{});
  EXPECT_TRUE(w.HasComponent<Position>(e));
}

TEST(WorldTest, RemoveComponent) {
  World w;
  Entity e = w.CreateEntity();
  w.AddComponent(e, Position{1.f, 2.f});
  EXPECT_TRUE(w.HasComponent<Position>(e));
  w.RemoveComponent<Position>(e);
  EXPECT_FALSE(w.HasComponent<Position>(e));
}

TEST(WorldTest, OverwriteComponent) {
  World w;
  Entity e = w.CreateEntity();
  w.AddComponent(e, Position{1.f, 2.f});
  w.AddComponent(e, Position{3.f, 4.f});
  Position* got = w.GetComponent<Position>(e);
  ASSERT_NE(got, nullptr);
  EXPECT_FLOAT_EQ(got->x, 3.f);
  EXPECT_FLOAT_EQ(got->y, 4.f);
}

// ===== Multiple Components =====

TEST(WorldTest, MultipleComponentsOnSameEntity) {
  World w;
  Entity e = w.CreateEntity();
  w.AddComponent(e, Position{1.f, 2.f});
  w.AddComponent(e, Velocity{0.1f, 0.2f});
  w.AddComponent(e, Health{75});

  Position* pos = w.GetComponent<Position>(e);
  Velocity* vel = w.GetComponent<Velocity>(e);
  Health* hp = w.GetComponent<Health>(e);

  ASSERT_NE(pos, nullptr);
  ASSERT_NE(vel, nullptr);
  ASSERT_NE(hp, nullptr);

  EXPECT_FLOAT_EQ(pos->x, 1.f);
  EXPECT_FLOAT_EQ(vel->dx, 0.1f);
  EXPECT_EQ(hp->hp, 75);
}

// ===== ForEach =====

TEST(WorldTest, ForEachSingleComponent) {
  World w;
  Entity e1 = w.CreateEntity();
  Entity e2 = w.CreateEntity();
  Entity e3 = w.CreateEntity();
  w.AddComponent(e1, Position{1.f, 0.f});
  w.AddComponent(e2, Position{2.f, 0.f});
  // e3 没有 Position

  int count = 0;
  w.ForEach<Position>([&](Entity, Position&) { count++; });
  EXPECT_EQ(count, 2);
}

TEST(WorldTest, ForEachTwoComponents) {
  World w;
  Entity e1 = w.CreateEntity();
  Entity e2 = w.CreateEntity();
  Entity e3 = w.CreateEntity();
  w.AddComponent(e1, Position{1.f, 0.f});
  w.AddComponent(e1, Velocity{0.1f, 0.f});
  w.AddComponent(e2, Position{2.f, 0.f});
  // e2 没有 Velocity
  w.AddComponent(e3, Velocity{0.3f, 0.f});
  // e3 没有 Position

  int count = 0;
  w.ForEach<Position, Velocity>([&](Entity, Position&, Velocity&) { count++; });
  EXPECT_EQ(count, 1);  // 只有 e1 同时有两个组件
}

TEST(WorldTest, ForEachModifiesData) {
  World w;
  Entity e = w.CreateEntity();
  w.AddComponent(e, Position{0.f, 0.f});

  w.ForEach<Position>([](Entity, Position& p) {
    p.x = 42.f;
    p.y = 99.f;
  });

  Position* got = w.GetComponent<Position>(e);
  ASSERT_NE(got, nullptr);
  EXPECT_FLOAT_EQ(got->x, 42.f);
  EXPECT_FLOAT_EQ(got->y, 99.f);
}

// ===== DestroyEntity =====

TEST(WorldTest, DestroyEntityRemovesAllComponents) {
  World w;
  Entity e = w.CreateEntity();
  w.AddComponent(e, Position{1.f, 2.f});
  w.AddComponent(e, Velocity{0.1f, 0.2f});

  w.DestroyEntity(e);

  EXPECT_FALSE(w.HasComponent<Position>(e));
  EXPECT_FALSE(w.HasComponent<Velocity>(e));
}

// ===== Clear =====

TEST(WorldTest, ClearRemovesAll) {
  World w;
  for (int i = 0; i < 50; ++i) {
    Entity e = w.CreateEntity();
    w.AddComponent(e, Position{float(i), 0.f});
  }

  w.Clear();

  // 新建实体 ID 应从头开始（next_id_ 重置为 kNullEntity）
  Entity e = w.CreateEntity();
  EXPECT_EQ(e, kNullEntity + 1);
}



// ===== 确定性遍历 =====

TEST(WorldTest, ForEachDeterministicOrder) {
  World w;
  // 创建 10 个实体，ID 单调递增
  std::vector<Entity> entities;
  for (int i = 0; i < 10; ++i) {
    Entity e = w.CreateEntity();
    w.AddComponent(e, Position{float(i), 0.f});
    entities.push_back(e);
  }

  // ForEach 遍历顺序应与 ID 排序一致（确定性）
  std::vector<Entity> traversal_order;
  w.ForEach<Position>([&](Entity e, Position&) {
    traversal_order.push_back(e);
  });

  // 验证顺序
  ASSERT_EQ(traversal_order.size(), entities.size());
  for (size_t i = 0; i < entities.size(); ++i) {
    EXPECT_EQ(traversal_order[i], entities[i])
        << "Traversal order mismatch at index " << i;
  }
}

// ===== Move 语义 =====

TEST(WorldTest, MoveConstruction) {
  World w1;
  Entity e = w1.CreateEntity();
  w1.AddComponent(e, Position{1.f, 2.f});

  World w2 = std::move(w1);
  Position* got = w2.GetComponent<Position>(e);
  ASSERT_NE(got, nullptr);
  EXPECT_FLOAT_EQ(got->x, 1.f);
}

// ===== TeamStateComponent 测试 =====

// 2026-08-30 P2-Phase2：TeamStateComponent 单元测试
// 注意：TeamStateComponent 定义在 onthepitch/ecs_components.hpp，
// 这里仅测试其作为纯数据结构的正确性（不依赖 Match/Team 运行时）。

struct TeamStateComponent {
  int team_id = 0;
  int side = -1;
  int static_side = -1;
  bool mirrored = false;
  float ai_difficulty = 0.0f;
  int player_count = 0;
  int human_gamer_count = 0;
  int active_player_count = 0;
  int last_touch_player_id = -1;
  int designated_possession_player_id = -1;
};

TEST(TeamStateComponentTest, DefaultConstruction) {
  TeamStateComponent tsc;
  EXPECT_EQ(tsc.team_id, 0);
  EXPECT_EQ(tsc.side, -1);
  EXPECT_EQ(tsc.static_side, -1);
  EXPECT_FALSE(tsc.mirrored);
  EXPECT_FLOAT_EQ(tsc.ai_difficulty, 0.0f);
  EXPECT_EQ(tsc.player_count, 0);
  EXPECT_EQ(tsc.human_gamer_count, 0);
  EXPECT_EQ(tsc.active_player_count, 0);
  EXPECT_EQ(tsc.last_touch_player_id, -1);
  EXPECT_EQ(tsc.designated_possession_player_id, -1);
}

TEST(TeamStateComponentTest, EcsIntegration) {
  World w;
  Entity e = w.CreateEntity();
  TeamStateComponent tsc;
  tsc.team_id = 1;
  tsc.side = 1;
  tsc.static_side = 1;
  tsc.player_count = 11;
  tsc.active_player_count = 11;
  tsc.ai_difficulty = 0.75f;
  w.AddComponent(e, tsc);

  TeamStateComponent* got = w.GetComponent<TeamStateComponent>(e);
  ASSERT_NE(got, nullptr);
  EXPECT_EQ(got->team_id, 1);
  EXPECT_EQ(got->side, 1);
  EXPECT_EQ(got->player_count, 11);
  EXPECT_FLOAT_EQ(got->ai_difficulty, 0.75f);
}

TEST(TeamStateComponentTest, MultipleTeams) {
  World w;
  Entity e0 = w.CreateEntity();
  Entity e1 = w.CreateEntity();

  TeamStateComponent left;
  left.team_id = 0;
  left.side = -1;
  left.static_side = -1;
  left.player_count = 11;

  TeamStateComponent right;
  right.team_id = 1;
  right.side = 1;
  right.static_side = 1;
  right.player_count = 11;

  w.AddComponent(e0, left);
  w.AddComponent(e1, right);

  // Verify both teams coexist
  TeamStateComponent* t0 = w.GetComponent<TeamStateComponent>(e0);
  TeamStateComponent* t1 = w.GetComponent<TeamStateComponent>(e1);
  ASSERT_NE(t0, nullptr);
  ASSERT_NE(t1, nullptr);
  EXPECT_EQ(t0->team_id, 0);
  EXPECT_EQ(t1->team_id, 1);
  EXPECT_EQ(t0->side, -1);
  EXPECT_EQ(t1->side, 1);
}

TEST(TeamStateComponentTest, ForEachTeamState) {
  World w;
  for (int i = 0; i < 2; ++i) {
    Entity e = w.CreateEntity();
    TeamStateComponent tsc;
    tsc.team_id = i;
    tsc.player_count = 11;
    w.AddComponent(e, tsc);
  }

  int count = 0;
  w.ForEach<TeamStateComponent>([&](Entity, TeamStateComponent& tsc) {
    EXPECT_EQ(tsc.player_count, 11);
    count++;
  });
  EXPECT_EQ(count, 2);
}

// ===== RefereeStateComponent 测试 =====

// 2026-08-30 P2-Phase2：RefereeStateComponent 单元测试
// 注意：RefereeStateComponent 定义在 onthepitch/ecs_components.hpp，
// 这里仅测试其作为纯数据结构的正确性（不依赖 Match/Referee 运行时）。

struct RefereeStateComponent {
  bool buffer_active = false;
  int desired_set_piece = 0;
  int buffer_team_id = 0;
  unsigned long stop_time = 0;
  unsigned long prepare_time = 0;
  unsigned long start_time = 0;
  bool end_phase = false;
  int after_set_piece_relax_time_ms = 0;
  int offside_player_count = 0;
  int foul_type = 0;
  bool foul_advantage = false;
  unsigned long foul_time = 0;
  bool foul_processed = false;
};

TEST(RefereeStateComponentTest, DefaultConstruction) {
  RefereeStateComponent rsc;
  EXPECT_FALSE(rsc.buffer_active);
  EXPECT_EQ(rsc.desired_set_piece, 0);
  EXPECT_EQ(rsc.buffer_team_id, 0);
  EXPECT_EQ(rsc.stop_time, 0UL);
  EXPECT_EQ(rsc.prepare_time, 0UL);
  EXPECT_EQ(rsc.start_time, 0UL);
  EXPECT_FALSE(rsc.end_phase);
  EXPECT_EQ(rsc.after_set_piece_relax_time_ms, 0);
  EXPECT_EQ(rsc.offside_player_count, 0);
  EXPECT_EQ(rsc.foul_type, 0);
  EXPECT_FALSE(rsc.foul_advantage);
  EXPECT_EQ(rsc.foul_time, 0UL);
  EXPECT_FALSE(rsc.foul_processed);
}

TEST(RefereeStateComponentTest, EcsIntegration) {
  World w;
  Entity e = w.CreateEntity();
  RefereeStateComponent rsc;
  rsc.buffer_active = true;
  rsc.desired_set_piece = 3;  // e_GameMode_KickOff
  rsc.buffer_team_id = 0;
  rsc.start_time = 2000;
  rsc.end_phase = true;
  w.AddComponent(e, rsc);

  RefereeStateComponent* got = w.GetComponent<RefereeStateComponent>(e);
  ASSERT_NE(got, nullptr);
  EXPECT_TRUE(got->buffer_active);
  EXPECT_EQ(got->desired_set_piece, 3);
  EXPECT_EQ(got->start_time, 2000UL);
  EXPECT_TRUE(got->end_phase);
}

TEST(RefereeStateComponentTest, FoulState) {
  World w;
  Entity e = w.CreateEntity();
  RefereeStateComponent rsc;
  rsc.foul_type = 2;  // yellow card
  rsc.foul_advantage = true;
  rsc.foul_time = 15000;
  rsc.foul_processed = false;
  w.AddComponent(e, rsc);

  RefereeStateComponent* got = w.GetComponent<RefereeStateComponent>(e);
  ASSERT_NE(got, nullptr);
  EXPECT_EQ(got->foul_type, 2);
  EXPECT_TRUE(got->foul_advantage);
  EXPECT_EQ(got->foul_time, 15000UL);
  EXPECT_FALSE(got->foul_processed);
}

// ===== MatchStateComponent 测试 =====

// 2026-08-30 P2-Phase2：MatchStateComponent 单元测试
// 注意：MatchStateComponent 定义在 onthepitch/ecs_components.hpp，
// 这里仅测试其作为纯数据结构的正确性（不依赖 Match 运行时）。

struct MatchStateComponent {
  unsigned long match_time_ms = 0;
  unsigned long actual_time_ms = 0;
  bool in_play = false;
  bool in_set_piece = false;
  bool goal_scored = false;
  bool ball_is_in_goal = false;
  int match_phase = 0;
  int last_touch_team_id = -1;
  int last_touch_team_ids[8] = {};
  int best_possession_team_id = -1;
  int designated_possession_player_id = -1;
  int ball_retainer_player_id = -1;
  int first_team = 0;
  int second_team = 1;
};

TEST(MatchStateComponentTest, DefaultConstruction) {
  MatchStateComponent msc;
  EXPECT_EQ(msc.match_time_ms, 0UL);
  EXPECT_EQ(msc.actual_time_ms, 0UL);
  EXPECT_FALSE(msc.in_play);
  EXPECT_FALSE(msc.in_set_piece);
  EXPECT_FALSE(msc.goal_scored);
  EXPECT_FALSE(msc.ball_is_in_goal);
  EXPECT_EQ(msc.match_phase, 0);
  EXPECT_EQ(msc.last_touch_team_id, -1);
  for (int i = 0; i < 8; ++i) {
    EXPECT_EQ(msc.last_touch_team_ids[i], 0);
  }
  EXPECT_EQ(msc.best_possession_team_id, -1);
  EXPECT_EQ(msc.designated_possession_player_id, -1);
  EXPECT_EQ(msc.ball_retainer_player_id, -1);
  EXPECT_EQ(msc.first_team, 0);
  EXPECT_EQ(msc.second_team, 1);
}

TEST(MatchStateComponentTest, EcsIntegration) {
  World w;
  Entity e = w.CreateEntity();
  MatchStateComponent msc;
  msc.match_time_ms = 45000;
  msc.actual_time_ms = 50000;
  msc.in_play = true;
  msc.match_phase = 1;  // 2nd half
  msc.first_team = 0;
  msc.second_team = 1;
  w.AddComponent(e, msc);

  MatchStateComponent* got = w.GetComponent<MatchStateComponent>(e);
  ASSERT_NE(got, nullptr);
  EXPECT_EQ(got->match_time_ms, 45000UL);
  EXPECT_EQ(got->actual_time_ms, 50000UL);
  EXPECT_TRUE(got->in_play);
  EXPECT_EQ(got->match_phase, 1);
}

TEST(MatchStateComponentTest, GoalState) {
  World w;
  Entity e = w.CreateEntity();
  MatchStateComponent msc;
  msc.goal_scored = true;
  msc.ball_is_in_goal = true;
  msc.best_possession_team_id = 0;
  w.AddComponent(e, msc);

  MatchStateComponent* got = w.GetComponent<MatchStateComponent>(e);
  ASSERT_NE(got, nullptr);
  EXPECT_TRUE(got->goal_scored);
  EXPECT_TRUE(got->ball_is_in_goal);
  EXPECT_EQ(got->best_possession_team_id, 0);
}

// ===== 序列化往返测试 =====
// 2026-08-30 P2-Phase4：验证所有 ECS 组件可序列化/反序列化

#include "ecs/serializer.hpp"

TEST(SerializationTest, TeamStateRoundTrip) {
  World w;
  Entity e = w.CreateEntity();
  TeamStateComponent src;
  src.team_id = 1;
  src.side = 1;
  src.static_side = 1;
  src.mirrored = true;
  src.ai_difficulty = 0.85f;
  src.player_count = 11;
  src.human_gamer_count = 2;
  src.active_player_count = 10;
  src.last_touch_player_id = 7;
  src.designated_possession_player_id = 9;
  w.AddComponent(e, src);

  SerializedWorld data = WorldSerializer::Serialize<TeamStateComponent>(w);

  World w2;
  WorldSerializer::Deserialize<TeamStateComponent>(w2, data);

  TeamStateComponent* got = nullptr;
  w2.ForEach<TeamStateComponent>([&](Entity, TeamStateComponent& c) { got = &c; });
  ASSERT_NE(got, nullptr);
  EXPECT_EQ(got->team_id, 1);
  EXPECT_EQ(got->side, 1);
  EXPECT_EQ(got->static_side, 1);
  EXPECT_TRUE(got->mirrored);
  EXPECT_FLOAT_EQ(got->ai_difficulty, 0.85f);
  EXPECT_EQ(got->player_count, 11);
  EXPECT_EQ(got->human_gamer_count, 2);
  EXPECT_EQ(got->active_player_count, 10);
  EXPECT_EQ(got->last_touch_player_id, 7);
  EXPECT_EQ(got->designated_possession_player_id, 9);
}

TEST(SerializationTest, RefereeStateRoundTrip) {
  World w;
  Entity e = w.CreateEntity();
  RefereeStateComponent src;
  src.buffer_active = true;
  src.desired_set_piece = 3;
  src.buffer_team_id = 0;
  src.stop_time = 1000;
  src.prepare_time = 1200;
  src.start_time = 1400;
  src.end_phase = true;
  src.after_set_piece_relax_time_ms = 400;
  src.offside_player_count = 2;
  src.foul_type = 2;
  src.foul_advantage = true;
  src.foul_time = 15000;
  src.foul_processed = false;
  w.AddComponent(e, src);

  SerializedWorld data = WorldSerializer::Serialize<RefereeStateComponent>(w);

  World w2;
  WorldSerializer::Deserialize<RefereeStateComponent>(w2, data);

  RefereeStateComponent* got = nullptr;
  w2.ForEach<RefereeStateComponent>([&](Entity, RefereeStateComponent& c) { got = &c; });
  ASSERT_NE(got, nullptr);
  EXPECT_TRUE(got->buffer_active);
  EXPECT_EQ(got->desired_set_piece, 3);
  EXPECT_EQ(got->buffer_team_id, 0);
  EXPECT_EQ(got->stop_time, 1000UL);
  EXPECT_EQ(got->prepare_time, 1200UL);
  EXPECT_EQ(got->start_time, 1400UL);
  EXPECT_TRUE(got->end_phase);
  EXPECT_EQ(got->after_set_piece_relax_time_ms, 400);
  EXPECT_EQ(got->offside_player_count, 2);
  EXPECT_EQ(got->foul_type, 2);
  EXPECT_TRUE(got->foul_advantage);
  EXPECT_EQ(got->foul_time, 15000UL);
  EXPECT_FALSE(got->foul_processed);
}

TEST(SerializationTest, MatchStateRoundTrip) {
  World w;
  Entity e = w.CreateEntity();
  MatchStateComponent src;
  src.match_time_ms = 45000;
  src.actual_time_ms = 50000;
  src.in_play = true;
  src.in_set_piece = false;
  src.goal_scored = true;
  src.ball_is_in_goal = true;
  src.match_phase = 1;
  src.last_touch_team_id = 0;
  src.last_touch_team_ids[0] = 0;
  src.last_touch_team_ids[1] = 1;
  src.best_possession_team_id = 0;
  src.designated_possession_player_id = 5;
  src.ball_retainer_player_id = 5;
  src.first_team = 0;
  src.second_team = 1;
  w.AddComponent(e, src);

  SerializedWorld data = WorldSerializer::Serialize<MatchStateComponent>(w);

  World w2;
  WorldSerializer::Deserialize<MatchStateComponent>(w2, data);

  MatchStateComponent* got = nullptr;
  w2.ForEach<MatchStateComponent>([&](Entity, MatchStateComponent& c) { got = &c; });
  ASSERT_NE(got, nullptr);
  EXPECT_EQ(got->match_time_ms, 45000UL);
  EXPECT_EQ(got->actual_time_ms, 50000UL);
  EXPECT_TRUE(got->in_play);
  EXPECT_FALSE(got->in_set_piece);
  EXPECT_TRUE(got->goal_scored);
  EXPECT_TRUE(got->ball_is_in_goal);
  EXPECT_EQ(got->match_phase, 1);
  EXPECT_EQ(got->last_touch_team_id, 0);
  EXPECT_EQ(got->last_touch_team_ids[0], 0);
  EXPECT_EQ(got->last_touch_team_ids[1], 1);
  EXPECT_EQ(got->best_possession_team_id, 0);
  EXPECT_EQ(got->designated_possession_player_id, 5);
  EXPECT_EQ(got->ball_retainer_player_id, 5);
  EXPECT_EQ(got->first_team, 0);
  EXPECT_EQ(got->second_team, 1);
}

TEST(SerializationTest, AllComponentsRoundTrip) {
  // 验证所有组件可同时序列化/反序列化
  World w;
  Entity e1 = w.CreateEntity();
  Entity e2 = w.CreateEntity();
  Entity e3 = w.CreateEntity();

  TeamStateComponent tsc;
  tsc.team_id = 0;
  tsc.player_count = 11;
  w.AddComponent(e1, tsc);

  RefereeStateComponent rsc;
  rsc.buffer_active = true;
  rsc.foul_type = 1;
  w.AddComponent(e2, rsc);

  MatchStateComponent msc;
  msc.in_play = true;
  msc.match_time_ms = 30000;
  w.AddComponent(e3, msc);

  SerializedWorld data = WorldSerializer::Serialize<
      TeamStateComponent, RefereeStateComponent, MatchStateComponent>(w);

  World w2;
  WorldSerializer::Deserialize<
      TeamStateComponent, RefereeStateComponent, MatchStateComponent>(w2, data);

  // 验证所有组件都恢复了
  int team_count = 0, ref_count = 0, match_count = 0;
  w2.ForEach<TeamStateComponent>([&](Entity, TeamStateComponent& c) {
    EXPECT_EQ(c.team_id, 0);
    EXPECT_EQ(c.player_count, 11);
    team_count++;
  });
  w2.ForEach<RefereeStateComponent>([&](Entity, RefereeStateComponent& c) {
    EXPECT_TRUE(c.buffer_active);
    EXPECT_EQ(c.foul_type, 1);
    ref_count++;
  });
  w2.ForEach<MatchStateComponent>([&](Entity, MatchStateComponent& c) {
    EXPECT_TRUE(c.in_play);
    EXPECT_EQ(c.match_time_ms, 30000UL);
    match_count++;
  });

  EXPECT_EQ(team_count, 1);
  EXPECT_EQ(ref_count, 1);
  EXPECT_EQ(match_count, 1);
}
