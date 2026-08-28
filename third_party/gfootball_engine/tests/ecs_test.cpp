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
