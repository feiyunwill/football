// Copyright 2019 Google LLC & Bastiaan Konings
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//

#ifndef _HPP_ECS_WORLD
#define _HPP_ECS_WORLD

#include "entity.hpp"

#include <algorithm>
#include <memory>
#include <typeindex>
#include <unordered_map>
#include <vector>

namespace blunted {

/// 类型擦除的组件池接口（2025-03-17 ECS 自研最小实现）
class IComponentPool {
 public:
  virtual ~IComponentPool() = default;
  virtual bool Has(Entity e) const = 0;
  virtual void Remove(Entity e) = 0;
  virtual void Clear() = 0;
};

/// Vector-based component pool with O(1) swap-and-pop removal.
/// Entities are stored in a dense vector for cache-friendly iteration.
/// An index map provides O(1) entity-to-index lookup.
/// Deterministic iteration order: entities are always in ID order.
template <typename T>
class ComponentPool : public IComponentPool {
 public:
  bool Has(Entity e) const override {
    auto it = entity_to_index_.find(e);
    return it != entity_to_index_.end();
  }

  void Remove(Entity e) override {
    auto it = entity_to_index_.find(e);
    if (it == entity_to_index_.end()) return;
    
    size_t idx = it->second;
    size_t last_idx = entities_.size() - 1;
    
    if (idx != last_idx) {
      // Swap with last element
      entities_[idx] = entities_[last_idx];
      components_[idx] = std::move(components_[last_idx]);
      entity_to_index_[entities_[idx]] = idx;
    }
    
    entities_.pop_back();
    components_.pop_back();
    entity_to_index_.erase(it);
  }

  void Clear() override {
    entities_.clear();
    components_.clear();
    entity_to_index_.clear();
  }

  T* Get(Entity e) {
    auto it = entity_to_index_.find(e);
    if (it == entity_to_index_.end()) return nullptr;
    return &components_[it->second];
  }

  const T* Get(Entity e) const {
    auto it = entity_to_index_.find(e);
    if (it == entity_to_index_.end()) return nullptr;
    return &components_[it->second];
  }

  void Set(Entity e, T comp) {
    auto it = entity_to_index_.find(e);
    if (it != entity_to_index_.end()) {
      // Update existing
      components_[it->second] = std::move(comp);
      return;
    }
    // Insert at end - 排序在批量操作后统一进行
    entity_to_index_[e] = entities_.size();
    entities_.push_back(e);
    components_.push_back(std::move(comp));
  }

  /// 批量插入后统一排序，保持确定性顺序
  void SortIfNeeded() {
    if (entities_.size() <= 1) return;
    
    // 使用插入排序保持稳定性
    for (size_t i = 1; i < entities_.size(); ++i) {
      Entity key_entity = entities_[i];
      T key_component = std::move(components_[i]);
      size_t j = i;
      
      while (j > 0 && entities_[j - 1] > key_entity) {
        entities_[j] = entities_[j - 1];
        components_[j] = std::move(components_[j - 1]);
        --j;
      }
      
      if (j != i) {
        entities_[j] = key_entity;
        components_[j] = std::move(key_component);
      }
    }
    
    // 更新索引映射
    for (size_t i = 0; i < entities_.size(); ++i) {
      entity_to_index_[entities_[i]] = i;
    }
  }

  /// Returns entities in deterministic order (sorted by ID).
  /// This is O(n) because entities_ is maintained in ID order.
  std::vector<Entity> Entities() const {
    // entities_ is already sorted by ID due to our insertion logic
    return entities_;
  }

  size_t Size() const { return entities_.size(); }

 private:
  std::vector<Entity> entities_;           // Dense storage of entity IDs
  std::vector<T> components_;             // Parallel dense storage of components
  std::unordered_map<Entity, size_t> entity_to_index_;  // Entity -> index mapping
};

/// ECS World：实体与组件存储，按类型查询（2025-03-17 ECS 迁移）
class World {
 public:
  World() = default;
  ~World() = default;

  World(const World&) = delete;
  World& operator=(const World&) = delete;
  World(World&&) = default;
  World& operator=(World&&) = default;

  Entity CreateEntity() {
    ++next_id_;
    return next_id_;
  }

