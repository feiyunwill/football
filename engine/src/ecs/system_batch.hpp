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

// 2026-09-02 Phase 9: ECS 系统批处理
// 将多个相关系统合并执行，减少系统调用开销

#ifndef _HPP_ECS_SYSTEM_BATCH
#define _HPP_ECS_SYSTEM_BATCH

#include "world.hpp"
#include "entity.hpp"
#include "query.hpp"

#include <functional>
#include <vector>

// Forward declaration
class Match;

namespace blunted {

/// 系统批处理：将多个系统合并为一个执行单元
template <typename... Components>
class SystemBatch {
 public:
  using SystemFn = std::function<void(World&, Entity, Components&...)>;

  SystemBatch() = default;

  /// 添加系统到批处理
  void AddSystem(SystemFn system) {
    systems_.push_back(std::move(system));
  }

  /// 执行批处理：遍历一次实体，执行所有系统
  void Execute(World& world) {
    // 使用查询接口获取所有拥有指定组件的实体
    auto result = Query<Components...>(world).Execute();
    
    for (Entity e : result) {
      // 获取所有组件
      auto* components = GetComponents(world, e);
      if (!components) continue;
      
      // 执行所有系统
      for (auto& system : systems_) {
        system(world, e, *components);
      }
    }
  }

  /// 获取系统数量
  size_t SystemCount() const { return systems_.size(); }

 private:
  /// 获取实体的所有组件（辅助函数）
  template <size_t... Is>
  auto* GetComponents(World& world, Entity e, std::index_sequence<Is...>) {
    using FirstComponent = std::tuple_element_t<0, std::tuple<Components...>>;
    auto* primary_pool = world.GetPool<FirstComponent>();
    if (!primary_pool) return nullptr;
    
    // 检查所有组件是否存在
    if ((!world.HasComponent<Components>(e) || ...)) {
      return nullptr;
    }
    
    // 返回组件元组
    return std::make_tuple(world.GetComponent<Components>(e)...);
  }

  /// 获取实体的所有组件（非模板版本）
  auto* GetComponents(World& world, Entity e) {
    return GetComponents(world, e, std::index_sequence_for<Components...>{});
  }

  std::vector<SystemFn> systems_;
};

/// 球员系统批处理：合并 PlayerState 和 HumanoidState 系统
class PlayerSystemBatch {
 public:
  void Execute(World& world);
};

/// 裁判组系统批处理：合并裁判组相关系统
class OfficialsSystemBatch {
 public:
  void Execute(World& world, Match* match);
};

/// 控球统计批处理：合并两个队伍的控球统计
class PossessionStatsBatch {
 public:
  void Execute(World& world, Match* match, int first_team, int second_team);
};

/// Team 系统批处理：合并 Team 相关系统
class TeamSystemBatch {
 public:
  void Execute(World& world, Match* match, int team_id);
};

/// Referee 系统批处理：合并 Referee 相关系统
class RefereeSystemBatch {
 public:
  void Execute(World& world, Match* match);
};

/// MentalImage 系统批处理：合并 MentalImage 相关系统
class MentalImageSystemBatch {
 public:
  void Execute(World& world, Match* match);
};

/// 完整游戏逻辑批处理：合并所有游戏逻辑系统
class GameLogicBatch {
 public:
  void Execute(World& world, Match* match);
};

}  // namespace blunted

#endif
