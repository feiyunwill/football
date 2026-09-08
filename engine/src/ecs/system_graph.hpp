// Copyright 2026 Google LLC & Contributors
// P2-Phase5：系统依赖图（SystemGraph）
// 替代硬编码管线顺序，允许系统声明依赖关系，自动拓扑排序后按序执行。

#ifndef _HPP_ECS_SYSTEM_GRAPH
#define _HPP_ECS_SYSTEM_GRAPH

#include <algorithm>
#include <functional>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace blunted {

/// 系统执行函数签名：接受上下文指针，返回 bool（false = 中断管线）
using SystemFn = std::move_only_function<bool(void*)>;

/// 系统依赖图：注册系统 → 声明依赖 → 拓扑排序 → 按序执行
class SystemGraph {
 public:
  /// 注册一个系统
  /// @param name 系统唯一名称
  /// @param fn 执行函数
  /// @param depends_on 依赖的系统名称列表
  void Register(const std::string& name, SystemFn fn,
                std::vector<std::string> depends_on = {}) {
    systems_[name] = std::move(fn);
    dependencies_[name] = std::move(depends_on);
    sorted_ = false;
  }

  /// 拓扑排序：返回按依赖关系排序的系统名称列表
  /// 如果存在循环依赖，返回空 vector
  const std::vector<std::string>& Sort() {
    if (sorted_) return sorted_order_;

    sorted_order_.clear();
    std::unordered_set<std::string> visited;
    std::unordered_set<std::string> in_stack;

    for (const auto& [name, _] : systems_) {
      if (visited.count(name)) continue;
      if (!TopoSort(name, visited, in_stack)) {
        sorted_order_.clear();
        return sorted_order_;
      }
    }

    sorted_ = true;
    return sorted_order_;
  }

  /// 按拓扑顺序执行所有系统
  /// @param context 传递给每个系统函数的上下文指针
  /// @return true 所有系统执行成功，false 某系统中断
  bool Execute(void* context) {
    const auto& order = Sort();
    if (order.empty() && !systems_.empty()) {
      return false;  // 循环依赖
    }
    for (const auto& name : order) {
      auto it = systems_.find(name);
      if (it == systems_.end()) return false;
      if (!it->second(context)) return false;
    }
    return true;
  }

  /// 检查是否存在循环依赖
  bool HasCycle() {
    const auto& order = Sort();
    return order.empty() && !systems_.empty();
  }

  /// 获取已注册的系统数量
  size_t Size() const { return systems_.size(); }

  /// 清空所有系统
  void Clear() {
    systems_.clear();
    dependencies_.clear();
    sorted_order_.clear();
    sorted_ = false;
  }

 private:
  bool TopoSort(const std::string& name,
                std::unordered_set<std::string>& visited,
                std::unordered_set<std::string>& in_stack) {
    if (in_stack.count(name)) return false;  // 循环依赖
    if (visited.count(name)) return true;

    visited.insert(name);
    in_stack.insert(name);

    auto dep_it = dependencies_.find(name);
    if (dep_it != dependencies_.end()) {
      for (const auto& dep : dep_it->second) {
        if (!TopoSort(dep, visited, in_stack)) return false;
      }
    }

    in_stack.erase(name);
    sorted_order_.push_back(name);
    return true;
  }

  std::unordered_map<std::string, SystemFn> systems_;
  std::unordered_map<std::string, std::vector<std::string>> dependencies_;
  std::vector<std::string> sorted_order_;
  bool sorted_ = false;
};

}  // namespace blunted

#endif
