// Copyright 2026 Google LLC & Contributors
// Unit tests for vector-based ComponentPool with swap-and-pop removal.

#include "world.hpp"
#include <cassert>
#include <iostream>
#include <set>
#include <string>
#include <vector>

struct Position {
  float x, y, z;
};

struct Velocity {
  float dx, dy, dz;
};

struct Name {
  std::string value;
};

void test_basic_operations() {
  std::cout << "=== Test: Basic Operations ===" << std::endl;
  
  blunted::World world;
  blunted::Entity e1 = world.CreateEntity();
  blunted::Entity e2 = world.CreateEntity();
  blunted::Entity e3 = world.CreateEntity();
  
  world.AddComponent(e1, Position{1.0f, 2.0f, 3.0f});
  world.AddComponent(e2, Position{4.0f, 5.0f, 6.0f});
  world.AddComponent(e3, Position{7.0f, 8.0f, 9.0f});
  
  // Test Get
  Position* p1 = world.GetComponent<Position>(e1);
  assert(p1 != nullptr);
  assert(p1->x == 1.0f);
  assert(p1->y == 2.0f);
  assert(p1->z == 3.0f);
  
  // Test Has
  assert(world.HasComponent<Position>(e1));
  assert(world.HasComponent<Position>(e2));
  assert(!world.HasComponent<Velocity>(e1));
  
  std::cout << "✓ Basic operations passed!" << std::endl;
}

void test_swap_and_pop_removal() {
  std::cout << "=== Test: Swap-and-Pop Removal ===" << std::endl;
  
  blunted::World world;
  blunted::Entity e1 = world.CreateEntity();
  blunted::Entity e2 = world.CreateEntity();
  blunted::Entity e3 = world.CreateEntity();
  blunted::Entity e4 = world.CreateEntity();
  
  world.AddComponent(e1, Position{1.0f, 0.0f, 0.0f});
  world.AddComponent(e2, Position{2.0f, 0.0f, 0.0f});
  world.AddComponent(e3, Position{3.0f, 0.0f, 0.0f});
  world.AddComponent(e4, Position{4.0f, 0.0f, 0.0f});
  
  // Remove middle element
  world.RemoveComponent<Position>(e2);
  assert(!world.HasComponent<Position>(e2));
  assert(world.HasComponent<Position>(e1));
  assert(world.HasComponent<Position>(e3));
  assert(world.HasComponent<Position>(e4));
  
  // Verify remaining elements are accessible
  Position* p1 = world.GetComponent<Position>(e1);
  Position* p3 = world.GetComponent<Position>(e3);
  Position* p4 = world.GetComponent<Position>(e4);
  assert(p1 != nullptr && p1->x == 1.0f);
  assert(p3 != nullptr && p3->x == 3.0f);
  assert(p4 != nullptr && p4->x == 4.0f);
  
  // Remove first element
  world.RemoveComponent<Position>(e1);
  assert(!world.HasComponent<Position>(e1));
  assert(world.HasComponent<Position>(e3));
  assert(world.HasComponent<Position>(e4));
  
  // Remove last element
  world.RemoveComponent<Position>(e4);
  assert(!world.HasComponent<Position>(e4));
  assert(world.HasComponent<Position>(e3));
  
  // Remove last remaining
  world.RemoveComponent<Position>(e3);
  assert(!world.HasComponent<Position>(e3));
  
  std::cout << "✓ Swap-and-pop removal passed!" << std::endl;
}

void test_deterministic_iteration() {
  std::cout << "=== Test: Deterministic Iteration ===" << std::endl;
  
  blunted::World world;
  // Create entities in non-sequential order
  blunted::Entity e3 = world.CreateEntity();  // id = 1
  blunted::Entity e1 = world.CreateEntity();  // id = 2
  blunted::Entity e4 = world.CreateEntity();  // id = 3
  blunted::Entity e2 = world.CreateEntity();  // id = 4
  
  std::cout << "  e1=" << e1 << " e2=" << e2 << " e3=" << e3 << " e4=" << e4 << std::endl;
  
  world.AddComponent(e3, Position{3.0f, 0.0f, 0.0f});
  world.AddComponent(e1, Position{1.0f, 0.0f, 0.0f});
  world.AddComponent(e4, Position{4.0f, 0.0f, 0.0f});
  world.AddComponent(e2, Position{2.0f, 0.0f, 0.0f});
  
  // Iterate multiple times and verify order is always the same
  std::vector<float> first_run;
  world.ForEach<Position>([&](blunted::Entity e, Position& p) {
    first_run.push_back(p.x);
  });
  
  for (int i = 0; i < 10; ++i) {
    std::vector<float> run;
    world.ForEach<Position>([&](blunted::Entity e, Position& p) {
      run.push_back(p.x);
    });
    assert(run == first_run);
  }
  
  // Verify order is sorted by entity ID
  assert(first_run.size() == 4);
  // Print actual order for debugging
  std::cout << "  Actual order: ";
  for (float x : first_run) std::cout << x << " ";
  std::cout << std::endl;
  // Entities are created with IDs 1,2,3,4 in order of CreateEntity() calls
  // So e3=1, e1=2, e4=3, e2=4
  // After sorting by ID: e3(1), e1(2), e4(3), e2(4)
  // Positions: e3=3.0, e1=1.0, e4=4.0, e2=2.0
  // Sorted by ID: 3.0, 1.0, 4.0, 2.0
  assert(first_run[0] == 3.0f);  // e3 (id=1)
  assert(first_run[1] == 1.0f);  // e1 (id=2)
  assert(first_run[2] == 4.0f);  // e4 (id=3)
  assert(first_run[3] == 2.0f);  // e2 (id=4)
  
  std::cout << "✓ Deterministic iteration passed!" << std::endl;
}

