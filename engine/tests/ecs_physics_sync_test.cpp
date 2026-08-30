// Copyright 2026 Google LLC & Contributors
// P2-Phase1/2/3/4 测试：ECS 组件操作与序列化
// 纯 POD 组件，不依赖引擎 math 库。

#include "ecs/world.hpp"
#include "ecs/entity.hpp"
#include "ecs/serializer.hpp"
#include "ecs/system_graph.hpp"
#include <typeindex>

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

// ===== TacticsComponent 模拟测试 =====

struct TestTacticsComponent {
  bool hasPossession = false;
  int timeNeededToGetToBall_ms = 0;
  float teamPossessionAmount = 0.0f;
  float fadingTeamPossessionAmount = 0.0f;
  int side = -1;
  int team_id = 0;
};

TEST(TacticsComponentTest, DefaultValues) {
  TestTacticsComponent comp;
  EXPECT_FALSE(comp.hasPossession);
  EXPECT_EQ(comp.timeNeededToGetToBall_ms, 0);
  EXPECT_FLOAT_EQ(comp.teamPossessionAmount, 0.0f);
  EXPECT_EQ(comp.side, -1);
}

TEST(TacticsComponentTest, AddGetComponent) {
  World w;
  Entity e = w.CreateEntity();
  TestTacticsComponent comp;
  comp.hasPossession = true;
  comp.timeNeededToGetToBall_ms = 500;
  comp.teamPossessionAmount = 0.7f;
  comp.fadingTeamPossessionAmount = 0.65f;
  comp.side = -1;
  comp.team_id = 0;
  w.AddComponent(e, comp);

  TestTacticsComponent* got = w.GetComponent<TestTacticsComponent>(e);
  ASSERT_NE(got, nullptr);
  EXPECT_TRUE(got->hasPossession);
  EXPECT_EQ(got->timeNeededToGetToBall_ms, 500);
  EXPECT_FLOAT_EQ(got->teamPossessionAmount, 0.7f);
  EXPECT_EQ(got->side, -1);
  EXPECT_EQ(got->team_id, 0);
}

TEST(TacticsComponentTest, RoundTripOopToEcsToOop) {
  TestTacticsComponent src;
  src.hasPossession = true;
  src.timeNeededToGetToBall_ms = 1200;
  src.teamPossessionAmount = 0.85f;
  src.fadingTeamPossessionAmount = 0.80f;
  src.side = 1;
  src.team_id = 1;

  World w;
  Entity e = w.CreateEntity();
  w.AddComponent(e, src);

  const TestTacticsComponent* comp = w.GetComponent<TestTacticsComponent>(e);
  ASSERT_NE(comp, nullptr);

  TestTacticsComponent dst;
  dst.hasPossession = comp->hasPossession;
  dst.timeNeededToGetToBall_ms = comp->timeNeededToGetToBall_ms;
  dst.teamPossessionAmount = comp->teamPossessionAmount;
  dst.fadingTeamPossessionAmount = comp->fadingTeamPossessionAmount;
  dst.side = comp->side;
  dst.team_id = comp->team_id;

  EXPECT_TRUE(dst.hasPossession);
  EXPECT_EQ(dst.timeNeededToGetToBall_ms, 1200);
  EXPECT_FLOAT_EQ(dst.teamPossessionAmount, 0.85f);
  EXPECT_EQ(dst.side, 1);
  EXPECT_EQ(dst.team_id, 1);
}

// ===== BallComponent 模拟测试 =====

struct TestBallComponent {
  float mx = 0.0f, my = 0.0f, mz = 0.0f;  // momentum
  float qw = 1.0f, qx = 0.0f, qy = 0.0f, qz = 0.0f;  // rotation quaternion
  float px = 0.0f, py = 0.0f, pz = 0.0f;  // positionBuffer
  bool ballTouchesNet = false;
  int valid_predictions = 0;
};

TEST(BallComponentTest, AddGetComponent) {
  World w;
  Entity e = w.CreateEntity();
  TestBallComponent comp;
  comp.mx = 5.0f;
  comp.my = -3.0f;
  comp.mz = 0.0f;
  comp.px = 10.0f;
  comp.py = 20.0f;
  comp.ballTouchesNet = true;
  comp.valid_predictions = 42;
  w.AddComponent(e, comp);

  TestBallComponent* got = w.GetComponent<TestBallComponent>(e);
  ASSERT_NE(got, nullptr);
  EXPECT_FLOAT_EQ(got->mx, 5.0f);
  EXPECT_FLOAT_EQ(got->my, -3.0f);
  EXPECT_TRUE(got->ballTouchesNet);
  EXPECT_EQ(got->valid_predictions, 42);
}

