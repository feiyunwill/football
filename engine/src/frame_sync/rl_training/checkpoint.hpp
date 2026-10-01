// Copyright 2026 Google LLC & Contributors
// Checkpoint: save/load PPO training state to/from TAR archive
// Uses RLtools' TAR persistence backend (no HDF5 dependency)

#ifndef _HPP_CHECKPOINT
#define _HPP_CHECKPOINT

// TAR backend FIRST — operations must be visible when persist headers instantiate templates
#include <rl_tools/persist/backends/tar/tar.h>
#include <rl_tools/persist/backends/tar/io.h>
#include <rl_tools/persist/backends/tar/operations_cpu.h>
#include <rl_tools/persist/backends/tar/operations_generic.h>

// Then ALL persist headers (they use save/load/save_binary/load_binary from TAR)
#include <rl_tools/nn/layers/standardize/persist.h>
#include <rl_tools/nn/layers/dense/persist.h>
#include <rl_tools/nn/layers/gru/persist.h>
#include <rl_tools/nn/layers/sample_and_squash/persist.h>
#include <rl_tools/nn/layers/td3_sampling/persist.h>
#include <rl_tools/nn/layers/embedding/persist.h>
#include <rl_tools/nn/parameters/persist.h>
#include <rl_tools/nn/optimizers/adam/persist.h>
#include <rl_tools/nn/optimizers/adam/instance/persist.h>
#include <rl_tools/nn_models/mlp/persist.h>
#include <rl_tools/nn_models/mlp_unconditional_stddev/persist.h>
#include <rl_tools/nn_models/sequential/persist.h>
#include <rl_tools/nn_models/multi_agent_wrapper/persist.h>
#include <rl_tools/rl/algorithms/ppo/persist.h>
#include <rl_tools/rl/components/on_policy_runner/persist.h>
#include <rl_tools/rl/components/running_normalizer/persist.h>
#include <rl_tools/random/persist.h>

// PPO loop state (needed for full state save/load)
#include <rl_tools/rl/algorithms/ppo/loop/core/persist.h>
#include <rl_tools/rl/loop/steps/timing/persist.h>

#include "checkpoint_file.hpp"
#include "checkpoint_archive.hpp"
#include <limits>
#include <algorithm>
#include <exception>
#include <vector>
#include <cstdio>  // 2026-08-30: printf instead of std::println

RL_TOOLS_NAMESPACE_WRAPPER_START
namespace rl_tools::checkpoint {

template <typename DEVICE, typename T_CONFIG>
bool serialize_core(DEVICE& device,
                    rl::algorithms::ppo::loop::core::State<T_CONFIG>& ts,
                    std::vector<char>& bytes) {
  using TI = typename DEVICE::index_t;
  persist::backends::tar::Writer writer;
  using WriterSpec = persist::backends::tar::WriterGroupSpecification<TI, persist::backends::tar::Writer>;
  persist::backends::tar::WriterGroup<WriterSpec> root_group;
  root_group.path[0] = '\0';
  root_group.writer = &writer;
  root_group.meta[0] = '\0';
  root_group.meta_position = 0;
  root_group.success = true;

  save(device, ts, root_group);
  persist::backends::tar::finalize(device, writer);
  if (!root_group.success) return false;
  bytes = std::move(writer.buffer);
  return true;
}

// ===== Save checkpoint =====
template <typename DEVICE, typename T_CONFIG>
bool save_checkpoint(DEVICE& device,
                     rl::algorithms::ppo::loop::core::State<T_CONFIG>& ts,
                     const char* path) {
  try {
    if (!path) return false;
    std::vector<char> tar;
    if (!serialize_core(device, ts, tar)) {
      fprintf(stderr, "checkpoint: serialization failed\n");
      return false;
    }
    auto sealed = ::football::training::SealArchive(std::move(tar));
    const auto result = ::football::training::SaveCheckpointFile(
        std::span<const char>(sealed.data(), sealed.size()), path);
    if (!result) {
      fprintf(stderr, "checkpoint: %s failed (committed=%d, error=%d, cleanup=%d)\n",
              result.stage, result.committed, result.error.value(), result.cleanup_error.value());
      return false;
    }
    printf("checkpoint: saved %zu bytes to %s\n", result.bytes, path);
    return true;
  } catch (const std::exception& error) {
    fprintf(stderr, "checkpoint: save failed: %s\n", error.what()); return false;
  }
}

// ===== Load checkpoint =====
template <typename DEVICE, typename T_CONFIG>
bool load_checkpoint(DEVICE& device,
                     rl::algorithms::ppo::loop::core::State<T_CONFIG>& ts,
                     const char* path) {
  using TI = typename DEVICE::index_t;

  ::football::training::CheckpointFileRead file;
  try {
    if (!path) return false;
    const auto maximum = std::min<uintmax_t>(
        ::football::training::kMaxCheckpointFileBytes, std::numeric_limits<TI>::max());
    file = ::football::training::ReadCheckpointFile(path, static_cast<size_t>(maximum));
    if (!file) {
      fprintf(stderr, "checkpoint: %s failed (error=%d)\n", file.stage, file.error.value());
      return false;
    }
  } catch (const std::exception& error) {
    fprintf(stderr, "checkpoint: read failed: %s\n", error.what()); return false;
  }
  std::vector<char> expected;
  if (!serialize_core(device, ts, expected)) {
    fprintf(stderr, "checkpoint: failed to construct expected schema\n");
    return false;
  }
  std::string diagnostic;
  const auto tar = ::football::training::OpenArchive(file.bytes, expected, diagnostic);
  if (tar.empty()) {
    fprintf(stderr, "checkpoint: %s\n", diagnostic.c_str());
    return false;
  }

  // Create TAR reader from in-memory buffer
  persist::backends::tar::BufferData<TI> data_backend;
  data_backend.data = file.bytes.data();
  data_backend.size = static_cast<TI>(tar.size());

  using ReaderSpec = persist::backends::tar::ReaderGroupSpecification<TI, persist::backends::tar::BufferData<TI>>;
  persist::backends::tar::ReaderGroup<ReaderSpec> root_group;
  root_group.path[0] = '\0';
  root_group.data = data_backend;
  root_group.success = true;

  // Load the full PPO loop state
  bool success = load(device, ts, root_group);
  if (success) {
    printf("checkpoint: loaded from %s (step=%lu)\n", path, static_cast<unsigned long>(ts.step));
  } else {
    fprintf(stderr, "checkpoint: failed to load from %s\n", path);
  }
  return success;
}

}  // namespace rl_tools::checkpoint
RL_TOOLS_NAMESPACE_WRAPPER_END

#endif