void test_iteration_after_removal() {
  std::cout << "=== Test: Iteration After Removal ===" << std::endl;
  
  blunted::World world;
  blunted::Entity e1 = world.CreateEntity();  // id=1
  blunted::Entity e2 = world.CreateEntity();  // id=2
  blunted::Entity e3 = world.CreateEntity();  // id=3
  blunted::Entity e4 = world.CreateEntity();  // id=4
  blunted::Entity e5 = world.CreateEntity();  // id=5
  
  world.AddComponent(e1, Position{1.0f, 0.0f, 0.0f});
  world.AddComponent(e2, Position{2.0f, 0.0f, 0.0f});
  world.AddComponent(e3, Position{3.0f, 0.0f, 0.0f});
  world.AddComponent(e4, Position{4.0f, 0.0f, 0.0f});
  world.AddComponent(e5, Position{5.0f, 0.0f, 0.0f});
  
  // Remove some elements
  world.RemoveComponent<Position>(e2);
  world.RemoveComponent<Position>(e4);
  
  // Verify iteration still works
  std::vector<float> values;
  world.ForEach<Position>([&](blunted::Entity e, Position& p) {
    values.push_back(p.x);
  });
  
  // After removing e2 and e4, remaining: e1(1.0), e3(3.0), e5(5.0)
  // Note: swap-and-pop doesn't guarantee sorted order, but guarantees
  // deterministic iteration order across runs
  assert(values.size() == 3);
  
  // Verify all remaining entities are present
  std::set<float> value_set(values.begin(), values.end());
  assert(value_set.count(1.0f));  // e1
  assert(value_set.count(3.0f));  // e3
  assert(value_set.count(5.0f));  // e5
  
  // Verify iteration is deterministic (same order on repeated calls)
  for (int i = 0; i < 10; ++i) {
    std::vector<float> run;
    world.ForEach<Position>([&](blunted::Entity e, Position& p) {
      run.push_back(p.x);
    });
    assert(run == values);
  }
  
  std::cout << "  Values after removal: ";
  for (float v : values) std::cout << v << " ";
  std::cout << std::endl;
  
  std::cout << "✓ Iteration after removal passed!" << std::endl;
}

void test_multiple_component_types() {
  std::cout << "=== Test: Multiple Component Types ===" << std::endl;
  
  blunted::World world;
  blunted::Entity e1 = world.CreateEntity();
  blunted::Entity e2 = world.CreateEntity();
  blunted::Entity e3 = world.CreateEntity();
  
  world.AddComponent(e1, Position{1.0f, 0.0f, 0.0f});
  world.AddComponent(e1, Velocity{0.1f, 0.0f, 0.0f});
  world.AddComponent(e1, Name{"player1"});
  
  world.AddComponent(e2, Position{2.0f, 0.0f, 0.0f});
  world.AddComponent(e2, Velocity{0.2f, 0.0f, 0.0f});
  
  world.AddComponent(e3, Position{3.0f, 0.0f, 0.0f});
  world.AddComponent(e3, Name{"player3"});
  
  // Test ForEach with single component
  int count = 0;
  world.ForEach<Position>([&](blunted::Entity e, Position& p) {
    count++;
  });
  assert(count == 3);
  
  // Test ForEach with two components
  count = 0;
  world.ForEach<Position, Velocity>([&](blunted::Entity e, Position& p, Velocity& v) {
    count++;
  });
  assert(count == 2);  // e1 and e2 have both Position and Velocity
  
  // Remove Velocity from e1, verify ForEach still works
  world.RemoveComponent<Velocity>(e1);
  count = 0;
  world.ForEach<Position, Velocity>([&](blunted::Entity e, Position& p, Velocity& v) {
    count++;
  });
  assert(count == 1);  // Only e2 has both
  
  std::cout << "✓ Multiple component types passed!" << std::endl;
}

void test_destroy_entity() {
  std::cout << "=== Test: Destroy Entity ===" << std::endl;
  
  blunted::World world;
  blunted::Entity e1 = world.CreateEntity();
  blunted::Entity e2 = world.CreateEntity();
  blunted::Entity e3 = world.CreateEntity();
  
  world.AddComponent(e1, Position{1.0f, 0.0f, 0.0f});
  world.AddComponent(e1, Velocity{0.1f, 0.0f, 0.0f});
  world.AddComponent(e2, Position{2.0f, 0.0f, 0.0f});
  world.AddComponent(e3, Position{3.0f, 0.0f, 0.0f});
  world.AddComponent(e3, Velocity{0.3f, 0.0f, 0.0f});
  
  // Destroy entity with multiple components
  world.DestroyEntity(e2);
  assert(!world.HasComponent<Position>(e2));
  
  // Verify other entities are unaffected
  assert(world.HasComponent<Position>(e1));
  assert(world.HasComponent<Velocity>(e1));
  assert(world.HasComponent<Position>(e3));
  assert(world.HasComponent<Velocity>(e3));
  
  // Verify iteration counts
  int pos_count = 0;
  world.ForEach<Position>([&](blunted::Entity e, Position& p) {
    pos_count++;
  });
  assert(pos_count == 2);  // e1 and e3
  
  std::cout << "✓ Destroy entity passed!" << std::endl;
}

int main() {
  std::cout << "ComponentPool Unit Tests" << std::endl;
  std::cout << "========================" << std::endl;
  
  test_basic_operations();
  test_swap_and_pop_removal();
  test_deterministic_iteration();
  test_iteration_after_removal();
  test_multiple_component_types();
  test_destroy_entity();
  
  std::cout << std::endl;
  std::cout << "========================" << std::endl;
  std::cout << "All tests passed!" << std::endl;
  
  return 0;
}
