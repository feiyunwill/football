// Copyright 2026 Google LLC & Contributors
// P2-Phase1 测试：PlayerPhysicsComponent 在 ECS World 中的操作
// 纯 POD 组件，不依赖引擎 math 库。

#include "ecs/world.hpp"
#include "ecs/entity.hpp"

#include <gtest/gtest.h>

using namespace blunted;

// ===== 测试用组件（纯 POD，无引擎依赖）=====

struct TestPhysics {
  float px = 0.0f, py = 0.0f, pz = 0.0f;
  float angle = 0.0f;
  float dx = 0.0f, dy = 0.0f, dz = 0.0f;
  int enumVelocity = 0;
  float floatVelocity = 0.0f;
  int foot = 1;
};

struct TestMeta {
  int stable_id = 0;
  int team_id = 0;
  bool is_active = false;
};

// ===== 默认值 =====

TEST(PlayerPhysicsTest, DefaultValues) {
  TestPhysics comp;
  EXPECT_FLOAT_EQ(comp.px, 0.0f);
  EXPECT_FLOAT_EQ(comp.angle, 0.0f);
  EXPECT_EQ(comp.enumVelocity, 0);
  EXPECT_EQ(comp.foot, 1);
}

// ===== ECS 存储与检索 =====

TEST(PlayerPhysicsTest, AddGetComponent) {
  World w;
  Entity e = w.CreateEntity();
  TestPhysics comp;
  comp.px = 10.0f;
  comp.py = 20.0f;
  comp.angle = 1.5f;
  comp.enumVelocity = 3;
  comp.floatVelocity = 8.5f;
  comp.foot = 0;
  w.AddComponent(e, comp);

  TestPhysics* got = w.GetComponent<TestPhysics>(e);
  ASSERT_NE(got, nullptr);
  EXPECT_FLOAT_EQ(got->px, 10.0f);
  EXPECT_FLOAT_EQ(got->py, 20.0f);
  EXPECT_FLOAT_EQ(got->angle, 1.5f);
  EXPECT_EQ(got->enumVelocity, 3);
  EXPECT_EQ(got->foot, 0);
}

TEST(PlayerPhysicsTest, OverwriteComponent) {
  World w;
  Entity e = w.CreateEntity();
  w.AddComponent(e, TestPhysics{1.0f, 2.0f, 0.0f, 0.0f, 0, 0, 0, 0, 0.0f, 1});
  w.AddComponent(e, TestPhysics{100.0f, 200.0f, 0.0f, 0.0f, 0, 0, 0, 3, 8.5f, 0});

  TestPhysics* got = w.GetComponent<TestPhysics>(e);
  ASSERT_NE(got, nullptr);
  EXPECT_FLOAT_EQ(got->px, 100.0f);
  EXPECT_EQ(got->enumVelocity, 3);
}

// ===== ForEach 遍历 =====

TEST(PlayerPhysicsTest, ForEachFiltersCorrectly) {
  World w;
  Entity e1 = w.CreateEntity();
  Entity e2 = w.CreateEntity();
  Entity e3 = w.CreateEntity();

  w.AddComponent(e1, TestPhysics{1.0f, 0, 0, 0, 0, 0, 0, 0, 5.0f, 1});
  w.AddComponent(e2, TestPhysics{2.0f, 0, 0, 0, 0, 0, 0, 0, 8.0f, 1});
  // e3 没有 TestPhysics

  int count = 0;
  float totalV = 0.0f;
  w.ForEach<TestPhysics>([&](Entity, TestPhysics& c) {
    count++;
    totalV += c.floatVelocity;
  });

  EXPECT_EQ(count, 2);
  EXPECT_FLOAT_EQ(totalV, 13.0f);
}

TEST(PlayerPhysicsTest, ForEachDeterministicOrder) {
  World w;
  std::vector<Entity> entities;
  for (int i = 0; i < 20; ++i) {
    Entity e = w.CreateEntity();
    w.AddComponent(e, TestPhysics{float(i), 0, 0, 0, 0, 0, 0, 0, 0.0f, 1});
    entities.push_back(e);
  }

  std::vector<Entity> traversal;
  w.ForEach<TestPhysics>([&](Entity e, TestPhysics&) {
    traversal.push_back(e);
  });

  ASSERT_EQ(traversal.size(), entities.size());
  for (size_t i = 0; i < entities.size(); ++i) {
    EXPECT_EQ(traversal[i], entities[i]);
  }
}

// ===== 多组件共存 =====

