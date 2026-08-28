// Copyright 2026 Google LLC & Contributors
// P2-Phase4：ECS World 序列化工具（简化版）
// 将 World 中所有实体和组件序列化到二进制缓冲区并反序列化恢复。

#ifndef _HPP_ECS_SERIALIZER
#define _HPP_ECS_SERIALIZER

#include "world.hpp"
#include "entity.hpp"

#include <cstring>
#include <typeindex>
#include <unordered_map>
#include <vector>

namespace blunted {

/// 序列化后的组件数据
struct SerializedComponent {
  Entity entity;
  std::vector<unsigned char> bytes;
};

/// 序列化后的 World 状态
struct SerializedWorld {
  int entity_count = 0;
  // type_index → 该类型所有实体的组件数据
  std::unordered_map<std::type_index, std::vector<SerializedComponent>> pools;
};

/// World 序列化/反序列化工具
class WorldSerializer {
 public:
  /// 序列化 World 中所有拥有组件 T 的实体
  template <typename T>
  static void SerializePool(const World& world, SerializedWorld& result) {
    auto key = std::type_index(typeid(T));
    auto& pool = result.pools[key];
    world.ForEach<T>([&](Entity e, const T& comp) {
      SerializedComponent sc;
      sc.entity = e;
      sc.bytes.resize(sizeof(T));
      std::memcpy(sc.bytes.data(), &comp, sizeof(T));
      pool.push_back(std::move(sc));
    });
  }

  /// 序列化多个组件类型
  template <typename T, typename... Rest>
  static void SerializePools(const World& world, SerializedWorld& result) {
    SerializePool<T>(world, result);
    if constexpr (sizeof...(Rest) > 0) {
      SerializePools<Rest...>(world, result);
    }
  }

  /// 从 World 读取实体数量并填充
  template <typename T>
  static void CountEntities(const World& world, SerializedWorld& result) {
    int count = 0;
    world.ForEach<T>([&](Entity, const T&) { count++; });
    result.entity_count = std::max(result.entity_count, count);
  }

  template <typename T, typename... Rest>
  static void CountAllEntities(const World& world, SerializedWorld& result) {
    CountEntities<T>(world, result);
    if constexpr (sizeof...(Rest) > 0) {
      CountAllEntities<Rest...>(world, result);
    }
  }

  /// 完整序列化
  template <typename... Ts>
  static SerializedWorld Serialize(const World& world) {
    SerializedWorld result;
    SerializePools<Ts...>(world, result);
    return result;
  }

  /// 反序列化单个组件类型到新 World
  template <typename T>
  static void DeserializePool(World& world, const SerializedWorld& data,
                               const std::unordered_map<Entity, Entity>& id_map) {
    auto key = std::type_index(typeid(T));
    auto it = data.pools.find(key);
    if (it == data.pools.end()) return;
    for (const auto& sc : it->second) {
      auto id_it = id_map.find(sc.entity);
      if (id_it == id_map.end()) continue;
      if (sc.bytes.size() != sizeof(T)) continue;
      T comp;
      std::memcpy(&comp, sc.bytes.data(), sizeof(T));
      world.AddComponent(id_it->second, comp);
    }
  }

  template <typename T, typename... Rest>
  static void DeserializePools(World& world, const SerializedWorld& data,
                                const std::unordered_map<Entity, Entity>& id_map) {
    DeserializePool<T>(world, data, id_map);
    if constexpr (sizeof...(Rest) > 0) {
      DeserializePools<Rest...>(world, data, id_map);
    }
  }

  /// 完整反序列化：清空 World，重建实体和组件
  template <typename... Ts>
  static void Deserialize(World& world, const SerializedWorld& data) {
    world.Clear();
    // 收集所有唯一实体 ID
    std::vector<Entity> all_entities;
    for (const auto& [key, pool] : data.pools) {
      for (const auto& sc : pool) {
        bool found = false;
        for (Entity e : all_entities) {
          if (e == sc.entity) { found = true; break; }
        }
        if (!found) all_entities.push_back(sc.entity);
      }
    }
    // 按旧 ID 排序（确定性）
    std::sort(all_entities.begin(), all_entities.end());

    // 创建新实体并建立 ID 映射
    std::unordered_map<Entity, Entity> id_map;
    for (Entity old_id : all_entities) {
      Entity new_id = world.CreateEntity();
      id_map[old_id] = new_id;
    }

    // 反序列化每个组件类型
    DeserializePools<Ts...>(world, data, id_map);
  }
};

}  // namespace blunted

#endif