TEST(BallComponentTest, RoundTripOopToEcsToOop) {
  TestBallComponent src;
  src.mx = 7.5f;
  src.my = -2.1f;
  src.mz = 0.3f;
  src.px = 42.0f;
  src.py = -15.0f;
  src.pz = 0.0f;
  src.ballTouchesNet = false;
  src.valid_predictions = 100;

  World w;
  Entity e = w.CreateEntity();
  w.AddComponent(e, src);

  const TestBallComponent* comp = w.GetComponent<TestBallComponent>(e);
  ASSERT_NE(comp, nullptr);

  TestBallComponent dst;
  dst.mx = comp->mx;
  dst.my = comp->my;
  dst.mz = comp->mz;
  dst.px = comp->px;
  dst.py = comp->py;
  dst.pz = comp->pz;
  dst.ballTouchesNet = comp->ballTouchesNet;
  dst.valid_predictions = comp->valid_predictions;

  EXPECT_FLOAT_EQ(dst.mx, 7.5f);
  EXPECT_FLOAT_EQ(dst.my, -2.1f);
  EXPECT_FLOAT_EQ(dst.mz, 0.3f);
  EXPECT_FLOAT_EQ(dst.px, 42.0f);
  EXPECT_FLOAT_EQ(dst.py, -15.0f);
  EXPECT_FALSE(dst.ballTouchesNet);
  EXPECT_EQ(dst.valid_predictions, 100);
}

TEST(BallComponentTest, OverwriteComponent) {
  World w;
  Entity e = w.CreateEntity();
  w.AddComponent(e, TestBallComponent{1.0f, 2.0f, 3.0f});
  w.AddComponent(e, TestBallComponent{10.0f, 20.0f, 30.0f});

  TestBallComponent* got = w.GetComponent<TestBallComponent>(e);
  ASSERT_NE(got, nullptr);
  EXPECT_FLOAT_EQ(got->mx, 10.0f);
  EXPECT_FLOAT_EQ(got->my, 20.0f);
  EXPECT_FLOAT_EQ(got->mz, 30.0f);
}

