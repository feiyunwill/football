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
    return std::find(entities_.begin(), entities_.end(), e) != entities_.end();
  }

 private:
  template <size_t... Is>
  void ExecuteImpl(World& world, std::index_sequence<Is...>) {
    // 使用第一个组件的池作为主遍历池
    using FirstComponent = std::tuple_element_t<0, std::tuple<Components...>>;
    auto* primary_pool = world.template GetPool<FirstComponent>();
    
    if (!primary_pool) return;
    
    for (Entity e : primary_pool->Entities()) {
      if ((world.template HasComponent<Components>(e) && ...)) {
        entities_.push_back(e);
      }
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
    auto result = Execute();
    for (Entity e : result) {
      fn(e, *world_.template GetComponent<Components>(e)...);
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
