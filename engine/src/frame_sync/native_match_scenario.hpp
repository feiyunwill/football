// 2026-09-13: product cadence owns a fresh scenario; original benchmark scenario stays immutable.
#pragma once
#include "frame_sync/native_match_contract.hpp"
#include "frame_sync/default_scenario.hpp"
namespace frame_sync {
inline std::shared_ptr<ScenarioConfig> MakeNativeMatchScenario(const NativeMatchContract& contract) {
  contract.Validate();
  auto scenario=MakeDefaultScenario(contract.left,contract.right,contract.seed);
  scenario->game_duration=NativeMatchContract::kDuration;
  return scenario;
}
}