  void DestroyEntity(Entity e) {
    for (auto& p : pools_) p.second->Remove(e);
  }

  template <typename T>
  void AddComponent(Entity e, T comp) {
    Pool<T>()->Set(e, std::move(comp));
  }

  /// 批量添加组件后统一排序，提高性能
  template <typename T>
  void FlushBatchAdds() {
    Pool<T>()->SortIfNeeded();
  }

  template <typename T>
  T* GetComponent(Entity e) {
    return Pool<T>()->Get(e);
  }

  template <typename T>
  const T* GetComponent(Entity e) const {
    return Pool<T>()->Get(e);
  }

  template <typename T>
  bool HasComponent(Entity e) const {
    const auto* pool = Pool<T>();
    return pool && pool->Has(e);
  }

  template <typename T>
  void RemoveComponent(Entity e) {
    Pool<T>()->Remove(e);
  }

  /// 对拥有组件 T 的每个实体调用 fn(entity, component_ref)
  template <typename T, typename Fn>
  void ForEach(Fn&& fn) {
    auto* pool = Pool<T>();
    for (const Entity e : pool->Entities()) {
      T* comp = pool->Get(e);
      if (comp) fn(e, *comp);
    }
  }

  template <typename T, typename Fn>
  void ForEach(Fn&& fn) const {
    const auto* pool = Pool<T>();
    if (!pool) return;
    for (const Entity e : pool->Entities()) {
      const T* comp = pool->Get(e);
      if (comp) fn(e, *comp);
    }
  }

  /// 对同时拥有 T1 和 T2 的实体调用 fn
  template <typename T1, typename T2, typename Fn>
  void ForEach(Fn&& fn) {
    auto* p1 = Pool<T1>();
    auto* p2 = Pool<T2>();
    for (const Entity e : p1->Entities()) {
      if (!p2->Has(e)) continue;
      T1* c1 = p1->Get(e);
      T2* c2 = p2->Get(e);
      if (c1 && c2) fn(e, *c1, *c2);
    }
  }

  /// 优化版多组件查询：使用较小的池作为主遍历池
  template <typename T1, typename T2, typename T3, typename Fn>
  void ForEach(Fn&& fn) {
    auto* p1 = Pool<T1>();
    auto* p2 = Pool<T2>();
    auto* p3 = Pool<T3>();
    
    // 选择最小的池作为主遍历池
    const auto* smallest_pool = p1;
    if (p2->Size() < smallest_pool->Size()) smallest_pool = p2;
    if (p3->Size() < smallest_pool->Size()) smallest_pool = p3;
    
    for (const Entity e : smallest_pool->Entities()) {
      if (!p1->Has(e) || !p2->Has(e) || !p3->Has(e)) continue;
      T1* c1 = p1->Get(e);
      T2* c2 = p2->Get(e);
      T3* c3 = p3->Get(e);
      if (c1 && c2 && c3) fn(e, *c1, *c2, *c3);
    }
  }

  void Clear() {
    pools_.clear();
    next_id_ = kNullEntity;
  }

  /// 获取组件池（供查询接口使用）
  template <typename T>
  ComponentPool<T>* GetPool() {
    return Pool<T>();
  }

  template <typename T>
  const ComponentPool<T>* GetPool() const {
    return Pool<T>();
  }

 private:
  template <typename T>
  ComponentPool<T>* Pool() {
    std::type_index key(typeid(T));
    auto it = pools_.find(key);
    if (it == pools_.end()) {
      auto u = std::make_unique<ComponentPool<T>>();
      ComponentPool<T>* p = u.get();
      pools_[key] = std::move(u);
      return p;
    }
    return static_cast<ComponentPool<T>*>(it->second.get());
  }

  template <typename T>
  const ComponentPool<T>* Pool() const {
    std::type_index key(typeid(T));
    auto it = pools_.find(key);
    return it == pools_.end() ? nullptr
                              : static_cast<const ComponentPool<T>*>(
                                    it->second.get());
  }

  std::unordered_map<std::type_index, std::unique_ptr<IComponentPool>> pools_;
  Entity next_id_ = kNullEntity;
};

}  // namespace blunted

#endif