TEST(BallComponentTest, ForEachDeterministicOrder) {
  World w;
  std::vector<Entity> entities;
  for (int i = 0; i < 10; ++i) {
    Entity e = w.CreateEntity();
    w.AddComponent(e, TestBallComponent{float(i), 0, 0});
    entities.push_back(e);
  }

  std::vector<Entity> traversal;
  w.ForEach<TestBallComponent>([&](Entity e, TestBallComponent&) {
    traversal.push_back(e);
  });

  ASSERT_EQ(traversal.size(), entities.size());
  for (size_t i = 0; i < entities.size(); ++i) {
    EXPECT_EQ(traversal[i], entities[i]);
  }
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

// ===== WorldSerializer 测试 =====

TEST(WorldSerializerTest, SerializeEmptyWorld) {
  World w;
  SerializedWorld data = WorldSerializer::Serialize<TestPhysics>(w);
  auto key = std::type_index(typeid(TestPhysics));
  EXPECT_EQ(data.pools[key].size(), 0u);
}

TEST(WorldSerializerTest, SerializeDeserializeRoundTrip) {
  World w;
  Entity e1 = w.CreateEntity();
  Entity e2 = w.CreateEntity();
  w.AddComponent(e1, TestPhysics{1.0f, 2.0f, 0, 0, 0, 0, 0, 0, 5.0f, 1});
  w.AddComponent(e2, TestPhysics{3.0f, 4.0f, 0, 0, 0, 0, 0, 2, 8.0f, 0});

  SerializedWorld data = WorldSerializer::Serialize<TestPhysics>(w);
  auto key = std::type_index(typeid(TestPhysics));
  EXPECT_EQ(data.pools[key].size(), 2u);

  // 反序列化到新 World
  World w2;
  WorldSerializer::Deserialize<TestPhysics>(w2, data);

  // 验证实体数量
  int count = 0;
  w2.ForEach<TestPhysics>([&](Entity, TestPhysics& c) {
    count++;
  });
  EXPECT_EQ(count, 2);
}

TEST(WorldSerializerTest, PreserveComponentData) {
  World w;
  Entity e = w.CreateEntity();
  TestPhysics src;
  src.px = 42.0f;
  src.py = -15.0f;
  src.angle = 3.14f;
  src.enumVelocity = 3;
  src.floatVelocity = 8.5f;
  src.foot = 0;
  w.AddComponent(e, src);

  SerializedWorld data = WorldSerializer::Serialize<TestPhysics>(w);

  World w2;
  WorldSerializer::Deserialize<TestPhysics>(w2, data);

  TestPhysics* got = nullptr;
  w2.ForEach<TestPhysics>([&](Entity, TestPhysics& c) {
    got = &c;
  });
  ASSERT_NE(got, nullptr);
  EXPECT_FLOAT_EQ(got->px, 42.0f);
  EXPECT_FLOAT_EQ(got->py, -15.0f);
  EXPECT_FLOAT_EQ(got->angle, 3.14f);
  EXPECT_EQ(got->enumVelocity, 3);
  EXPECT_FLOAT_EQ(got->floatVelocity, 8.5f);
  EXPECT_EQ(got->foot, 0);
}

TEST(WorldSerializerTest, MultipleComponentTypes) {
  World w;
  Entity e = w.CreateEntity();
  w.AddComponent(e, TestPhysics{1.0f, 2.0f, 0, 0, 0, 0, 0, 0, 5.0f, 1});
  w.AddComponent(e, TestMeta{42, 0, true});
  w.AddComponent(e, TestTacticsComponent{true, 500, 0.7f, 0.65f, -1, 0});

  SerializedWorld data =
      WorldSerializer::Serialize<TestPhysics, TestMeta, TestTacticsComponent>(w);
  auto key_p = std::type_index(typeid(TestPhysics));
  EXPECT_EQ(data.pools[key_p].size(), 1u);

  World w2;
  WorldSerializer::Deserialize<TestPhysics, TestMeta, TestTacticsComponent>(w2, data);

  int count = 0;
  w2.ForEach<TestPhysics>([&](Entity e2, TestPhysics& p) {
    count++;
    EXPECT_FLOAT_EQ(p.px, 1.0f);
    EXPECT_TRUE(w2.HasComponent<TestMeta>(e2));
    EXPECT_TRUE(w2.HasComponent<TestTacticsComponent>(e2));
    TestMeta* m = w2.GetComponent<TestMeta>(e2);
    ASSERT_NE(m, nullptr);
    EXPECT_EQ(m->stable_id, 42);
    EXPECT_TRUE(m->is_active);
    TestTacticsComponent* t = w2.GetComponent<TestTacticsComponent>(e2);
    ASSERT_NE(t, nullptr);
    EXPECT_TRUE(t->hasPossession);
    EXPECT_EQ(t->timeNeededToGetToBall_ms, 500);
  });
  EXPECT_EQ(count, 1);
}

TEST(WorldSerializerTest, DeterministicEntityOrder) {
  World w;
  for (int i = 0; i < 10; ++i) {
    Entity e = w.CreateEntity();
    w.AddComponent(e, TestPhysics{float(i), 0, 0, 0, 0, 0, 0, 0, 0.0f, 1});
  }

  SerializedWorld data = WorldSerializer::Serialize<TestPhysics>(w);
  auto key = std::type_index(typeid(TestPhysics));
  EXPECT_EQ(data.pools[key].size(), 10u);

  World w2;
  WorldSerializer::Deserialize<TestPhysics>(w2, data);

  std::vector<float> positions;
  w2.ForEach<TestPhysics>([&](Entity, TestPhysics& c) {
    positions.push_back(c.px);
  });

  ASSERT_EQ(positions.size(), 10u);
  for (int i = 0; i < 10; ++i) {
    EXPECT_FLOAT_EQ(positions[i], float(i));
  }
}

// ===== SystemGraph 测试 =====

TEST(SystemGraphTest, EmptyGraph) {
  blunted::SystemGraph g;
  EXPECT_EQ(g.Size(), 0u);
  EXPECT_TRUE(g.Sort().empty());
  EXPECT_TRUE(g.Execute(nullptr));
}

TEST(SystemGraphTest, SingleSystem) {
  blunted::SystemGraph g;
  int call_count = 0;
  g.Register("a", [&](void*) -> bool { call_count++; return true; });
  EXPECT_EQ(g.Size(), 1u);
  EXPECT_TRUE(g.Execute(nullptr));
  EXPECT_EQ(call_count, 1);
}

TEST(SystemGraphTest, LinearDependency) {
  blunted::SystemGraph g;
  std::vector<std::string> order;
  g.Register("a", [&](void*) -> bool { order.push_back("a"); return true; });
  g.Register("b", [&](void*) -> bool { order.push_back("b"); return true; }, {"a"});
  g.Register("c", [&](void*) -> bool { order.push_back("c"); return true; }, {"b"});

  EXPECT_TRUE(g.Execute(nullptr));
  ASSERT_EQ(order.size(), 3u);
  EXPECT_EQ(order[0], "a");
  EXPECT_EQ(order[1], "b");
  EXPECT_EQ(order[2], "c");
}

TEST(SystemGraphTest, DiamondDependency) {
  blunted::SystemGraph g;
  std::vector<std::string> order;
  g.Register("a", [&](void*) -> bool { order.push_back("a"); return true; });
  g.Register("b", [&](void*) -> bool { order.push_back("b"); return true; }, {"a"});
  g.Register("c", [&](void*) -> bool { order.push_back("c"); return true; }, {"a"});
  g.Register("d", [&](void*) -> bool { order.push_back("d"); return true; }, {"b", "c"});

  EXPECT_TRUE(g.Execute(nullptr));
  ASSERT_EQ(order.size(), 4u);
  // a 必须在 b 和 c 之前，d 必须在 b 和 c 之后
  EXPECT_EQ(order[0], "a");
  EXPECT_EQ(order[3], "d");
  // b 和 c 的相对顺序不固定
  bool b_before_c = (order[1] == "b" && order[2] == "c");
  bool c_before_b = (order[1] == "c" && order[2] == "b");
  EXPECT_TRUE(b_before_c || c_before_b);
}

TEST(SystemGraphTest, CycleDetection) {
  blunted::SystemGraph g;
  g.Register("a", [](void*) -> bool { return true; }, {"c"});
  g.Register("b", [](void*) -> bool { return true; }, {"a"});
  g.Register("c", [](void*) -> bool { return true; }, {"b"});

  EXPECT_TRUE(g.HasCycle());
  EXPECT_TRUE(g.Sort().empty());
  EXPECT_FALSE(g.Execute(nullptr));
}

TEST(SystemGraphTest, EarlyAbort) {
  blunted::SystemGraph g;
  std::vector<std::string> order;
  // b 依赖 a，c 依赖 b → 顺序确定：a → b → c
  g.Register("a", [&](void*) -> bool { order.push_back("a"); return true; });
  g.Register("b", [&](void*) -> bool { order.push_back("b"); return false; }, {"a"});
  g.Register("c", [&](void*) -> bool { order.push_back("c"); return true; }, {"b"});

  EXPECT_FALSE(g.Execute(nullptr));
  ASSERT_EQ(order.size(), 2u);
  EXPECT_EQ(order[0], "a");
  EXPECT_EQ(order[1], "b");
  // c 不应被执行（b 返回 false 中断了管线）
}

TEST(SystemGraphTest, ContextPassing) {
  blunted::SystemGraph g;
  int value = 0;
  g.Register("inc", [&](void* ctx) -> bool {
    int* v = static_cast<int*>(ctx);
    (*v)++;
    return true;
  });
  g.Register("double", [&](void* ctx) -> bool {
    int* v = static_cast<int*>(ctx);
    (*v) *= 2;
    return true;
  }, {"inc"});

  EXPECT_TRUE(g.Execute(&value));
  EXPECT_EQ(value, 2);  // 0 → 1 → 2
}

TEST(SystemGraphTest, ClearResetsState) {
  blunted::SystemGraph g;
  g.Register("a", [](void*) -> bool { return true; });
  g.Register("b", [](void*) -> bool { return true; }, {"a"});
  EXPECT_EQ(g.Size(), 2u);

  g.Clear();
  EXPECT_EQ(g.Size(), 0u);
  EXPECT_TRUE(g.Sort().empty());
}

TEST(SystemGraphTest, IndependentSystems) {
  blunted::SystemGraph g;
  std::vector<std::string> order;
  g.Register("a", [&](void*) -> bool { order.push_back("a"); return true; });
  g.Register("b", [&](void*) -> bool { order.push_back("b"); return true; });
  g.Register("c", [&](void*) -> bool { order.push_back("c"); return true; });

  EXPECT_TRUE(g.Execute(nullptr));
  EXPECT_EQ(order.size(), 3u);
  // 无依赖时，所有系统都会执行（顺序不确定）
}
