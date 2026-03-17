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

template <typename T>
class ComponentPool : public IComponentPool {
 public:
  bool Has(Entity e) const override {
    return storage_.find(e) != storage_.end();
  }
  void Remove(Entity e) override { storage_.erase(e); }
  void Clear() override { storage_.clear(); }

  T* Get(Entity e) {
    auto it = storage_.find(e);
    return it == storage_.end() ? nullptr : &it->second;
  }
  const T* Get(Entity e) const {
    auto it = storage_.find(e);
    return it == storage_.end() ? nullptr : &it->second;
  }
  void Set(Entity e, T comp) { storage_[e] = std::move(comp); }
  std::vector<Entity> Entities() const {
    std::vector<Entity> out;
    out.reserve(storage_.size());
    for (const auto& p : storage_) out.push_back(p.first);
    return out;
  }

 private:
  std::unordered_map<Entity, T> storage_;
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
    return Pool<T>()->Has(e);
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

  void Clear() {
    pools_.clear();
    next_id_ = kNullEntity;
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