TEST(PlayerPhysicsTest, MultipleComponentsOnSameEntity) {
  World w;
  Entity e = w.CreateEntity();
  w.AddComponent(e, TestPhysics{5.0f, 10.0f, 0, 0, 0, 0, 0, 2, 0.0f, 1});
  w.AddComponent(e, TestMeta{42, 0, true});

  TestPhysics* pc = w.GetComponent<TestPhysics>(e);
  TestMeta* mc = w.GetComponent<TestMeta>(e);
  ASSERT_NE(pc, nullptr);
  ASSERT_NE(mc, nullptr);
  EXPECT_FLOAT_EQ(pc->px, 5.0f);
  EXPECT_EQ(mc->stable_id, 42);
  EXPECT_TRUE(mc->is_active);
}

TEST(PlayerPhysicsTest, ForEachTwoComponents) {
  World w;
  Entity e1 = w.CreateEntity();
  Entity e2 = w.CreateEntity();

  w.AddComponent(e1, TestPhysics{1.0f, 0, 0, 0, 0, 0, 0, 0, 0.0f, 1});
  w.AddComponent(e1, TestMeta{1, 0, true});

  w.AddComponent(e2, TestPhysics{2.0f, 0, 0, 0, 0, 0, 0, 0, 0.0f, 1});
  // e2 没有 TestMeta

  int count = 0;
  w.ForEach<TestPhysics, TestMeta>([&](Entity, TestPhysics&, TestMeta&) {
    count++;
  });
  EXPECT_EQ(count, 1);
}

// ===== RemoveComponent =====

TEST(PlayerPhysicsTest, RemoveComponent) {
  World w;
  Entity e = w.CreateEntity();
  w.AddComponent(e, TestPhysics{1.0f, 2.0f, 0, 0, 0, 0, 0, 0, 0.0f, 1});
  EXPECT_TRUE(w.HasComponent<TestPhysics>(e));

  w.RemoveComponent<TestPhysics>(e);
  EXPECT_FALSE(w.HasComponent<TestPhysics>(e));
  EXPECT_EQ(w.GetComponent<TestPhysics>(e), nullptr);
}

// ===== DestroyEntity =====

TEST(PlayerPhysicsTest, DestroyEntityRemovesAll) {
  World w;
  Entity e = w.CreateEntity();
  w.AddComponent(e, TestPhysics{1.0f, 2.0f, 0, 0, 0, 0, 0, 0, 0.0f, 1});
  w.AddComponent(e, TestMeta{1, 0, true});

  w.DestroyEntity(e);
  EXPECT_FALSE(w.HasComponent<TestPhysics>(e));
  EXPECT_FALSE(w.HasComponent<TestMeta>(e));
}

// ===== Clear =====

TEST(PlayerPhysicsTest, ClearRemovesAll) {
  World w;
  for (int i = 0; i < 50; ++i) {
    Entity e = w.CreateEntity();
    w.AddComponent(e, TestPhysics{float(i), 0, 0, 0, 0, 0, 0, 0, 0.0f, 1});
  }

  w.Clear();
  Entity e = w.CreateEntity();
  EXPECT_EQ(e, kNullEntity + 1);
}

// ===== 模拟双向同步模式 =====

TEST(PlayerPhysicsTest, BidirectionalSyncPattern) {
  // 模拟 SpatialState → PlayerPhysicsComponent 的单向同步
  float srcPx = 42.0f, srcPy = -15.0f;
  float srcAngle = 3.14f;
  int srcVelocity = 3;
  float srcFloatV = 8.5f;

  World w;
  Entity e = w.CreateEntity();
  // 初始全零
  w.AddComponent(e, TestPhysics{});

  // OOP → ECS 同步
  TestPhysics* comp = w.GetComponent<TestPhysics>(e);
  ASSERT_NE(comp, nullptr);
  comp->px = srcPx;
  comp->py = srcPy;
  comp->angle = srcAngle;
  comp->enumVelocity = srcVelocity;
  comp->floatVelocity = srcFloatV;

  // 验证同步结果
  TestPhysics* check = w.GetComponent<TestPhysics>(e);
  EXPECT_FLOAT_EQ(check->px, 42.0f);
  EXPECT_FLOAT_EQ(check->py, -15.0f);
  EXPECT_FLOAT_EQ(check->angle, 3.14f);
  EXPECT_EQ(check->enumVelocity, 3);
  EXPECT_FLOAT_EQ(check->floatVelocity, 8.5f);

  // ECS → OOP 反向同步（模拟）
  float dstPx = check->px;
  float dstAngle = check->angle;
  EXPECT_FLOAT_EQ(dstPx, 42.0f);
  EXPECT_FLOAT_EQ(dstAngle, 3.14f);
}
