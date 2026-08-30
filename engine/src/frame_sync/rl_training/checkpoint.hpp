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

#include <fstream>
#include <vector>
#include <cstdio>  // 2026-08-30: printf instead of std::println

RL_TOOLS_NAMESPACE_WRAPPER_START
namespace rl_tools::checkpoint {

// ===== Save checkpoint =====
template <typename DEVICE, typename T_CONFIG>
bool save_checkpoint(DEVICE& device,
                     rl::algorithms::ppo::loop::core::State<T_CONFIG>& ts,
                     const char* path) {
  using TI = typename DEVICE::index_t;

  // Create TAR writer in memory
  persist::backends::tar::Writer writer;
  using WriterSpec = persist::backends::tar::WriterGroupSpecification<TI, persist::backends::tar::Writer>;
  persist::backends::tar::WriterGroup<WriterSpec> root_group;
  root_group.path[0] = '\0';
  root_group.writer = &writer;
  root_group.meta[0] = '\0';
  root_group.meta_position = 0;
  root_group.success = true;

  // Save the full PPO loop state
  save(device, ts, root_group);

  // Finalize TAR
  persist::backends::tar::finalize(device, writer);

  // Write buffer to file
  std::ofstream ofs(path, std::ios::binary);
  if (!ofs.is_open()) {
    fprintf(stderr, "checkpoint: failed to open %s for writing\n", path);
    return false;
  }
  ofs.write(writer.buffer.data(), static_cast<std::streamsize>(writer.buffer.size()));
  ofs.close();

  printf("checkpoint: saved %zu bytes to %s\n", writer.buffer.size(), path);
  return true;
}

// ===== Load checkpoint =====
template <typename DEVICE, typename T_CONFIG>
bool load_checkpoint(DEVICE& device,
                     rl::algorithms::ppo::loop::core::State<T_CONFIG>& ts,
                     const char* path) {
  using TI = typename DEVICE::index_t;

  // Read entire TAR file into memory
  std::ifstream ifs(path, std::ios::binary | std::ios::ate);
  if (!ifs.is_open()) {
    fprintf(stderr, "checkpoint: failed to open %s for reading\n", path);
    return false;
  }
  auto file_size = ifs.tellg();
  ifs.seekg(0, std::ios::beg);

  std::vector<char> buffer(file_size);
  if (!ifs.read(buffer.data(), file_size)) {
    fprintf(stderr, "checkpoint: failed to read %s\n", path);
    return false;
  }
  ifs.close();

  // Create TAR reader from in-memory buffer
  persist::backends::tar::BufferData<TI> data_backend;
  data_backend.data = buffer.data();
  data_backend.size = static_cast<TI>(file_size);

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
