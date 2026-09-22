// Copyright 2019 Google LLC & Bastiaan Konings
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// 2026-09-02 Phase 9: ECS 查询接口优化
// 提供更高效、更易用的查询机制

#ifndef _HPP_ECS_QUERY
#define _HPP_ECS_QUERY

#include "entity.hpp"
#include "world.hpp"

#include <algorithm>
#include <functional>
#include <tuple>
#include <utility>
#include <vector>

namespace blunted {

/// 查询结果缓存
template <typename... Components>
class QueryResult {
 public:
  using EntityList = std::vector<Entity>;
  using Iterator = EntityList::const_iterator;

  QueryResult() = default;
  
  /// 构造时执行查询
  QueryResult(World& world) {
    Execute(world);
  }

  /// 执行查询
  void Execute(World& world) {
    entities_.clear();
    
    // 使用第一个组件的池作为主遍历池
    ExecuteImpl(world, std::index_sequence_for<Components...>{});
  }

  /// 获取实体数量
  size_t Size() const { return entities_.size(); }

  /// 检查是否为空
  bool Empty() const { return entities_.empty(); }

  /// 获取实体列表
  const EntityList& Entities() const { return entities_; }

  /// 迭代器支持
  Iterator begin() const { return entities_.begin(); }
  Iterator end() const { return entities_.end(); }

  /// 检查是否包含指定实体
  bool Contains(Entity e) const {
    // 2026-09-09: query results inherit deterministic sorted entity order.
    // return std::find(entities_.begin(), entities_.end(), e) != entities_.end();
    return std::binary_search(entities_.begin(), entities_.end(), e);
  }

 private:
// 2026-09-09: cache each pool once and inspect only the smallest pool in immutable result construction.
//   template <size_t... Is>
//   void ExecuteImpl(World& world, std::index_sequence<Is...>) {
//     // 使用第一个组件的池作为主遍历池
//     using FirstComponent = std::tuple_element_t<0, std::tuple<Components...>>;
//     auto* primary_pool = world.template GetPool<FirstComponent>();
//
//     if (!primary_pool) return;
//
//     // 2026-09-09: avoid copying the entire primary pool for each query.
//     // for (Entity e : primary_pool->Entities()) {
//     for (Entity e : primary_pool->EntitiesSpan()) {
//       if ((world.template HasComponent<Components>(e) && ...)) {
//         entities_.push_back(e);
//       }
//     }
//   }
  template <size_t... Is>
  void ExecuteImpl(World& world, std::index_sequence<Is...>) {
    static_assert(sizeof...(Components) > 0, "Queries require at least one component");
    // Pool handles live only for this Execute call; Clear/recreation is safe
    // between calls, and missing types do not allocate empty pools.
    const auto pools = std::tuple{std::as_const(world).template GetPool<Components>()...};
    if (!std::apply([](auto*... pool) { return ((pool != nullptr) && ...); }, pools)) return;
    const auto smallest = std::apply([](auto*... pool) { return std::min({pool->Size()...}); }, pools);
    if (smallest == 0) return;
    std::span<const Entity> candidates;
    auto select = [&](const auto* pool) {
      if (candidates.empty() && pool->Size() == smallest) candidates = pool->EntitiesSpan();
    };
    std::apply([&](auto*... pool) { (select(pool), ...); }, pools);
    entities_.reserve(smallest);
    for (Entity e : candidates) {
      if (std::apply([&](auto*... pool) { return (pool->Has(e) && ...); }, pools)) entities_.push_back(e);
    }
  }

  EntityList entities_;
};

/// 查询构建器 - 支持链式调用
template <typename... Components>
class QueryBuilder {
 public:
  QueryBuilder(World& world) : world_(world) {}

  /// 执行查询并返回结果
  QueryResult<Components...> Execute() {
    return QueryResult<Components...>(world_);
  }

  /// 执行查询并对每个实体调用回调
  template <typename Fn>
  void ForEach(Fn&& fn) {
// 2026-09-09: snapshot membership, then skip matches removed by earlier callbacks; avoid per-entity pool discovery.
//     auto result = Execute();
//     for (Entity e : result) {
//       fn(e, *world_.template GetComponent<Components>(e)...);
//     }
    auto result = Execute();
    if (result.Empty()) return;
    const auto pools = std::tuple{world_.template GetPool<Components>()...};
    for (Entity e : result) {
      const auto components = std::apply([&](auto*... pool) { return std::tuple{pool->Get(e)...}; }, pools);
      std::apply([&](auto*... component) {
        if (((component != nullptr) && ...)) fn(e, *component...);
      }, components);
    }
  }

 private:
  World& world_;
};

/// 全局查询函数
template <typename... Components>
QueryBuilder<Components...> Query(World& world) {
  return QueryBuilder<Components...>(world);
}

/// 便捷查询函数 - 获取所有拥有指定组件的实体
template <typename... Components>
std::vector<Entity> GetEntities(World& world) {
  QueryResult<Components...> result(world);
  return result.Entities();
}

/// 便捷查询函数 - 检查实体是否拥有所有指定组件
template <typename... Components>
bool HasAllComponents(World& world, Entity e) {
  return (world.template HasComponent<Components>(e) && ...);
}

}  // namespace blunted

#endif
